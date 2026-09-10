"""Backtest replay harness (spec section 8/9).

Calls the exact same engine.evaluate.evaluate_date() the nightly job calls
-- this file's only extra job is bookkeeping: turning a sequence of daily
signals into filled/unfilled trades, applying the cost model, evaluating
exit rules on open positions, and marking equity to market. It is a
simulation loop, not new trading logic.

Known simplifications, stated per spec section 9.2 discipline:
  - Trading calendar is taken from index_bars() dates, not a dedicated TSX
    holiday calendar (see engine/calendar.py).
  - Equity is marked to market at each day's close; no intraday P&L.
  - One position per symbol at a time; partial fills are not modeled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from northstar.backtest.costs import apply_entry_costs, apply_exit_costs, exit_fill
from northstar.config import ParameterVersion
from northstar.engine.calendar import trading_days_ago_from_dates
from northstar.engine.evaluate import AlertRateState, PortfolioState, evaluate_date
from northstar.engine.exits import ExitContext, evaluate_exit
from northstar.models import Position, RuleResult
from northstar.providers.base import MarketDataProvider


@dataclass(slots=True)
class Trade:
    symbol: str
    signal_date: date
    param_version: str
    entry_low: float
    entry_high: float
    stop: float
    target: float
    shares: int
    dollar_risk: float
    fill_date: date | None = None
    fill_price: float | None = None
    exit_date: date | None = None
    exit_price: float | None = None
    exit_condition: str | None = None
    state: str = "pending"  # pending, expired_unfilled, open, closed

    @property
    def r_multiple(self) -> float | None:
        if self.fill_price is None or self.exit_price is None:
            return None
        risk_per_share = self.fill_price - self.stop
        if risk_per_share <= 0:
            return None
        return (self.exit_price - self.fill_price) / risk_per_share


@dataclass(slots=True)
class BacktestReport:
    trades: list[Trade]
    all_evaluations: list[RuleResult]
    equity_curve: list[tuple[date, float]]
    starting_equity: float


def run_backtest(
    *,
    provider: MarketDataProvider,
    params: ParameterVersion,
    start: date,
    end: date,
    starting_equity: float = 100_000.0,
) -> BacktestReport:
    index_df = provider.index_bars(start, end)
    if index_df.empty:
        raise ValueError("no index bars in range; cannot determine trading calendar")
    trading_days = sorted(index_df["date"].dt.date.unique().tolist())

    trades: list[Trade] = []
    all_evaluations: list[RuleResult] = []
    equity_curve: list[tuple[date, float]] = []

    open_positions: dict[str, Trade] = {}  # symbol -> Trade in "open" state
    pending_trade: Trade | None = None
    last_signal_date_by_symbol: dict[str, date] = {}
    entries_sent_this_week = 0
    current_week: tuple[int, int] | None = None
    cash = starting_equity
    regime_fail_streak = 0
    sector_by_symbol: dict[str, str] = {}
    for sec in provider.universe(end):
        sector_by_symbol[sec.symbol] = sec.gics_sector

    bar_cache: dict[str, pd.DataFrame] = {}

    def bars_for(symbol: str) -> pd.DataFrame:
        if symbol not in bar_cache:
            bar_cache[symbol] = provider.daily_bars(symbol, start.replace(year=start.year - 2), end)
        return bar_cache[symbol]

    for d in trading_days:
        iso_week = d.isocalendar()[:2]
        if iso_week != current_week:
            current_week = iso_week
            entries_sent_this_week = 0

        # 1. Try to fill yesterday's pending signal using today's open.
        if pending_trade is not None:
            df = bars_for(pending_trade.symbol)
            row = df[df["date"].dt.date == d]
            if not row.empty:
                today_open = float(row.iloc[0]["open"])
                if pending_trade.entry_low <= today_open <= pending_trade.entry_high:
                    spread = float(row.iloc[0].get("median_spread_60d_pct", 0.0) or 0.0)
                    dv = float(row.iloc[0].get("adv_20d_dollar", 0.0) or 0.0)
                    pending_trade.fill_date = d
                    pending_trade.fill_price = apply_entry_costs(
                        fill_price=today_open, median_spread_pct_60d=spread, dollar_volume_20d=dv
                    )
                    pending_trade.state = "open"
                    open_positions[pending_trade.symbol] = pending_trade
                    cash -= pending_trade.fill_price * pending_trade.shares
                else:
                    pending_trade.state = "expired_unfilled"
                trades.append(pending_trade)
            else:
                pending_trade.state = "expired_unfilled"
                trades.append(pending_trade)
            pending_trade = None

        # 2. Evaluate exits on open positions using today's close.
        index_row = index_df[index_df["date"].dt.date == d]
        index_close = float(index_row.iloc[0]["close"]) if not index_row.empty else None
        sma200 = index_df[index_df["date"].dt.date <= d]["close"].tail(200)
        regime_ok = index_close is not None and len(sma200) == 200 and index_close > sma200.mean()
        regime_fail_streak = 0 if regime_ok else regime_fail_streak + 1

        for symbol in list(open_positions.keys()):
            trade = open_positions[symbol]
            df = bars_for(symbol)
            row = df[df["date"].dt.date == d]
            if row.empty:
                continue
            close = float(row.iloc[0]["close"])
            fill_date = trade.fill_date
            bar_dates = df["date"].dt.date.tolist()
            days_since_fill = trading_days_ago_from_dates(bar_dates, fill_date, d) or 0

            position = Position(
                symbol=symbol,
                shares=trade.shares,
                fill_price=trade.fill_price,
                fill_date=trade.fill_date,
                stop=trade.stop,
                target=trade.target,
                time_limit_date=d,
            )
            ctx = ExitContext(
                close=close,
                as_of_date=d,
                trading_days_since_fill=days_since_fill,
                regime_failed_two_consecutive=regime_fail_streak >= 2,
                trading_days_to_nearest_earnings=None,
            )
            triggered = evaluate_exit(position, ctx, params)
            if triggered:
                condition = triggered[0].condition
                raw_exit_price = exit_fill(trigger_price=trade.stop if condition == "stop" else close, session_open=close)
                spread = float(row.iloc[0].get("median_spread_60d_pct", 0.0) or 0.0)
                dv = float(row.iloc[0].get("adv_20d_dollar", 0.0) or 0.0)
                trade.exit_date = d
                trade.exit_price = apply_exit_costs(
                    fill_price=raw_exit_price, median_spread_pct_60d=spread, dollar_volume_20d=dv
                )
                trade.exit_condition = condition
                trade.state = "closed"
                cash += trade.exit_price * trade.shares
                del open_positions[symbol]

        # 3. Mark equity to market.
        market_value = 0.0
        for symbol, trade in open_positions.items():
            df = bars_for(symbol)
            row = df[df["date"].dt.date == d]
            if not row.empty:
                market_value += float(row.iloc[0]["close"]) * trade.shares
        equity_curve.append((d, cash + market_value))

        # 4. Run the engine for tomorrow's candidate.
        portfolio = PortfolioState(
            account_value=cash + market_value,
            open_positions_symbols=frozenset(open_positions.keys()),
            open_positions_count=len(open_positions),
            open_positions_by_sector=_sector_counts(open_positions.keys(), sector_by_symbol),
        )
        alert_rate = AlertRateState(
            entries_sent_today=0,
            entries_sent_this_week=entries_sent_this_week,
            last_signal_date_by_symbol=last_signal_date_by_symbol,
        )
        result = evaluate_date(as_of=d, provider=provider, params=params, portfolio=portfolio, alert_rate=alert_rate)
        all_evaluations.extend(result.results)
        if result.signal is not None:
            entries_sent_this_week += 1
            last_signal_date_by_symbol[result.signal.evaluation_symbol] = d
            pending_trade = Trade(
                symbol=result.signal.evaluation_symbol,
                signal_date=d,
                param_version=result.signal.param_version,
                entry_low=result.signal.entry_low,
                entry_high=result.signal.entry_high,
                stop=result.signal.stop,
                target=result.signal.target,
                shares=result.signal.shares,
                dollar_risk=result.signal.dollar_risk,
            )

    return BacktestReport(
        trades=trades,
        all_evaluations=all_evaluations,
        equity_curve=equity_curve,
        starting_equity=starting_equity,
    )


def _sector_counts(symbols, sector_by_symbol: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in symbols:
        sector = sector_by_symbol.get(s, "unknown")
        counts[sector] = counts.get(sector, 0) + 1
    return counts
