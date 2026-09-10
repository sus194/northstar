"""Cost model, spec section 9.3.

Every function is a pure calculation so the backtest and any future
paper-trading slippage audit can call the same code.
"""

from __future__ import annotations

from dataclasses import dataclass

COMMISSION_CAD = 0.0


@dataclass(frozen=True, slots=True)
class FillResult:
    filled: bool
    fill_price: float | None
    reason: str


def entry_fill(*, next_open: float, entry_low: float, entry_high: float) -> FillResult:
    """Next-session open if inside the entry zone; otherwise expired_unfilled."""
    if entry_low <= next_open <= entry_high:
        return FillResult(True, next_open, "filled_at_open")
    return FillResult(False, None, "expired_unfilled")


def exit_fill(*, trigger_price: float, session_open: float) -> float:
    """Stop/target fill at the trigger level, or the next open if gapped
    through, whichever is worse for a long holder -- i.e. the lower of the
    two. This applies uniformly to stop exits (a gap-down means more loss
    than the stop implied) and target exits (a gap that happens to sit
    below the target on the fill day means less profit than the target
    implied); a favorable gap never gives a better-than-trigger fill.
    """
    return min(trigger_price, session_open)


def slippage_bps(dollar_volume_20d: float, low_liquidity_threshold: float = 10_000_000) -> float:
    return 5.0 if dollar_volume_20d < low_liquidity_threshold else 2.0


def spread_cost_per_side(price: float, median_spread_pct_60d: float) -> float:
    """Half the stored median spread, applied on each side of a round trip."""
    return price * (median_spread_pct_60d / 100.0) / 2.0


def apply_entry_costs(
    *, fill_price: float, median_spread_pct_60d: float, dollar_volume_20d: float
) -> float:
    spread = spread_cost_per_side(fill_price, median_spread_pct_60d)
    slip = fill_price * (slippage_bps(dollar_volume_20d) / 10_000.0)
    return fill_price + spread + slip


def apply_exit_costs(
    *, fill_price: float, median_spread_pct_60d: float, dollar_volume_20d: float
) -> float:
    spread = spread_cost_per_side(fill_price, median_spread_pct_60d)
    slip = fill_price * (slippage_bps(dollar_volume_20d) / 10_000.0)
    return fill_price - spread - slip
