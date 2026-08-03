"""End-to-end tests for setting up the EARLY integration."""

from __future__ import annotations

import re

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.early.const import API_BASE_URL, CONF_API_SECRET, DOMAIN

# A Monday, so the day and week buckets start together.
NOW = "2026-08-03T10:00:00+00:00"

TRACKING = {
    "id": 1,
    "activity": {"id": "10", "name": "Deep Work", "color": "#123456", "folderId": "1"},
    "startedAt": "2026-08-03T09:30:00.000",
    "note": {
        "text": "quarterly report <{{|t|7|}}>",
        "tags": [{"id": 7, "label": "focus"}],
    },
}

ACTIVITIES = {
    "activities": [
        {"id": "10", "name": "Deep Work", "color": "#123456", "folderId": "1"},
        {"id": "11", "name": "Admin", "color": "#654321", "folderId": "1"},
    ]
}

TIME_ENTRIES = {
    "timeEntries": [
        # One hour earlier today.
        {
            "id": "1",
            "activity": ACTIVITIES["activities"][0],
            "duration": {
                "startedAt": "2026-08-03T08:00:00.000",
                "stoppedAt": "2026-08-03T09:00:00.000",
            },
        },
        # Two hours on Saturday: this month, but neither today nor this week.
        {
            "id": "2",
            "activity": ACTIVITIES["activities"][1],
            "duration": {
                "startedAt": "2026-08-01T08:00:00.000",
                "stoppedAt": "2026-08-01T10:00:00.000",
            },
        },
    ]
}


@pytest.fixture
def mock_early(aioclient_mock: AiohttpClientMocker) -> AiohttpClientMocker:
    """Mock a signed-in EARLY account with one running tracking."""
    aioclient_mock.post(f"{API_BASE_URL}/developer/sign-in", json={"token": "abc"})
    aioclient_mock.get(f"{API_BASE_URL}/tracking", json=TRACKING)
    aioclient_mock.get(f"{API_BASE_URL}/activities", json=ACTIVITIES)
    aioclient_mock.get(
        re.compile(rf"{re.escape(API_BASE_URL)}/time-entries/.*"), json=TIME_ENTRIES
    )
    aioclient_mock.post(f"{API_BASE_URL}/tracking/stop", json={"id": "99"})
    aioclient_mock.post(
        re.compile(rf"{re.escape(API_BASE_URL)}/tracking/\d+/start"), json=TRACKING
    )
    return aioclient_mock


@pytest.fixture
async def entry(hass: HomeAssistant, mock_early, freezer) -> MockConfigEntry:
    """Set up the integration at a fixed point in time."""
    freezer.move_to(NOW)
    await hass.config.async_set_time_zone("UTC")

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="42",
        title="me@example.com",
        data={CONF_API_KEY: "key", CONF_API_SECRET: "secret"},
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


