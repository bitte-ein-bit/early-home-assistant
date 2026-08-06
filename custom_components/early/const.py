"""Constants for the EARLY (Timeular) integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "early"

CONF_API_SECRET: Final = "api_secret"

# EARLY's public API does not expose the working hours configured in its UI,
# so the target is kept here. Per weekday, because a single daily figure would
# put every weekend permanently in the red.
WEEKDAYS: Final = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
DEFAULT_WORKDAY_HOURS: Final = (8.0, 8.0, 8.0, 8.0, 8.0, 0.0, 0.0)

# Length of the rolling window, ending with today. Four weeks by default:
# a whole number of weeks always holds the same weekdays, so the target stays
# put as the window slides, where 30 days would step by a day's worth whenever
# the count of weekdays inside it changes.
CONF_ROLLING_DAYS: Final = "rolling_days"
DEFAULT_ROLLING_DAYS: Final = 28

API_BASE_URL: Final = "https://api.early.app/api/v4"

# How often the current tracking is polled. It is the most frequent call by a
# wide margin, so it backs off once nothing has changed for a while. Anything
# done from Home Assistant refreshes immediately either way, so the slower
# cadence only delays noticing a change made in the EARLY app itself.
ACTIVE_SCAN_INTERVAL: Final = timedelta(seconds=30)
IDLE_SCAN_INTERVAL: Final = timedelta(minutes=5)
IDLE_AFTER: Final = timedelta(hours=2)
# Completed time entries only change when a tracking stops, which the
# coordinator already reacts to, so the periodic fetch is just a safety net for
# edits made elsewhere. It is the heaviest call in the integration -- it returns
# every entry in the window -- so it runs rarely.
TIME_ENTRY_INTERVAL: Final = timedelta(hours=1)
# The activity list is edited by hand in the EARLY app, so it changes rarely.
ACTIVITY_INTERVAL: Final = timedelta(minutes=15)

ATTR_ACTIVITY: Final = "activity"
ATTR_ACTIVITY_ID: Final = "activity_id"
ATTR_COLOR: Final = "color"
ATTR_FOLDER_ID: Final = "folder_id"
ATTR_MENTIONS: Final = "mentions"
ATTR_NOTE: Final = "note"
ATTR_REMAINING_HOURS: Final = "remaining_hours"
ATTR_RGB_COLOR: Final = "rgb_color"
ATTR_STARTED_AT: Final = "started_at"
ATTR_TARGET_HOURS: Final = "target_hours"
ATTR_TRACKED_HOURS: Final = "tracked_hours"
ATTR_TAGS: Final = "tags"

SERVICE_START_TRACKING: Final = "start_tracking"
SERVICE_STOP_TRACKING: Final = "stop_tracking"
SERVICE_CANCEL_TRACKING: Final = "cancel_tracking"
