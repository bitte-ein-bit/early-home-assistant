"""Activity selector for the EARLY (Timeular) integration."""

from __future__ import annotations

from collections import Counter

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import EarlyConfigEntry
from .coordinator import Activity, EarlyDataUpdateCoordinator
from .entity import EarlyEntity


def option_names(activities: list[Activity]) -> dict[str, str]:
    """Map each activity id to a display name that is unique in the list.

    Activity names are free text in the EARLY app and may repeat, while the
    select platform requires distinct options.
    """
    counts = Counter(activity.name for activity in activities)
    return {
        activity.id: (
            activity.name
            if counts[activity.name] == 1
            else f"{activity.name} ({activity.id})"
        )
        for activity in activities
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EarlyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the EARLY activity select."""
    async_add_entities([EarlyActivitySelect(entry.runtime_data.coordinator, entry)])


class EarlyActivitySelect(EarlyEntity, SelectEntity, RestoreEntity):
    """Picks which activity the start button will track.

    The options follow the activity list in the EARLY app, so activities that
    are added, renamed or archived there show up without a restart.
    """

    _attr_icon = "mdi:format-list-bulleted"

    def __init__(
        self, coordinator: EarlyDataUpdateCoordinator, entry: EarlyConfigEntry
    ) -> None:
        """Initialise the select."""
        super().__init__(coordinator, entry, "activity")
        self._names: dict[str, str] = {}
        self._refresh_options()

    async def async_added_to_hass(self) -> None:
        """Restore the previous selection, or fall back to what is tracked."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            for activity_id, name in self._names.items():
                if name == last_state.state:
                    self._set_selection(activity_id)
                    return

        if (tracked := self.coordinator.data.tracked_activity_id) in self._names:
            self._set_selection(tracked)

    @property
    def options(self) -> list[str]:
        """Return the selectable activity names."""
        return sorted(self._names.values())

    @property
    def current_option(self) -> str | None:
        """Return the selected activity name, if it still exists."""
        return self._names.get(self._selected_id or "")

    @property
    def _selected_id(self) -> str | None:
        """Return the selected activity id."""
        return self._entry.runtime_data.selected_activity_id

    async def async_select_option(self, option: str) -> None:
        """Remember which activity the start button should use."""
        for activity_id, name in self._names.items():
            if name == option:
                self._set_selection(activity_id)
                self.async_write_ha_state()
                return
        raise ValueError(f"Unknown EARLY activity: {option}")

    def _set_selection(self, activity_id: str | None) -> None:
        """Store the selection where the other platforms can read it."""
        self._entry.runtime_data.selected_activity_id = activity_id

    @callback
    def _handle_coordinator_update(self) -> None:
        """Track activity changes made in the EARLY app."""
        self._refresh_options()
        super()._handle_coordinator_update()

    def _refresh_options(self) -> None:
        """Rebuild the options from the latest activity list."""
        self._names = option_names(self.coordinator.data.activities)
        if self._selected_id is not None and self._selected_id not in self._names:
            # The activity was archived or deleted in the EARLY app.
            self._set_selection(None)
