"""Trading-day arithmetic.

v1 approximates the TSX trading calendar with a Mon-Fri business calendar
and no holiday list. This is a known simplification -- see
docs/known_limitations.md -- and should be replaced with a real TSX holiday
calendar (numpy busdaycalendar with holidays=[...]) before backtesting,
since holidays shift every "N trading days" computation by one and this
will silently bias fill/expiry dates around Canadian and US holidays that
don't align.
"""

from __future__ import annotations

from datetime import date

import numpy as np


def add_trading_days(start: date, n: int) -> date:
    if n == 0:
        return start
    result = np.busday_offset(start.isoformat(), n, roll="forward")
    return date.fromisoformat(str(result))


def trading_days_between(a: date, b: date) -> int:
    """Number of business days between a and b (b - a), signed."""
    if a == b:
        return 0
    sign = 1 if b > a else -1
    lo, hi = (a, b) if b > a else (b, a)
    count = int(np.busday_count(lo.isoformat(), hi.isoformat()))
    return sign * count


def trading_days_ago_from_dates(dates: list[date], as_of: date, event_date: date) -> int | None:
    """Signed trading-day offset of event_date relative to as_of, counted
    along a symbol's own observed trading calendar (its bar dates) rather
    than a generic business calendar, so it reflects actual sessions the
    stock traded rather than assuming every weekday was a session.
    """
    if event_date == as_of:
        return 0
    sorted_dates = sorted(set(dates) | {as_of, event_date})
    try:
        idx_as_of = sorted_dates.index(as_of)
        idx_event = sorted_dates.index(event_date)
    except ValueError:
        return None
    return idx_event - idx_as_of
