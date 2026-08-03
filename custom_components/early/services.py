"""Services for the EARLY (Timeular) integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import EarlyError
from .const import (
    ATTR_ACTIVITY,
    ATTR_NOTE,
    DOMAIN,
    SERVICE_CANCEL_TRACKING,
    SERVICE_START_TRACKING,
    SERVICE_STOP_TRACKING,
)

if TYPE_CHECKING:
    from . import EarlyConfigEntry

ATTR_CONFIG_ENTRY_ID = "config_entry_id"

_ENTRY_SCHEMA = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}

START_SCHEMA = vol.Schema(
    {
        **_ENTRY_SCHEMA,
        vol.Required(ATTR_ACTIVITY): cv.string,
        vol.Optional(ATTR_NOTE): cv.string,
    }
)
TRACKING_SCHEMA = vol.Schema(_ENTRY_SCHEMA)


def _async_get_entry(hass: HomeAssistant, call: ServiceCall) -> EarlyConfigEntry:
    """Return the config entry the call targets."""
    entries = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]

    if (entry_id := call.data.get(ATTR_CONFIG_ENTRY_ID)) is not None:
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )

    if len(entries) == 1:
        return entries[0]
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="entry_required" if entries else "no_entries",
    )


def _resolve_activity(entry: EarlyConfigEntry, value: str) -> str:
    """Resolve an activity id or (case-insensitive) name to an activity id."""
    activities = entry.runtime_data.coordinator.data.activities
    for activity in activities:
        if activity.id == value:
            return activity.id
    for activity in activities:
        if activity.name.casefold() == value.casefold():
            return activity.id
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_activity",
        translation_placeholders={
            "activity": value,
            "known": ", ".join(sorted(item.name for item in activities)) or "-",
        },
    )


async def _async_start_tracking(call: ServiceCall) -> None:
    """Handle the start_tracking service."""
    entry = _async_get_entry(call.hass, call)
    activity_id = _resolve_activity(entry, call.data[ATTR_ACTIVITY])
    coordinator = entry.runtime_data.coordinator
    try:
        await coordinator.api.async_start_tracking(
            activity_id, note=call.data.get(ATTR_NOTE)
        )
    except EarlyError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="start_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    await coordinator.async_refresh_now()


async def _async_stop_tracking(call: ServiceCall) -> None:
    """Handle the stop_tracking service."""
    coordinator = _async_get_entry(call.hass, call).runtime_data.coordinator
    try:
        await coordinator.api.async_stop_tracking()
    except EarlyError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="stop_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    await coordinator.async_refresh_now(totals=True)


async def _async_cancel_tracking(call: ServiceCall) -> None:
    """Handle the cancel_tracking service."""
    coordinator = _async_get_entry(call.hass, call).runtime_data.coordinator
    try:
        await coordinator.api.async_cancel_tracking()
    except EarlyError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="cancel_failed",
            translation_placeholders={"error": str(err)},
        ) from err
    await coordinator.async_refresh_now(totals=True)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the EARLY services once."""
    if hass.services.has_service(DOMAIN, SERVICE_START_TRACKING):
        return

    hass.services.async_register(
        DOMAIN, SERVICE_START_TRACKING, _async_start_tracking, schema=START_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_STOP_TRACKING, _async_stop_tracking, schema=TRACKING_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CANCEL_TRACKING, _async_cancel_tracking, schema=TRACKING_SCHEMA
    )
