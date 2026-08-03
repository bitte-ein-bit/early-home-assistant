"""The EARLY (Timeular) integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EarlyApi
from .const import CONF_API_SECRET
from .coordinator import EarlyDataUpdateCoordinator
from .services import async_setup_services

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SELECT,
    Platform.SENSOR,
]


@dataclass
class EarlyRuntimeData:
    """Runtime state shared between the platforms of one config entry."""

    api: EarlyApi
    coordinator: EarlyDataUpdateCoordinator
    # Which activity the start button will track. Owned by the select entity.
    selected_activity_id: str | None = None


type EarlyConfigEntry = ConfigEntry[EarlyRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: EarlyConfigEntry) -> bool:
    """Set up EARLY from a config entry."""
    api = EarlyApi(
        async_get_clientsession(hass),
        entry.data[CONF_API_KEY],
        entry.data[CONF_API_SECRET],
    )
    coordinator = EarlyDataUpdateCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = EarlyRuntimeData(api=api, coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_setup_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EarlyConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
