"""Buttons for the EARLY (Timeular) integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EarlyConfigEntry
from .const import DOMAIN
from .coordinator import EarlyDataUpdateCoordinator
from .entity import EarlyEntity
from .errors import translated_errors


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EarlyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the EARLY buttons."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            EarlyStartButton(coordinator, entry),
            EarlyStopButton(coordinator, entry),
            EarlyCancelButton(coordinator, entry),
        ]
    )


class EarlyStartButton(EarlyEntity, ButtonEntity):
    """Starts tracking the activity chosen in the select entity."""

    _attr_icon = "mdi:play"

    def __init__(
        self, coordinator: EarlyDataUpdateCoordinator, entry: EarlyConfigEntry
    ) -> None:
        """Initialise the button."""
        super().__init__(coordinator, entry, "start")

    async def async_press(self) -> None:
        """Start tracking."""
        activity_id = self._entry.runtime_data.selected_activity_id
        if activity_id is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="no_activity_selected"
            )
        with translated_errors("start_failed"):
            await self.coordinator.api.async_start_tracking(activity_id)
        await self.coordinator.async_refresh_now()


class EarlyStopButton(EarlyEntity, ButtonEntity):
    """Stops the running tracking and keeps it as a time entry."""

    _attr_icon = "mdi:stop"

    def __init__(
        self, coordinator: EarlyDataUpdateCoordinator, entry: EarlyConfigEntry
    ) -> None:
        """Initialise the button."""
        super().__init__(coordinator, entry, "stop")

    async def async_press(self) -> None:
        """Stop tracking."""
        with translated_errors("stop_failed", conflict_key="not_tracking"):
            await self.coordinator.api.async_stop_tracking()
        await self.coordinator.async_refresh_now(totals=True)


class EarlyCancelButton(EarlyEntity, ButtonEntity):
    """Discards the running tracking without creating a time entry."""

    _attr_icon = "mdi:cancel"
    _attr_entity_registry_enabled_default = False

    def __init__(
        self, coordinator: EarlyDataUpdateCoordinator, entry: EarlyConfigEntry
    ) -> None:
        """Initialise the button."""
        super().__init__(coordinator, entry, "cancel")

    async def async_press(self) -> None:
        """Throw the running tracking away."""
        with translated_errors("cancel_failed", conflict_key="not_tracking"):
            await self.coordinator.api.async_cancel_tracking()
        await self.coordinator.async_refresh_now(totals=True)
