"""Sensors for the EARLY (Timeular) integration."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import EarlyConfigEntry
from .const import (
    ATTR_ACTIVITY_ID,
    ATTR_COLOR,
    ATTR_FOLDER_ID,
    ATTR_MENTIONS,
    ATTR_NOTE,
    ATTR_REMAINING_HOURS,
    ATTR_RGB_COLOR,
    ATTR_STARTED_AT,
    ATTR_TAGS,
    ATTR_TARGET_HOURS,
    ATTR_TRACKED_HOURS,
)
from .coordinator import (
    EarlyData,
    EarlyDataUpdateCoordinator,
    bucket_starts,
    rolling_days,
)
from .entity import EarlyEntity
from .targets import rolling_target, target_between

_LOGGER = logging.getLogger(__name__)

# EARLY stores tags and mentions inside the note text as <{{|t|<id>|}}> and
# <{{|m|<id>|}}> markers, which are meaningless outside of their app.
_MARKER = re.compile(r"<\{\{\|([tm])\|(\d+)\|\}\}>")


def readable_note(note: dict[str, Any] | None) -> str | None:
    """Return the note text with tag and mention markers spelled out."""
    if not note or not (text := note.get("text")):
        return None

    labels = {
        ("t", str(tag.get("id"))): f"#{tag.get('label')}"
        for tag in note.get("tags") or []
    }
    labels.update(
        {
            ("m", str(mention.get("id"))): f"@{mention.get('label')}"
            for mention in note.get("mentions") or []
        }
    )

    def replace(match: re.Match[str]) -> str:
        return labels.get((match.group(1), match.group(2)), "")

    return _MARKER.sub(replace, text).strip() or None


def rgb_color(value: str | None) -> list[int] | None:
    """Convert EARLY's "#rrggbb" activity colour into an RGB triplet.

    Home Assistant has no hex-to-RGB template filter, and light.turn_on wants
    a triplet, so the conversion happens here rather than in everyone's
    automation.
    """
    if not value:
        return None
    text = value.removeprefix("#")
    if len(text) != 6:
        return None
    try:
        return [int(text[index : index + 2], 16) for index in (0, 2, 4)]
    except ValueError:
        _LOGGER.debug("Unparseable activity colour from EARLY: %s", value)
        return None


def _labels(note: dict[str, Any] | None, key: str) -> list[str]:
    """Return the labels of the note's tags or mentions."""
    if not note:
        return []
    return [str(item.get("label")) for item in note.get(key) or [] if item.get("label")]


def _live_seconds(data: EarlyData, window_start: datetime, now: datetime) -> float:
    """Return the seconds the running tracking contributes to a window."""
    started_at = data.started_at
    if started_at is None:
        return 0.0
    return max((now - max(started_at, window_start)).total_seconds(), 0.0)


@dataclass(frozen=True, kw_only=True)
class EarlyWindowDescription(SensorEntityDescription):
    """Describes one of the rolling windows tracked time is summed over."""

    completed: Callable[[EarlyData], float]
    # Index into bucket_starts(): 0 = today, 1 = week, 2 = month, 3 = rolling.
    bucket: int
    # The rolling window's length is configurable, so its name carries it.
    rolling: bool = False


