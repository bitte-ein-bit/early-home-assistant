"""Tests for the time bucketing that backs the daily/weekly/monthly sensors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util

from custom_components.early.api import api_timestamp, parse_timestamp
from custom_components.early.coordinator import (
    Activity,
    bucket_starts,
    overlap_seconds,
    scan_interval,
)
from custom_components.early.select import option_names
from custom_components.early.sensor import readable_note, rgb_color


def utc(*args: int) -> datetime:
    """Build an aware UTC datetime."""
    return datetime(*args, tzinfo=UTC)


def test_api_timestamp_is_utc_without_suffix() -> None:
    """EARLY expects naive UTC timestamps with milliseconds."""
    assert api_timestamp(utc(2026, 8, 3, 5, 30, 0)) == "2026-08-03T05:30:00.000"


def test_parse_timestamp_assumes_utc() -> None:
    """A timestamp without a zone comes back as aware UTC."""
    assert parse_timestamp("2026-08-03T05:30:00.000") == utc(2026, 8, 3, 5, 30)


def test_parse_timestamp_handles_missing_value() -> None:
    """No timestamp means no value, not a crash."""
    assert parse_timestamp(None) is None
    assert parse_timestamp("not a date") is None


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        # Fully inside the window.
        (utc(2026, 8, 3, 10), utc(2026, 8, 3, 11), 3600),
        # Starts before the window: only the tail counts.
        (utc(2026, 8, 2, 23), utc(2026, 8, 3, 1), 3600),
        # Ends after the window: only the head counts.
        (utc(2026, 8, 3, 11), utc(2026, 8, 3, 13), 3600),
        # Completely outside.
        (utc(2026, 8, 1), utc(2026, 8, 1, 5), 0),
    ],
)
def test_overlap_seconds(start: datetime, end: datetime, expected: int) -> None:
    """An entry only contributes the part that falls inside the window."""
    window_start = utc(2026, 8, 3, 0)
    window_end = utc(2026, 8, 3, 12)
    assert overlap_seconds(start, end, window_start, window_end) == expected


def test_bucket_starts_are_local_midnight() -> None:
    """Buckets are anchored to local midnight, not UTC midnight."""
    dt_util.set_default_time_zone(ZoneInfo("Europe/Berlin"))
    try:
        # 2026-08-03 is a Monday, so day and week start together.
        day, week, month, rolling = bucket_starts(utc(2026, 8, 3, 5, 30))
        assert day.isoformat() == "2026-08-03T00:00:00+02:00"
        assert week == day
        assert month.isoformat() == "2026-08-01T00:00:00+02:00"
        # The rolling window is not anchored to midnight: it reaches back
        # exactly 28 x 24 h from now, so it keeps the time of day.
        assert rolling.isoformat() == "2026-07-06T07:30:00+02:00"

        # 00:30 UTC on the 4th is already 02:30 local on the 4th.
        day, _, _, _ = bucket_starts(utc(2026, 8, 4, 0, 30))
        assert day.isoformat() == "2026-08-04T00:00:00+02:00"

        # 23:30 UTC on the 4th is 01:30 local on the 5th.
        day, week, _, _ = bucket_starts(utc(2026, 8, 4, 23, 30))
        assert day.isoformat() == "2026-08-05T00:00:00+02:00"
        assert week.isoformat() == "2026-08-03T00:00:00+02:00"
    finally:
        dt_util.set_default_time_zone(dt_util.UTC)


def test_option_names_disambiguates_duplicates() -> None:
    """Activities may share a name, select options may not."""
    names = option_names(
        [
            Activity(id="1", name="Deep Work"),
            Activity(id="2", name="Admin"),
            Activity(id="3", name="Admin"),
        ]
    )
    assert names == {"1": "Deep Work", "2": "Admin (2)", "3": "Admin (3)"}


def test_readable_note_replaces_markers() -> None:
    """Tag and mention markers are swapped for their labels."""
    note = {
        "text": "review <{{|t|1|}}> with <{{|m|2|}}>",
        "tags": [{"id": 1, "label": "billable"}],
        "mentions": [{"id": 2, "label": "team"}],
    }
    assert readable_note(note) == "review #billable with @team"


def test_readable_note_drops_unknown_markers() -> None:
    """A marker without a matching tag leaves no debris behind."""
    note = {"text": "review <{{|t|9|}}>", "tags": [], "mentions": []}
    assert readable_note(note) == "review"


def test_readable_note_without_text() -> None:
    """An empty note has no readable form."""
    assert readable_note(None) is None
    assert readable_note({"text": None}) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("#123456", [18, 52, 86]),
        ("#000000", [0, 0, 0]),
        ("#FFFFFF", [255, 255, 255]),
        # Lower case and a missing hash both turn up in the wild.
        ("abcdef", [171, 205, 239]),
        # Nothing usable: the attribute stays absent rather than guessing.
        (None, None),
        ("", None),
        ("#abc", None),
        ("#gggggg", None),
    ],
)
def test_rgb_color(value: str | None, expected: list[int] | None) -> None:
    """The hex colour becomes the triplet that light.turn_on expects."""
    assert rgb_color(value) == expected


@pytest.mark.parametrize(
    ("quiet_minutes", "expected_seconds"),
    [
        # Something just happened, or happened recently: stay responsive.
        (0, 30),
        (60, 30),
        (119, 30),
        # Two hours of nothing: back off.
        (120, 300),
        (600, 300),
    ],
)
def test_scan_interval_backs_off_when_quiet(
    quiet_minutes: int, expected_seconds: int
) -> None:
    """Polling slows down only after a full stretch without a change."""
    interval = scan_interval(timedelta(minutes=quiet_minutes))
    assert interval.total_seconds() == expected_seconds
