"""Tests for the working-time target the balance sensors measure against."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.early.targets import daily_target, target_between

# 2026-08-03 is a Monday.
MONDAY = date(2026, 8, 3)
SATURDAY = date(2026, 8, 8)
SUNDAY = date(2026, 8, 9)

FULL_TIME = {
    "monday": 8,
    "tuesday": 8,
    "wednesday": 8,
    "thursday": 8,
    "friday": 8,
    "saturday": 0,
    "sunday": 0,
}


def test_defaults_are_a_monday_to_friday_week() -> None:
    """Without configuration the target is 8 hours on weekdays only."""
    assert daily_target({}, MONDAY) == 8.0
    assert daily_target({}, SATURDAY) == 0.0
    assert daily_target({}, SUNDAY) == 0.0


def test_configured_hours_win() -> None:
    """A part-time Friday is just another number per weekday."""
    options = {**FULL_TIME, "friday": 4.5}
    assert daily_target(options, date(2026, 8, 7)) == 4.5


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Strings arrive from the number selector round trip.
        ("6", 6.0),
        (7.5, 7.5),
        # Nonsense must not crash a sensor; it counts as no target.
        (None, 0.0),
        ("", 0.0),
        ("nope", 0.0),
        # A negative target is meaningless.
        (-3, 0.0),
    ],
)
def test_daily_target_is_forgiving(value: object, expected: float) -> None:
    """The stored option is whatever the UI wrote, so parse defensively."""
    assert daily_target({"monday": value}, MONDAY) == expected


def test_target_between_counts_both_ends() -> None:
    """Monday to Wednesday inclusive is three working days."""
    assert target_between(FULL_TIME, MONDAY, date(2026, 8, 5)) == 24.0


def test_target_between_skips_the_weekend() -> None:
    """A full week stays at 40 hours even though it spans seven days."""
    assert target_between(FULL_TIME, MONDAY, SUNDAY) == 40.0


def test_target_between_for_a_single_day() -> None:
    """The daily window is one day wide, not zero."""
    assert target_between(FULL_TIME, MONDAY, MONDAY) == 8.0
    assert target_between(FULL_TIME, SATURDAY, SATURDAY) == 0.0


def test_target_between_ignores_an_inverted_range() -> None:
    """An end before the start contributes nothing rather than looping."""
    assert target_between(FULL_TIME, date(2026, 8, 5), MONDAY) == 0.0
