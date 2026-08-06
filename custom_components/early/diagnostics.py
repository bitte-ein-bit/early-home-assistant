"""Diagnostics for the EARLY (Timeular) integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant

from . import EarlyConfigEntry
from .const import CONF_API_SECRET

TO_REDACT = {CONF_API_KEY, CONF_API_SECRET, "note", "text", "email"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: EarlyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    return {
        "scan_interval_seconds": (
            coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None
        ),
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "tracking": async_redact_data(data.tracking or {}, TO_REDACT),
        "activity_count": len(data.activities),
        "activities": [asdict(activity) for activity in data.activities],
        "selected_activity_id": entry.runtime_data.selected_activity_id,
        "totals_seconds": {
            "today": data.completed_today,
            "week": data.completed_week,
            "month": data.completed_month,
        },
    }
