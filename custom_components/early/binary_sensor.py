"""Binary sensor for the EARLY (Timeular) integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EarlyConfigEntry
from .coordinator import EarlyDataUpdateCoordinator
from .entity import EarlyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EarlyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the EARLY binary sensor."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([EarlyTrackingBinarySensor(coordinator, entry)])


class EarlyTrackingBinarySensor(EarlyEntity, BinarySensorEntity):
    """Whether a tracking is running at all."""

    _attr_icon = "mdi:record-circle-outline"

    def __init__(
        self, coordinator: EarlyDataUpdateCoordinator, entry: EarlyConfigEntry
    ) -> None:
        """Initialise the binary sensor."""
        super().__init__(coordinator, entry, "tracking")

    @property
    def is_on(self) -> bool:
        """Return True while EARLY is tracking something."""
        return self.coordinator.data.tracking is not None
