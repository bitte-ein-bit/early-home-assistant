"""Constants for the EARLY (Timeular) integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "early"

CONF_API_SECRET: Final = "api_secret"

API_BASE_URL: Final = "https://api.early.app/api/v4"

# How often the current tracking is polled. Everything else is derived from it.
DEFAULT_SCAN_INTERVAL: Final = timedelta(seconds=30)
# Completed time entries barely change while a tracking is running, so they are
# fetched on a slower cadence and refreshed eagerly whenever a tracking stops.
TIME_ENTRY_INTERVAL: Final = timedelta(minutes=5)
# The activity list is edited by hand in the EARLY app, so it changes rarely.
ACTIVITY_INTERVAL: Final = timedelta(minutes=15)

ATTR_ACTIVITY: Final = "activity"
ATTR_ACTIVITY_ID: Final = "activity_id"
ATTR_COLOR: Final = "color"
ATTR_FOLDER_ID: Final = "folder_id"
ATTR_MENTIONS: Final = "mentions"
ATTR_NOTE: Final = "note"
ATTR_STARTED_AT: Final = "started_at"
ATTR_TAGS: Final = "tags"

SERVICE_START_TRACKING: Final = "start_tracking"
SERVICE_STOP_TRACKING: Final = "stop_tracking"
SERVICE_CANCEL_TRACKING: Final = "cancel_tracking"
