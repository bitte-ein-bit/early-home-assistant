"""Data coordinator for the EARLY (Timeular) integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EarlyApi, EarlyAuthError, EarlyError, parse_timestamp
from .const import (
    ACTIVE_SCAN_INTERVAL,
    ACTIVITY_INTERVAL,
    CONF_ROLLING_DAYS,
    DEFAULT_ROLLING_DAYS,
    DOMAIN,
    IDLE_AFTER,
    IDLE_SCAN_INTERVAL,
    TIME_ENTRY_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Activity:
    """An activity that can be tracked."""

    id: str
    name: str
    color: str | None = None
    folder_id: str | None = None

    @classmethod
    def from_api(cls, payload: dict[str, Any]) -> Activity:
        """Build an activity from an API payload."""
        return cls(
            id=str(payload["id"]),
            name=payload.get("name") or str(payload["id"]),
            color=payload.get("color"),
            folder_id=payload.get("folderId"),
        )


@dataclass(slots=True)
class EarlyData:
    """Everything the entities render, as of the last refresh."""

    tracking: dict[str, Any] | None = None
    activities: list[Activity] = field(default_factory=list)
    # Completed seconds per bucket, excluding the running tracking.
    completed_today: float = 0.0
    completed_week: float = 0.0
    completed_month: float = 0.0
    completed_rolling: float = 0.0

    @property
    def tracked_activity_id(self) -> str | None:
        """Return the id of the activity being tracked, if any."""
        if not self.tracking:
            return None
        activity = self.tracking.get("activity") or {}
        return str(activity["id"]) if activity.get("id") is not None else None

    @property
    def tracking_signal(self) -> tuple[str | None, str | None]:
        """Identify the running tracking.

        Carries the tracking id as well as the activity, so stopping and
        restarting the same activity still reads as a change.
        """
        if not self.tracking:
            return (None, None)
        return (str(self.tracking.get("id")), self.tracked_activity_id)

    @property
    def started_at(self) -> datetime | None:
        """Return when the running tracking started."""
        if not self.tracking:
            return None
        return parse_timestamp(self.tracking.get("startedAt"))


def overlap_seconds(
    start: datetime, end: datetime, window_start: datetime, window_end: datetime
) -> float:
    """Return how many seconds of [start, end] fall inside the window."""
    first = max(start, window_start)
    last = min(end, window_end)
    return max((last - first).total_seconds(), 0.0)


def scan_interval(quiet_for: timedelta) -> timedelta:
    """Return how often to poll after a given stretch without a change.

    Backing off costs nothing for anything done from Home Assistant, which
    refreshes on the spot; it only delays noticing a change made in the app.
    """
    if quiet_for >= IDLE_AFTER:
        return IDLE_SCAN_INTERVAL
    return ACTIVE_SCAN_INTERVAL


def rolling_days(options: Mapping[str, Any]) -> int:
    """Return the configured length of the rolling window, in days."""
    try:
        days = int(float(options.get(CONF_ROLLING_DAYS, DEFAULT_ROLLING_DAYS)))
    except (TypeError, ValueError):
        return DEFAULT_ROLLING_DAYS
    return max(days, 1)


def bucket_starts(
    now: datetime, days: int = DEFAULT_ROLLING_DAYS
) -> tuple[datetime, datetime, datetime, datetime]:
    """Return the start of today, the week, the month and the rolling window.

    The first three are anchored to local midnight. The rolling one is not: it
    ends at `now` and reaches back exactly `days` × 24 h, so its contents leak
    out minute by minute instead of a whole day falling out at midnight.
    """
    local_now = dt_util.as_local(now)
    day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = day - timedelta(days=day.weekday())
    month = day.replace(day=1)
    rolling = local_now - timedelta(days=days)
    return day, week, month, rolling


class EarlyDataUpdateCoordinator(DataUpdateCoordinator[EarlyData]):
    """Polls the running tracking often and the derived totals rarely."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, api: EarlyApi
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=config_entry,
            update_interval=ACTIVE_SCAN_INTERVAL,
        )
        self.api = api
        self._activities_fetched: datetime | None = None
        self._entries_fetched: datetime | None = None
        self._entries_day: int | None = None
        self._last_signal: tuple[str | None, str | None] | None = None
        self._last_change: datetime | None = None

    async def async_refresh_now(self, *, totals: bool = False) -> None:
        """Refresh straight away after an action the user triggered.

        async_request_refresh is debounced with a 10 second cooldown, so a
        second action shortly after the first would not show up until that
        cooldown expired. Pass totals=True when a time entry was created or
        removed.
        """
        if totals:
            self._entries_fetched = None
        await self.async_refresh()

    async def _async_update_data(self) -> EarlyData:
        """Fetch the current state from EARLY."""
        previous = self.data or EarlyData()
        now = dt_util.utcnow()

        try:
            tracking = await self.api.async_get_tracking()

            activities = previous.activities
            if self._is_stale(self._activities_fetched, now, ACTIVITY_INTERVAL):
                activities = [
                    Activity.from_api(item)
                    for item in await self.api.async_get_activities()
                ]
                self._activities_fetched = now

            data = EarlyData(
                tracking=tracking,
                activities=activities,
                completed_today=previous.completed_today,
                completed_week=previous.completed_week,
                completed_month=previous.completed_month,
                completed_rolling=previous.completed_rolling,
            )

            changed = data.tracking_signal != self._last_signal

            if self._totals_need_refresh(changed, now):
                await self._async_update_totals(data, now)
                self._entries_fetched = now
                self._entries_day = dt_util.as_local(now).toordinal()
        except EarlyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EarlyError as err:
            raise UpdateFailed(str(err)) from err

        self._last_signal = data.tracking_signal
        if changed or self._last_change is None:
            self._last_change = now
        self.update_interval = scan_interval(now - self._last_change)
        return data

    def _totals_need_refresh(self, changed: bool, now: datetime) -> bool:
        """Decide whether the completed totals have to be fetched again."""
        if self._is_stale(self._entries_fetched, now, TIME_ENTRY_INTERVAL):
            return True
        # A tracking that just stopped, started or switched made a time entry.
        if changed:
            return True
        # Midnight moved the buckets underneath us.
        return self._entries_day != dt_util.as_local(now).toordinal()

    @staticmethod
    def _is_stale(last: datetime | None, now: datetime, interval: timedelta) -> bool:
        """Return whether a cached fetch has aged out."""
        return last is None or now - last >= interval

    async def _async_update_totals(self, data: EarlyData, now: datetime) -> None:
        """Sum the completed time entries into every window.

        One request covers all of them: it spans the earliest window start, and
        each entry is then counted against every window it falls into.
        """
        windows = bucket_starts(now, rolling_days(self.config_entry.options))
        entries = await self.api.async_get_time_entries(min(windows), now)

        totals = [0.0] * len(windows)
        for entry in entries:
            duration = entry.get("duration") or {}
            start = parse_timestamp(duration.get("startedAt"))
            end = parse_timestamp(duration.get("stoppedAt"))
            if start is None or end is None:
                continue
            for index, window_start in enumerate(windows):
                totals[index] += overlap_seconds(start, end, window_start, now)

        (
            data.completed_today,
            data.completed_week,
            data.completed_month,
            data.completed_rolling,
        ) = totals
