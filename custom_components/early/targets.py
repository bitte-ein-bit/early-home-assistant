"""The working-time target that tracked hours are measured against."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
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


SECONDS_PER_DAY = 24 * 60 * 60


def rolling_target(options: Mapping[str, Any], local_now: datetime, days: int) -> float:
    """Return the target for a window of exactly `days` × 24 h ending now.

    The window's ends fall inside a day rather than on midnight, so those two
    days count in proportion to how much of them the window covers. When `days`
    is a whole number of weeks the two are the same weekday, their shares add
    up to exactly one of that weekday, and the target therefore does not move
    at all as the window slides -- which is the point of the exercise.
    """
    today = local_now.date()
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = (local_now - midnight).total_seconds() / SECONDS_PER_DAY
    elapsed = min(max(elapsed, 0.0), 1.0)

    first = today - timedelta(days=days)
    total = daily_target(options, first) * (1.0 - elapsed)
    total += daily_target(options, today) * elapsed
    total += target_between(
        options, first + timedelta(days=1), today - timedelta(days=1)
    )
    return total
