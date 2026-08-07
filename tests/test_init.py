"""End-to-end tests for setting up the EARLY integration."""

from __future__ import annotations

import re

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
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
        # Three hours in July: inside the rolling 30 days, outside the month.
        {
            "id": "3",
            "activity": ACTIVITIES["activities"][0],
            "duration": {
                "startedAt": "2026-07-20T08:00:00.000",
                "stoppedAt": "2026-07-20T11:00:00.000",
            },
        },
        # Four hours long before the rolling window opened: counted nowhere.
        {
            "id": "4",
            "activity": ACTIVITIES["activities"][0],
            "duration": {
                "startedAt": "2026-05-04T08:00:00.000",
                "stoppedAt": "2026-05-04T12:00:00.000",
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


async def test_rolling_window_reaches_back_a_full_period(
    hass: HomeAssistant, entry: MockConfigEntry, mock_early: AiohttpClientMocker
) -> None:
    """The rolling sensors reach back past the start of the calendar month."""
    # 1 h today + 0.5 h running + 2 h on Saturday + 3 h on 20 July. The May
    # entry is older than the window and must not count.
    assert hass.states.get("sensor.me_example_com_tracked_last_28_days").state == "6.5"

    # One request serves every window, and it has to reach back far enough.
    ranges = [
        str(call[1])
        for call in mock_early.mock_calls
        if "/time-entries/" in str(call[1])
    ]
    assert ranges, "no time entry request was sent"
    assert "2026-07-06T10:00:00.000" in ranges[-1]


async def test_rolling_window_does_not_jump_at_midnight(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer
) -> None:
    """A day's work leaves the window as the clock passes it, not all at once.

    With a midnight-anchored window the whole of the oldest day dropped out at
    00:00, taking the balance down by a full working day every night.
    """
    # A single eight hour day, exactly 28 days before the day under test.
    aioclient_mock.post(f"{API_BASE_URL}/developer/sign-in", json={"token": "abc"})
    aioclient_mock.get(f"{API_BASE_URL}/tracking", status=404, json={"message": "idle"})
    aioclient_mock.get(f"{API_BASE_URL}/activities", json=ACTIVITIES)
    aioclient_mock.get(
        re.compile(rf"{re.escape(API_BASE_URL)}/time-entries/.*"),
        json={
            "timeEntries": [
                {
                    "id": "1",
                    "activity": ACTIVITIES["activities"][0],
                    "duration": {
                        "startedAt": "2026-07-07T08:00:00.000",
                        "stoppedAt": "2026-07-07T16:00:00.000",
                    },
                }
            ]
        },
    )

    freezer.move_to("2026-08-03T23:59:00+00:00")
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

    sensor = "sensor.me_example_com_tracked_last_28_days"
    assert float(hass.states.get(sensor).state) == pytest.approx(8.0)

    # Two minutes later, on the other side of midnight. The old window would
    # have dropped all eight hours here.
    freezer.move_to("2026-08-04T00:01:00+00:00")
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get(sensor).state) == pytest.approx(8.0)

    # It only starts leaving once the clock passes the hours it was worked.
    freezer.move_to("2026-08-04T12:00:00+00:00")
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get(sensor).state) == pytest.approx(4.0)

    # And is gone once the clock has passed all of them.
    freezer.move_to("2026-08-04T16:00:00+00:00")
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert float(hass.states.get(sensor).state) == pytest.approx(0.0)