WINDOWS: tuple[EarlyWindowDescription, ...] = (
    EarlyWindowDescription(
        key="today", bucket=0, completed=lambda data: data.completed_today
    ),
    EarlyWindowDescription(
        key="week", bucket=1, completed=lambda data: data.completed_week
    ),
    EarlyWindowDescription(
        key="month", bucket=2, completed=lambda data: data.completed_month
    ),
    EarlyWindowDescription(
        key="rolling",
        bucket=3,
        completed=lambda data: data.completed_rolling,
        rolling=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EarlyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the EARLY sensors."""
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = [
        EarlyCurrentActivitySensor(coordinator, entry),
        EarlyStartedAtSensor(coordinator, entry),
        EarlyCurrentDurationSensor(coordinator, entry),
    ]
    for description in WINDOWS:
        entities.append(EarlyTotalSensor(coordinator, entry, description))
        entities.append(EarlyBalanceSensor(coordinator, entry, description))
    async_add_entities(entities)


class EarlyCurrentActivitySensor(EarlyEntity, SensorEntity):
    """The activity that is being tracked right now."""

    _attr_icon = "mdi:timeline-clock-outline"

    def __init__(
        self, coordinator: EarlyDataUpdateCoordinator, entry: EarlyConfigEntry
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, entry, "current_activity")

    @property
    def native_value(self) -> str | None:
        """Return the activity name, or None while nothing is tracked."""
        tracking = self.coordinator.data.tracking
        if not tracking:
            return None
        return (tracking.get("activity") or {}).get("name")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the details of the running tracking."""
        data = self.coordinator.data
        tracking = data.tracking or {}
        activity = tracking.get("activity") or {}
        note = tracking.get("note")
        return {
            ATTR_ACTIVITY_ID: data.tracked_activity_id,
            ATTR_COLOR: activity.get("color"),
            ATTR_RGB_COLOR: rgb_color(activity.get("color")),
            ATTR_FOLDER_ID: activity.get("folderId"),
            ATTR_STARTED_AT: data.started_at,
            ATTR_NOTE: readable_note(note),
            ATTR_TAGS: _labels(note, "tags"),
            ATTR_MENTIONS: _labels(note, "mentions"),
        }


class EarlyStartedAtSensor(EarlyEntity, SensorEntity):
    """When the running tracking started."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-start"

    def __init__(
        self, coordinator: EarlyDataUpdateCoordinator, entry: EarlyConfigEntry
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, entry, "started_at")

    @property
    def native_value(self) -> datetime | None:
        """Return the start of the running tracking."""
        return self.coordinator.data.started_at


class EarlyCurrentDurationSensor(EarlyEntity, SensorEntity):
    """How long the running tracking has been going."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self, coordinator: EarlyDataUpdateCoordinator, entry: EarlyConfigEntry
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, entry, "current_duration")

    @property
    def native_value(self) -> int | None:
        """Return whole minutes since the tracking started."""
        started_at = self.coordinator.data.started_at
        if started_at is None:
            return None
        # Whole minutes keep the recorder from writing a state every poll.
        return int((dt_util.utcnow() - started_at).total_seconds() // 60)


class EarlyWindowSensor(EarlyEntity, SensorEntity):
    """Shared arithmetic for the sensors that report on a rolling window."""

    entity_description: EarlyWindowDescription

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: EarlyDataUpdateCoordinator,
        entry: EarlyConfigEntry,
        description: EarlyWindowDescription,
        key: str,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, entry, key)
        self.entity_description = description
        if description.rolling:
            self._attr_translation_placeholders = {
                "days": str(rolling_days(entry.options))
            }

    @property
    def _window_start(self) -> datetime:
        """Return the local start of this sensor's window."""
        windows = bucket_starts(dt_util.utcnow(), rolling_days(self._entry.options))
        return windows[self.entity_description.bucket]

    @property
    def tracked_hours(self) -> float:
        """Return completed plus currently running hours in the window."""
        data = self.coordinator.data
        now = dt_util.utcnow()
        seconds = self.entity_description.completed(data) + _live_seconds(
            data, self._window_start, now
        )
        return round(seconds / 3600, 3)

    @property
    def target_hours(self) -> float:
        """Return the hours meant to be tracked over this sensor's window."""
        options = self._entry.options
        local_now = dt_util.as_local(dt_util.utcnow())
        if self.entity_description.rolling:
            target = rolling_target(options, local_now, rolling_days(options))
        else:
            target = target_between(
                options, self._window_start.date(), local_now.date()
            )
        return round(target, 3)


class EarlyTotalSensor(EarlyWindowSensor):
    """Tracked time over a rolling window, including the running tracking."""

    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(
        self,
        coordinator: EarlyDataUpdateCoordinator,
        entry: EarlyConfigEntry,
        description: EarlyWindowDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, entry, description, f"tracked_{description.key}")

    @property
    def native_value(self) -> float:
        """Return the tracked hours."""
        return self.tracked_hours


class EarlyBalanceSensor(EarlyWindowSensor):
    """Tracked time measured against the configured working-time target.

    Negative means hours still owed, positive means overtime. Today counts
    with its full target, so the value climbs to zero over the working day.
    """

    _attr_icon = "mdi:scale-balance"

    def __init__(
        self,
        coordinator: EarlyDataUpdateCoordinator,
        entry: EarlyConfigEntry,
        description: EarlyWindowDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, entry, description, f"balance_{description.key}")

    @property
    def native_value(self) -> float:
        """Return tracked minus target hours."""
        return round(self.tracked_hours - self.target_hours, 3)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the two sides of the comparison and what is left of it."""
        tracked = self.tracked_hours
        target = self.target_hours
        return {
            ATTR_TRACKED_HOURS: tracked,
            ATTR_TARGET_HOURS: target,
            ATTR_REMAINING_HOURS: round(max(target - tracked, 0.0), 3),
        }
