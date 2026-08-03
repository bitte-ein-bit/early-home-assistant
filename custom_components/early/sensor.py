"""Sensors for the EARLY (Timeular) integration."""

from __future__ import annotations

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
    ATTR_STARTED_AT,
    ATTR_TAGS,
)
from .coordinator import EarlyData, EarlyDataUpdateCoordinator, bucket_starts
from .entity import EarlyEntity

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
class EarlyTotalDescription(SensorEntityDescription):
    """Describes a tracked-time total over a rolling window."""

    completed: Callable[[EarlyData], float]
    window_start: Callable[[datetime], datetime]


TOTALS: tuple[EarlyTotalDescription, ...] = (
    EarlyTotalDescription(
        key="tracked_today",
        completed=lambda data: data.completed_today,
        window_start=lambda now: bucket_starts(now)[0],
    ),
    EarlyTotalDescription(
        key="tracked_week",
        completed=lambda data: data.completed_week,
        window_start=lambda now: bucket_starts(now)[1],
    ),
    EarlyTotalDescription(
        key="tracked_month",
        completed=lambda data: data.completed_month,
        window_start=lambda now: bucket_starts(now)[2],
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
    entities.extend(
        EarlyTotalSensor(coordinator, entry, description) for description in TOTALS
    )
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


class EarlyTotalSensor(EarlyEntity, SensorEntity):
    """Tracked time over a rolling window, including the running tracking."""

    entity_description: EarlyTotalDescription

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:chart-timeline-variant"

    def __init__(
        self,
        coordinator: EarlyDataUpdateCoordinator,
        entry: EarlyConfigEntry,
        description: EarlyTotalDescription,
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        """Return completed plus currently running hours in the window."""
        data = self.coordinator.data
        now = dt_util.utcnow()
        window_start = self.entity_description.window_start(now)
        seconds = self.entity_description.completed(data) + _live_seconds(
            data, window_start, now
        )
        return round(seconds / 3600, 3)
