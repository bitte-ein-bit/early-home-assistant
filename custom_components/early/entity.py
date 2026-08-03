"""Shared entity base for the EARLY (Timeular) integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EarlyDataUpdateCoordinator


class EarlyEntity(CoordinatorEntity[EarlyDataUpdateCoordinator]):
    """Base entity that ties every platform to the same service device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: EarlyDataUpdateCoordinator, entry: ConfigEntry, key: str
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="EARLY",
            name=entry.title,
            configuration_url="https://app.early.app",
        )
