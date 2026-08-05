"""The working-time target that tracked hours are measured against."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from .const import DEFAULT_WORKDAY_HOURS, WEEKDAYS


def daily_target(options: Mapping[str, Any], day: date) -> float:
    """Return the hours that are meant to be tracked on the given day."""
    weekday = day.weekday()
    value = options.get(WEEKDAYS[weekday], DEFAULT_WORKDAY_HOURS[weekday])
    try:
        return max(float(value), 0.0)
    except (TypeError, ValueError):
        return 0.0


def target_between(options: Mapping[str, Any], first: date, last: date) -> float:
    """Return the target for every day in [first, last], both included.

    Today counts in full rather than pro rata, so the balance runs from minus
    a full day up to zero as the day is worked through, and answers "am I done
    yet" instead of "am I ahead of an imaginary clock".
    """
    total = 0.0
    day = first
    while day <= last:
        total += daily_target(options, day)
        day += timedelta(days=1)
    return total
