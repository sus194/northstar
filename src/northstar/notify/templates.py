"""Email subject/body rendering, verbatim to spec section 7.

Kept as plain string templates (no Jinja) -- the content is short, fixed,
and needs to be reproducible byte-for-byte from a RuleResult + Signal, not
templated for reuse elsewhere.
"""

from __future__ import annotations

from datetime import date

from northstar.models import ExitReview, RuleInputs, Signal

FAILURE_REASONS = (
    "dip may be information not liquidity; "
    "sector may be leading the move; "
    "momentum can crash in rebounds."
)


def entry_subject(symbol: str, signal: Signal) -> str:
    return (
        f"Northstar entry review: {symbol} — "
        f"zone {signal.entry_low:.2f}–{signal.entry_high:.2f} — next session only"
    )


def entry_body(
    *,
    symbol: str,
    company_name: str,
    sector: str,
    signal: Signal,
    inputs: RuleInputs,
    vendor: str,
    bar_timestamp: str,
    review_url: str,
) -> str:
    lines = [
        f"{symbol} — {company_name}",
        f"Sector: {sector}",
        f"Setup: momentum-dip {signal.param_version}",
        "",
        f"Entry zone: {signal.entry_low:.2f}–{signal.entry_high:.2f}",
        f"Stop: {signal.stop:.2f}",
        f"Target: {signal.target:.2f}",
        f"Suggested shares: {signal.shares}",
        f"Dollar risk: {signal.dollar_risk:.2f}",
        f"Time limit: {signal.expiry_date.isoformat()}",
        "",
        "Rule inputs:",
        f"  12-2 month return: {_pct(inputs.formation_return)} (rank {_pct(inputs.formation_return_rank_pct)})",
        f"  5-day sector-relative return (D2): {_pct(inputs.dip_relative)} (rank {_pct(inputs.dip_relative_rank_pct)})",
        f"  ATR(14): {_fmt(inputs.atr_14)}",
        f"  Turnover ratio (5d/60d avg vol): {_fmt(inputs.turnover_ratio)}",
        f"  Days to next earnings: {inputs.days_to_next_earnings if inputs.days_to_next_earnings is not None else 'unknown'}",
        "",
        f"Reasons this could fail: {FAILURE_REASONS}",
        "",
        f"Data vendor: {vendor}. Bar timestamp: {bar_timestamp}.",
        "End-of-day data; confirm the live quote before ordering.",
        "",
        f"Review: {review_url}",
    ]
    return "\n".join(lines)


def quiet_subject(as_of: date) -> str:
    return f"Northstar: no setup for {as_of.isoformat()}"


def quiet_body(*, as_of: date, regime_pass: bool, counts_by_step: dict[str, int]) -> str:
    lines = [
        f"No setup for {as_of.isoformat()}.",
        f"Regime gate: {'passed' if regime_pass else 'failed (S&P/TSX Composite at or below 200-day SMA)'}",
        "",
        "Names reaching each rule step:",
    ]
    for step, count in counts_by_step.items():
        lines.append(f"  {step}: {count}")
    return "\n".join(lines)


def exit_subject(review: ExitReview) -> str:
    return f"Northstar exit review: {review.symbol} — {review.condition} at close {review.close:.2f}"


def exit_body(review: ExitReview) -> str:
    condition_text = {
        "stop": "the close reached or crossed the stop.",
        "target": "the close reached or crossed the target.",
        "time": "the position has reached its time limit.",
        "regime": "the regime gate has failed for two consecutive closes; review all open positions.",
        "event": "an earnings date falls within 2 trading days; the setup was not meant to hold through an announcement.",
    }[review.condition]
    return (
        f"{review.symbol} — condition triggered: {review.condition}\n"
        f"Close: {review.close:.2f} as of {review.as_of.isoformat()}\n\n"
        f"{condition_text}\n\n"
        "This is a review, not an instruction. You decide."
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%" if abs(value) < 5 else f"{value:.2f}"


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"