async def test_entities_reflect_the_running_tracking(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The running tracking shows up across the platforms."""
    current = hass.states.get("sensor.me_example_com_current_activity")
    assert current is not None
    assert current.state == "Deep Work"
    assert current.attributes["activity_id"] == "10"
    assert current.attributes["color"] == "#123456"
    assert current.attributes["rgb_color"] == [18, 52, 86]
    assert current.attributes["note"] == "quarterly report #focus"
    assert current.attributes["tags"] == ["focus"]

    assert hass.states.get("binary_sensor.me_example_com_tracking").state == "on"
    assert (
        hass.states.get("sensor.me_example_com_tracking_started").state
        == "2026-08-03T09:30:00+00:00"
    )
    assert hass.states.get("sensor.me_example_com_current_duration").state == "30"


async def test_totals_include_the_running_tracking(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Totals add the elapsed part of the running tracking, clipped per window."""
    # 1 h completed today plus 30 min still running.
    assert hass.states.get("sensor.me_example_com_tracked_today").state == "1.5"
    # The Saturday entry falls outside the Monday-based week.
    assert hass.states.get("sensor.me_example_com_tracked_this_week").state == "1.5"
    # ... but inside the calendar month.
    assert hass.states.get("sensor.me_example_com_tracked_this_month").state == "3.5"


async def test_select_offers_the_activities_from_early(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The select mirrors the activity list rather than a hardcoded one."""
    select = hass.states.get("select.me_example_com_activity")
    assert select is not None
    assert select.attributes["options"] == ["Admin", "Deep Work"]
    # With nothing restored, the running tracking seeds the selection.
    assert select.state == "Deep Work"


async def test_start_button_uses_the_selected_activity(
    hass: HomeAssistant, entry: MockConfigEntry, mock_early: AiohttpClientMocker
) -> None:
    """Choosing an activity is what the start button acts on."""
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": "select.me_example_com_activity", "option": "Admin"},
        blocking=True,
    )
    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.me_example_com_start_tracking"},
        blocking=True,
    )
    await hass.async_block_till_done()

    started = [call for call in mock_early.mock_calls if "/start" in str(call[1])]
    assert started, "no start request was sent"
    assert str(started[-1][1]).endswith("/tracking/11/start")


async def test_start_tracking_service_resolves_the_activity_name(
    hass: HomeAssistant, entry: MockConfigEntry, mock_early: AiohttpClientMocker
) -> None:
    """The service takes an activity name and posts against its id."""
    await hass.services.async_call(
        DOMAIN, "start_tracking", {"activity": "admin"}, blocking=True
    )
    await hass.async_block_till_done()

    started = [call for call in mock_early.mock_calls if "/start" in str(call[1])]
    assert started, "no start request was sent"
    assert str(started[-1][1]).endswith("/tracking/11/start")


async def test_start_tracking_service_rejects_unknown_activity(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """An activity that EARLY does not know is a validation error."""
    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError, match="Nap"):
        await hass.services.async_call(
            DOMAIN, "start_tracking", {"activity": "Nap"}, blocking=True
        )


async def test_stop_tracking_service(
    hass: HomeAssistant, entry: MockConfigEntry, mock_early: AiohttpClientMocker
) -> None:
    """Stopping posts to the stop endpoint."""
    await hass.services.async_call(DOMAIN, "stop_tracking", {}, blocking=True)
    await hass.async_block_till_done()

    assert any("/tracking/stop" in str(call[1]) for call in mock_early.mock_calls)


async def test_stopping_leaves_the_entities_available(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """Stopping puts EARLY into the idle state that answers /tracking with 404.

    The refresh that follows a stop must not take the whole entry down with it.
    """
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{API_BASE_URL}/developer/sign-in", json={"token": "abc"})
    aioclient_mock.post(f"{API_BASE_URL}/tracking/stop", json={"id": "99"})
    aioclient_mock.get(
        f"{API_BASE_URL}/tracking", status=404, json={"message": "no tracking"}
    )
    aioclient_mock.get(f"{API_BASE_URL}/activities", json=ACTIVITIES)
    aioclient_mock.get(
        re.compile(rf"{re.escape(API_BASE_URL)}/time-entries/.*"), json=TIME_ENTRIES
    )

    await hass.services.async_call(
        "button",
        "press",
        {"entity_id": "button.me_example_com_stop_tracking"},
        blocking=True,
    )
    await hass.async_block_till_done()

    for entity_id in (
        "sensor.me_example_com_current_activity",
        "sensor.me_example_com_tracked_today",
        "binary_sensor.me_example_com_tracking",
        "select.me_example_com_activity",
    ):
        assert hass.states.get(entity_id).state != "unavailable", entity_id

    assert hass.states.get("binary_sensor.me_example_com_tracking").state == "off"
    assert hass.states.get("sensor.me_example_com_current_activity").state == "unknown"


async def test_stopping_while_idle_says_so(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """EARLY answers a pointless stop with 409 "no tracking in progress"."""
    from homeassistant.exceptions import HomeAssistantError

    aioclient_mock.clear_requests()
    aioclient_mock.post(
        f"{API_BASE_URL}/tracking/stop",
        status=409,
        json={"message": "there is no tracking in progress"},
    )

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(DOMAIN, "stop_tracking", {}, blocking=True)

    assert caught.value.translation_key == "not_tracking"
    # A pointless press must not take the integration down.
    assert entry.state is ConfigEntryState.LOADED
    assert (
        hass.states.get("binary_sensor.me_example_com_tracking").state != "unavailable"
    )


async def test_a_conflict_elsewhere_relays_earlys_wording(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """409 means something else per endpoint, so start keeps EARLY's text."""
    from homeassistant.exceptions import HomeAssistantError

    aioclient_mock.clear_requests()
    aioclient_mock.post(
        re.compile(rf"{re.escape(API_BASE_URL)}/tracking/\d+/start"),
        status=409,
        json={"message": "a tracking is already in progress"},
    )

    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call(
            DOMAIN, "start_tracking", {"activity": "Admin"}, blocking=True
        )

    assert caught.value.translation_key == "start_failed"
    assert "already in progress" in caught.value.translation_placeholders["error"]


async def test_back_to_back_actions_each_refresh(
    hass: HomeAssistant, entry: MockConfigEntry, mock_early: AiohttpClientMocker
) -> None:
    """A second action must not wait out a debounce cooldown.

    Time is frozen here, so a debounced refresh would never run at all.
    """

    def tracking_polls() -> int:
        return len(
            [
                call
                for call in mock_early.mock_calls
                # session.request() records "GET", session.get() records "get".
                if call[0].lower() == "get" and str(call[1]).endswith("/tracking")
            ]
        )

    before = tracking_polls()

    await hass.services.async_call(DOMAIN, "stop_tracking", {}, blocking=True)
    await hass.async_block_till_done()
    after_stop = tracking_polls()
    assert after_stop > before, "stop did not refresh"

    await hass.services.async_call(
        DOMAIN, "start_tracking", {"activity": "Admin"}, blocking=True
    )
    await hass.async_block_till_done()
    assert tracking_polls() > after_stop, "the second action was debounced away"


async def test_idle_tracking_is_not_an_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    """EARLY answers /tracking with a 404 while nothing is being tracked."""
    freezer.move_to(NOW)
    await hass.config.async_set_time_zone("UTC")

    aioclient_mock.post(f"{API_BASE_URL}/developer/sign-in", json={"token": "abc"})
    aioclient_mock.get(
        f"{API_BASE_URL}/tracking", status=404, json={"message": "no tracking"}
    )
    aioclient_mock.get(f"{API_BASE_URL}/activities", json=ACTIVITIES)
    aioclient_mock.get(
        re.compile(rf"{re.escape(API_BASE_URL)}/time-entries/.*"), json=TIME_ENTRIES
    )

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="42",
        title="me@example.com",
        data={CONF_API_KEY: "key", CONF_API_SECRET: "secret"},
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.me_example_com_current_activity").state == "unknown"
    assert hass.states.get("sensor.me_example_com_current_duration").state == "unknown"
    assert hass.states.get("binary_sensor.me_example_com_tracking").state == "off"
    # The completed entry from earlier today still counts.
    assert hass.states.get("sensor.me_example_com_tracked_today").state == "1.0"
    # The activity list is independent of whether something is running.
    assert hass.states.get("select.me_example_com_activity").attributes["options"] == [
        "Admin",
        "Deep Work",
    ]


async def test_unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The entry unloads cleanly and takes its entities down with it."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED
    assert (
        hass.states.get("sensor.me_example_com_current_activity").state == "unavailable"
    )
