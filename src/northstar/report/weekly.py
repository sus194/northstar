"""Weekly strategy report, spec section 9.4.

Consumes a BacktestReport (or the equivalent ledger query against live/paper
data) and produces the numbers the go/no-go gates in section 9.5 are judged
against. This module only aggregates; it never decides pass/fail -- that
judgement belongs to a human reading the report, per principle 6 (parameters
are frozen before testing, so the report can't be allowed to quietly steer
them).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from northstar.backtest.harness import BacktestReport, Trade


@dataclass(slots=True)
class WeeklyReport:
    n_signals: int
    n_filled: int
    n_expired_unfilled: int
    n_closed: int
    win_rate: float | None
    mean_r: float | None
    median_r: float | None
    worst_5: list[Trade]
    holding_period_days_histogram: dict[int, int]
    max_drawdown_pct: float | None
    drawdown_duration_days: int | None
    exit_attribution: dict[str, int]
    veto_counts: dict[str, int]
    reject_step_counts: dict[str, int]
    total_return_pct: float | None


def build_report(bt: BacktestReport) -> WeeklyReport:
    filled = [t for t in bt.trades if t.state in ("open", "closed")]
    unfilled = [t for t in bt.trades if t.state == "expired_unfilled"]
    closed = [t for t in bt.trades if t.state == "closed"]

    r_values = [t.r_multiple for t in closed if t.r_multiple is not None]
    wins = [r for r in r_values if r > 0]

    win_rate = len(wins) / len(r_values) if r_values else None
    mean_r = sum(r_values) / len(r_values) if r_values else None
    median_r = _median(r_values) if r_values else None
    worst_5 = sorted((t for t in closed if t.r_multiple is not None), key=lambda t: t.r_multiple)[:5]

    holding_hist: dict[int, int] = Counter()
    for t in closed:
        if t.fill_date and t.exit_date:
            days = (t.exit_date - t.fill_date).days
            holding_hist[days] += 1

    max_dd, dd_duration = _drawdown(bt.equity_curve)

    exit_attribution = Counter(t.exit_condition for t in closed if t.exit_condition)
    reject_step_counts = Counter(
        r.reject_step.value for r in bt.all_evaluations if r.reject_step is not None
    )
    veto_counts = Counter(
        r.reject_reason for r in bt.all_evaluations if r.reject_step is not None and r.reject_step.value == "veto"
    )

    total_return_pct = None
    if bt.equity_curve:
        final_equity = bt.equity_curve[-1][1]
        total_return_pct = (final_equity / bt.starting_equity - 1.0) * 100.0

    return WeeklyReport(
        n_signals=len(bt.trades),
        n_filled=len(filled),
        n_expired_unfilled=len(unfilled),
        n_closed=len(closed),
        win_rate=win_rate,
        mean_r=mean_r,
        median_r=median_r,
        worst_5=worst_5,
        holding_period_days_histogram=dict(holding_hist),
        max_drawdown_pct=max_dd,
        drawdown_duration_days=dd_duration,
        exit_attribution=dict(exit_attribution),
        veto_counts=dict(veto_counts),
        reject_step_counts=dict(reject_step_counts),
        total_return_pct=total_return_pct,
    )


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _drawdown(equity_curve: list[tuple]) -> tuple[float | None, int | None]:
    if not equity_curve:
        return None, None
    peak = equity_curve[0][1]
    peak_date = equity_curve[0][0]
    max_dd = 0.0
    max_dd_duration = 0
    for d, equity in equity_curve:
        if equity > peak:
            peak = equity
            peak_date = d
        dd = (equity / peak - 1.0) * 100.0
        if dd < max_dd:
            max_dd = dd
            max_dd_duration = (d - peak_date).days
    return max_dd, max_dd_duration


def render_markdown(report: WeeklyReport) -> str:
    lines = [
        "# Northstar weekly strategy report",
        "",
        (
            f"Signals: {report.n_signals}  |  Filled: {report.n_filled}  |  "
            f"Expired unfilled: {report.n_expired_unfilled}  |  Closed: {report.n_closed}"
        ),
        "",
        f"Win rate: {_pct(report.win_rate)}",
        f"Mean R: {_num(report.mean_r)}  |  Median R: {_num(report.median_r)}",
        f"Max drawdown: {_pct2(report.max_drawdown_pct)}  over {report.drawdown_duration_days} days",
        f"Total return: {_pct2(report.total_return_pct)}",
        "",
        "## Exit attribution",
    ]
    for cond, n in sorted(report.exit_attribution.items()):
        lines.append(f"  {cond}: {n}")
    lines.append("")
    lines.append("## Rejections by rule step")
    for step, n in sorted(report.reject_step_counts.items()):
        lines.append(f"  {step}: {n}")
    lines.append("")
    lines.append("## Worst 5 trades (by R)")
    for t in report.worst_5:
        lines.append(f"  {t.symbol} {t.signal_date} R={_num(t.r_multiple)}")
    return "\n".join(lines)


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def _pct2(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.2f}%"


def _num(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.3f}"