async def test_rolling_balance_uses_the_same_target_rules(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The rolling balance counts weekday targets over its own window."""
    balance = hass.states.get("sensor.me_example_com_balance_last_28_days")
    assert balance is not None
    # Four whole weeks is exactly 20 weekdays at the default 8 hours, whatever
    # time of day the window happens to start at.
    assert balance.attributes["target_hours"] == pytest.approx(160.0)
    assert balance.attributes["tracked_hours"] == pytest.approx(6.5)
    assert float(balance.state) == pytest.approx(6.5 - 160.0)


async def test_rolling_window_length_is_configurable(
    hass: HomeAssistant, mock_early: AiohttpClientMocker, freezer
) -> None:
    """A shorter window changes the sensor name, the target and the reach back."""
    freezer.move_to(NOW)
    await hass.config.async_set_time_zone("UTC")

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="42",
        title="me@example.com",
        data={CONF_API_KEY: "key", CONF_API_SECRET: "secret"},
        options={"rolling_days": 14},
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # The configured length appears in the entity name, hence the entity id.
    tracked = hass.states.get("sensor.me_example_com_tracked_last_14_days")
    assert tracked is not None
    assert tracked.attributes["friendly_name"] == "me@example.com Tracked last 14 days"

    # From 20 July 10:00: that day's 08:00-11:00 entry is half out of the
    # window already, contributing one hour of its three.
    assert tracked.state == "4.5"

    balance = hass.states.get("sensor.me_example_com_balance_last_14_days")
    assert balance.attributes["target_hours"] == pytest.approx(10 * 8.0)

    # The single range request only reaches back as far as it has to.
    ranges = [
        str(call[1])
        for call in mock_early.mock_calls
        if "/time-entries/" in str(call[1])
    ]
    assert "2026-07-20T10:00:00.000" in ranges[-1]


async def test_polling_backs_off_while_nothing_changes(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer,
) -> None:
    """The tracking poll slows to 5 minutes after two quiet hours, then speeds up."""
    coordinator = entry.runtime_data.coordinator

    # A tracking is running and has just been seen, so polling stays fast.
    assert coordinator.update_interval.total_seconds() == 30

    # The same tracking, still running, two hours later.
    freezer.move_to("2026-08-03T12:01:00+00:00")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.update_interval.total_seconds() == 300

    # Now it stops. Noticing that is a change, so we go back to watching closely.
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{API_BASE_URL}/tracking", status=404, json={"message": "no tracking"}
    )
    aioclient_mock.get(f"{API_BASE_URL}/activities", json=ACTIVITIES)
    aioclient_mock.get(
        re.compile(rf"{re.escape(API_BASE_URL)}/time-entries/.*"), json=TIME_ENTRIES
    )

    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.update_interval.total_seconds() == 30

    # Idle counts as quiet too: nothing tracked, nothing changing.
    freezer.move_to("2026-08-03T14:02:00+00:00")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.update_interval.total_seconds() == 300


async def test_restarting_the_same_activity_counts_as_a_change(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    freezer,
) -> None:
    """A new tracking of the same activity is still a change, id included."""
    coordinator = entry.runtime_data.coordinator

    freezer.move_to("2026-08-03T12:01:00+00:00")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.update_interval.total_seconds() == 300

    # Same activity, but a different tracking: stopped and started again.
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{API_BASE_URL}/tracking", json={**TRACKING, "id": 2})
    aioclient_mock.get(f"{API_BASE_URL}/activities", json=ACTIVITIES)
    aioclient_mock.get(
        re.compile(rf"{re.escape(API_BASE_URL)}/time-entries/.*"), json=TIME_ENTRIES
    )

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.update_interval.total_seconds() == 30
    # It also produced a time entry, so the history was refetched.
    assert any("/time-entries/" in str(c[1]) for c in aioclient_mock.mock_calls)


async def test_history_is_not_refetched_on_every_poll(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    mock_early: AiohttpClientMocker,
    freezer,
) -> None:
    """The heavy range query runs on a slow cadence, not with every tracking poll."""

    def counts() -> tuple[int, int]:
        entries = len(
            [c for c in mock_early.mock_calls if "/time-entries/" in str(c[1])]
        )
        tracking = len(
            [
                c
                for c in mock_early.mock_calls
                if c[0].lower() == "get" and str(c[1]).endswith("/tracking")
            ]
        )
        return entries, tracking

    entries_before, tracking_before = counts()

    # Ten minutes of polling with nothing happening.
    for minute in range(1, 11):
        freezer.move_to(f"2026-08-03T10:{minute:02d}:00+00:00")
        await entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()

    entries_after, tracking_after = counts()
    assert tracking_after > tracking_before, "the tracking poll stopped running"
    assert entries_after == entries_before, "history was refetched while idle"


async def test_history_is_refetched_when_the_activity_changes(
    hass: HomeAssistant, entry: MockConfigEntry, aioclient_mock: AiohttpClientMocker
) -> None:
    """A stop or an activity switch creates a time entry, so history reloads."""

    def entry_requests() -> int:
        return len(
            [c for c in aioclient_mock.mock_calls if "/time-entries/" in str(c[1])]
        )

    # The tracking switched to the other activity behind our back.
    # clear_requests() also wipes the call log, so count from after it.
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"{API_BASE_URL}/tracking",
        json={**TRACKING, "activity": ACTIVITIES["activities"][1]},
    )
    aioclient_mock.get(f"{API_BASE_URL}/activities", json=ACTIVITIES)
    aioclient_mock.get(
        re.compile(rf"{re.escape(API_BASE_URL)}/time-entries/.*"), json=TIME_ENTRIES
    )

    assert entry_requests() == 0

    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert entry_requests() == 1


async def test_balance_compares_tracked_time_against_the_target(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Balance is tracked minus target, with today counted in full.

    The fixture freezes a Monday at 10:00 UTC with 1.5 h tracked, and no
    options are set, so the default 8 h weekday target applies.
    """
    balance = hass.states.get("sensor.me_example_com_balance_today")
    assert balance is not None
    assert float(balance.state) == pytest.approx(1.5 - 8.0)
    assert balance.attributes["tracked_hours"] == pytest.approx(1.5)
    assert balance.attributes["target_hours"] == pytest.approx(8.0)
    assert balance.attributes["remaining_hours"] == pytest.approx(6.5)

    # Monday is the first day of the week, so the week matches the day.
    week = hass.states.get("sensor.me_example_com_balance_this_week")
    assert float(week.state) == pytest.approx(1.5 - 8.0)

    # The month started on Saturday the 1st: two weekend days at zero, then
    # Monday. The Saturday entry counts towards tracked but not the target.
    month = hass.states.get("sensor.me_example_com_balance_this_month")
    assert month.attributes["target_hours"] == pytest.approx(8.0)
    assert float(month.state) == pytest.approx(3.5 - 8.0)


async def test_balance_follows_the_configured_target(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """Changing the working hours reloads the entry and moves the balance."""
    hass.config_entries.async_update_entry(
        entry, options={"monday": 1.5, "saturday": 0, "sunday": 0}
    )
    await hass.async_block_till_done()

    balance = hass.states.get("sensor.me_example_com_balance_today")
    # Exactly on target: 1.5 h tracked against a 1.5 h Monday.
    assert float(balance.state) == pytest.approx(0.0)
    assert balance.attributes["remaining_hours"] == pytest.approx(0.0)


async def test_options_flow_stores_the_hours(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    """The working time is editable from the integration's options."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    hours = {
        "monday": 8,
        "tuesday": 8,
        "wednesday": 8,
        "thursday": 8,
        "friday": 4,
        "saturday": 0,
        "sunday": 0,
        "rolling_days": 28,
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], hours)
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == hours


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
