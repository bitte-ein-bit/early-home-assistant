"""Data coordinator for the EARLY (Timeular) integration."""

from __future__ import annotations

import logging
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
    ACTIVITY_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ROLLING_DAYS,
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


def bucket_starts(now: datetime) -> tuple[datetime, datetime, datetime, datetime]:
    """Return the local start of today, the week, the month and the rolling window.

    The rolling window ends with today, so it spans ROLLING_DAYS days including
    today rather than ROLLING_DAYS days before it.
    """
    local_now = dt_util.as_local(now)
    day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = day - timedelta(days=day.weekday())
    month = day.replace(day=1)
    rolling = day - timedelta(days=ROLLING_DAYS - 1)
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
            update_interval=DEFAULT_SCAN_INTERVAL,
        )
        self.api = api
        self._activities_fetched: datetime | None = None
        self._entries_fetched: datetime | None = None
        self._entries_day: int | None = None
        self._last_tracked_id: str | None = None

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

            if self._totals_need_refresh(data, now):
                await self._async_update_totals(data, now)
                self._entries_fetched = now
                self._entries_day = dt_util.as_local(now).toordinal()
        except EarlyAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except EarlyError as err:
            raise UpdateFailed(str(err)) from err

        self._last_tracked_id = data.tracked_activity_id
        return data

    def _totals_need_refresh(self, data: EarlyData, now: datetime) -> bool:
        """Decide whether the completed totals have to be fetched again."""
        if self._is_stale(self._entries_fetched, now, TIME_ENTRY_INTERVAL):
            return True
        # A tracking that just stopped or switched produced a new time entry.
        if data.tracked_activity_id != self._last_tracked_id:
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
        windows = bucket_starts(now)
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
