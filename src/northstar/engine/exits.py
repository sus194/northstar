"""Exit-watch rules (spec section 6).

Pure function over one position's current state; no I/O, no dedup logic --
callers (scripts/run_nightly.py) are responsible for "each condition emails
once per position", since that requires looking at what has already been
sent (ledger concern, not a rule concern).
"""

from __future__ import annotations

from dataclasses import dataclass

from northstar.config import ParameterVersion
from northstar.models import ExitReview, Position


@dataclass(frozen=True, slots=True)
class ExitContext:
    close: float
    as_of_date: object  # datetime.date, kept loose to avoid a circular import hint
    trading_days_since_fill: int
    regime_failed_two_consecutive: bool
    trading_days_to_nearest_earnings: int | None


def evaluate_exit(position: Position, ctx: ExitContext, params: ParameterVersion) -> list[ExitReview]:
    p = params.parameters
    triggered: list[ExitReview] = []

    if ctx.close <= position.stop:
        triggered.append(ExitReview(position.symbol, "stop", ctx.close, ctx.as_of_date))
    if ctx.close >= position.target:
        triggered.append(ExitReview(position.symbol, "target", ctx.close, ctx.as_of_date))
    if ctx.trading_days_since_fill >= int(p["E4_time_limit_trading_days"]):
        triggered.append(ExitReview(position.symbol, "time", ctx.close, ctx.as_of_date))
    if ctx.regime_failed_two_consecutive:
        triggered.append(ExitReview(position.symbol, "regime", ctx.close, ctx.as_of_date))
    if ctx.trading_days_to_nearest_earnings is not None and abs(ctx.trading_days_to_nearest_earnings) <= 2:
        triggered.append(ExitReview(position.symbol, "event", ctx.close, ctx.as_of_date))

    return triggered
