"""Nightly rule evaluation, per spec section 5.3.

evaluate_date() is the single entry point used by both the live nightly
job (scripts/run_nightly.py) and the backtest replay (backtest/harness.py)
-- this is what "backtest and live scan share the same engine code path"
(spec section 8 / acceptance criteria) means concretely.

It is a pure function of (as_of, provider snapshot, params, portfolio
state, alert-rate state) -> EvaluateResult. It performs no I/O beyond the
provider calls and returns data; callers decide what to persist and what
to email.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from northstar.config import ParameterVersion
from northstar.engine import indicators as ind
from northstar.engine import rules as R
from northstar.engine.calendar import trading_days_ago_from_dates
from northstar.engine.frame_builder import build_indicator_frame
from northstar.models import (
    CorporateEventType,
    RuleInputs,
    RuleResult,
    RuleStep,
    Signal,
)
from northstar.providers.base import MarketDataProvider

HISTORY_LOOKBACK_DAYS = 420  # calendar days back for daily_bars() calls; covers M1's 12mo window plus buffer

_EVENT_VETO_TYPES = frozenset(
    {
        CorporateEventType.EX_DIVIDEND,
        CorporateEventType.SPLIT,
        CorporateEventType.CONSOLIDATION,
        CorporateEventType.OTHER_MATERIAL,
    }
)


@dataclass(frozen=True, slots=True)
class PortfolioState:
    account_value: float
    open_positions_symbols: frozenset[str]
    open_positions_count: int
    open_positions_by_sector: dict[str, int]


@dataclass(frozen=True, slots=True)
class AlertRateState:
    entries_sent_today: int
    entries_sent_this_week: int
    last_signal_date_by_symbol: dict[str, date]


@dataclass(slots=True)
class EvaluateResult:
    as_of: date
    param_version: str
    regime_pass: bool
    results: list[RuleResult]
    signal: Signal | None
    counts_by_step_reached: dict[str, int] = field(default_factory=dict)


def _last_row_as_of(frame: pd.DataFrame, as_of: date) -> pd.Series | None:
    if frame.empty:
        return None
    match = frame[frame["date"].dt.date == as_of]
    if match.empty:
        return None
    return match.iloc[-1]


def evaluate_date(
    *,
    as_of: date,
    provider: MarketDataProvider,
    params: ParameterVersion,
    portfolio: PortfolioState,
    alert_rate: AlertRateState,
) -> EvaluateResult:
    securities = provider.universe(as_of)
    index_df = provider.index_bars(as_of - timedelta(days=400), as_of)
    index_row = _last_row_as_of(index_df, as_of) if not index_df.empty else None
    index_sma_200 = None
    index_close = None
    if index_row is not None:
        index_close = float(index_row["close"])
        sma_series = ind.sma(index_df["close"], 200)
        idx_pos = index_df.index[index_df["date"].dt.date == as_of]
        if len(idx_pos):
            val = sma_series.loc[idx_pos[0]]
            index_sma_200 = float(val) if not math.isnan(val) else None

    regime_outcome = R.check_regime(index_close=index_close, index_sma_200=index_sma_200)

    results: list[RuleResult] = []
    counts: dict[str, int] = {step.value: 0 for step in R.ORDERED_STEPS}

    if not regime_outcome.passed:
        for sec in securities:
            inputs = RuleInputs(symbol=sec.symbol, as_of=as_of, index_close=index_close, index_sma_200=index_sma_200)
            results.append(
                RuleResult(
                    symbol=sec.symbol,
                    as_of=as_of,
                    param_version=params.version,
                    inputs=inputs,
                    passed=False,
                    reject_step=RuleStep.REGIME,
                    reject_reason=regime_outcome.reason,
                )
            )
        return EvaluateResult(
            as_of=as_of,
            param_version=params.version,
            regime_pass=False,
            results=results,
            signal=None,
            counts_by_step_reached=counts,
        )

    counts[RuleStep.REGIME.value] = len(securities)

    frames: dict[str, pd.DataFrame] = {}
    rows: dict[str, pd.Series] = {}
    sectors: dict[str, str] = {}
    universe_pass: dict[str, RuleInputs] = {}

    for sec in securities:
        bars = provider.daily_bars(sec.symbol, as_of - timedelta(days=HISTORY_LOOKBACK_DAYS), as_of)
        if bars.empty:
            continue
        frame = build_indicator_frame(bars, params)
        row = _last_row_as_of(frame, as_of)
        if row is None:
            continue
        frames[sec.symbol] = frame
        rows[sec.symbol] = row
        sectors[sec.symbol] = sec.gics_sector

        inputs = RuleInputs(
            symbol=sec.symbol,
            as_of=as_of,
            adv_20d_dollar=_safe_float(row.get("adv_20d_dollar")),
            median_spread_60d_pct=_safe_float(row.get("median_spread_60d_pct")),
            price_history_days=int(row.get("price_history_days", 0)),
            price=_safe_float(row.get("close")),
            index_close=index_close,
            index_sma_200=index_sma_200,
            atr_14=_safe_float(row.get("atr_14")),
            sma_100=_safe_float(row.get("sma_100")),
            gics_sector=sec.gics_sector,
        )

        outcome = R.check_universe(
            adv_20d_dollar=inputs.adv_20d_dollar,
            median_spread_60d_pct=inputs.median_spread_60d_pct,
            price_history_days=inputs.price_history_days,
            price=inputs.price,
            is_etf=sec.is_etf,
            is_preferred=sec.is_preferred,
            status=sec.status,
            params=params,
        )
        if not outcome.passed:
            results.append(
                RuleResult(sec.symbol, as_of, params.version, inputs, False, RuleStep.UNIVERSE, outcome.reason)
            )
            continue
        counts[RuleStep.UNIVERSE.value] += 1
        universe_pass[sec.symbol] = inputs

    # Cross-sectional momentum rank (M2) over the universe-eligible set.
    formation_returns = {s: _safe_float(rows[s].get("formation_return")) for s in universe_pass}
    momentum_ranks = _percentile_rank(formation_returns)

    # Cross-sectional sector 5-day return, for the industry-relative dip (D2).
    stock_5d = {s: _safe_float(rows[s].get("stock_5d_return")) for s in universe_pass}
    sector_5d_avg = _sector_average(stock_5d, sectors)
    dip_relative = {
        s: (stock_5d[s] - sector_5d_avg[sectors[s]])
        for s in universe_pass
        if stock_5d[s] is not None and sectors[s] in sector_5d_avg
    }
    dip_ranks = _percentile_rank(dip_relative)

    momentum_survivors: list[str] = []
    for symbol, inputs in universe_pass.items():
        row = rows[symbol]
        formation_ret = formation_returns.get(symbol)
        rank_pct = momentum_ranks.get(symbol)
        inputs2 = _with(inputs, formation_return=formation_ret, formation_return_rank_pct=rank_pct)

        outcome = R.check_momentum(
            close=float(row["close"]),
            sma_100=inputs.sma_100,
            formation_return=formation_ret,
            momentum_rank_pct=rank_pct,
            params=params,
        )
        if not outcome.passed:
            results.append(RuleResult(symbol, as_of, params.version, inputs2, False, RuleStep.MOMENTUM, outcome.reason))
            continue
        counts[RuleStep.MOMENTUM.value] += 1
        universe_pass[symbol] = inputs2
        momentum_survivors.append(symbol)

    dip_survivors: list[str] = []
    for symbol in momentum_survivors:
        inputs = universe_pass[symbol]
        row = rows[symbol]
        depth = R.dip_depth_in_atr(
            close=float(row["close"]),
            close_high_20d=_safe_float(row.get("close_high_20d")) or float(row["close"]),
            atr_14=inputs.atr_14 or math.nan,
        )
        d2 = dip_relative.get(symbol)
        rank_pct = dip_ranks.get(symbol)
        inputs2 = _with(
            inputs,
            stock_5d_return=stock_5d.get(symbol),
            sector_5d_return=sector_5d_avg.get(sectors[symbol]),
            dip_relative=d2,
            dip_relative_rank_pct=rank_pct,
            close_high_20d=_safe_float(row.get("close_high_20d")),
            dip_depth_in_atr=depth if not math.isnan(depth) else None,
        )
        outcome = R.check_dip(dip_relative_rank_pct=rank_pct, depth_in_atr=depth, params=params)
        if not outcome.passed:
            results.append(RuleResult(symbol, as_of, params.version, inputs2, False, RuleStep.DIP, outcome.reason))
            continue
        counts[RuleStep.DIP.value] += 1
        universe_pass[symbol] = inputs2
        dip_survivors.append(symbol)

    veto_survivors: list[str] = []
    for symbol in dip_survivors:
        inputs = universe_pass[symbol]
        row = rows[symbol]
        frame = frames[symbol]
        bar_dates = [d.date() for d in frame["date"]]

        events = provider.corporate_events(symbol, as_of - timedelta(days=40), as_of + timedelta(days=15))
        earnings_offsets = [
            trading_days_ago_from_dates(bar_dates, as_of, e.date)
            for e in events
            if e.type == CorporateEventType.EARNINGS
        ]
        earnings_offsets = [o for o in earnings_offsets if o is not None]
        nearest_earnings = min(earnings_offsets, key=abs) if earnings_offsets else None

        event_offsets = [
            trading_days_ago_from_dates(bar_dates, as_of, e.date) for e in events if e.type in _EVENT_VETO_TYPES
        ]
        event_offsets = [o for o in event_offsets if o is not None]
        nearest_event = min(event_offsets, key=abs) if event_offsets else None

        halt_events = [e for e in events if e.type == CorporateEventType.HALT and e.date <= as_of]
        days_since_halt = None
        if halt_events:
            most_recent_halt = max(e.date for e in halt_events)
            offset = trading_days_ago_from_dates(bar_dates, as_of, most_recent_halt)
            days_since_halt = abs(offset) if offset is not None else None

        news = provider.news_flags(symbol, as_of - timedelta(days=20), as_of)
        matched_flags = tuple(
            n.flag
            for n in news
            if trading_days_ago_from_dates(bar_dates, as_of, n.date) is not None
            and abs(trading_days_ago_from_dates(bar_dates, as_of, n.date)) <= params.parameters["V6_news_veto_lookback_days"]
        )

        inputs2 = _with(
            inputs,
            turnover_ratio=_ratio(_safe_float(row.get("avg_vol_5d")), _safe_float(row.get("avg_vol_60d"))),
            max_gap_atr_ratio_5d=_safe_float(row.get("max_gap_atr_ratio_5d")),
            days_to_next_earnings=nearest_earnings,
            days_since_event=nearest_event,
            days_since_halt=days_since_halt,
            news_flags_10d=matched_flags,
        )

        veto_checks = [
            R.check_turnover_veto(
                avg_vol_5d=_safe_float(row.get("avg_vol_5d")),
                avg_vol_60d=_safe_float(row.get("avg_vol_60d")),
                params=params,
            ),
            R.check_gap_veto(max_gap_atr_ratio_5d=inputs2.max_gap_atr_ratio_5d, params=params),
            R.check_earnings_veto(trading_days_to_nearest_earnings=nearest_earnings, params=params),
            R.check_event_veto(trading_days_to_nearest_event=nearest_event, params=params),
            R.check_halt_veto(trading_days_since_halt=days_since_halt, params=params),
            R.check_news_veto(matched_flags=matched_flags),
        ]
        failed = next((o for o in veto_checks if not o.passed), None)
        universe_pass[symbol] = inputs2
        if failed is not None:
            results.append(RuleResult(symbol, as_of, params.version, inputs2, False, RuleStep.VETO, failed.reason))
            continue
        counts[RuleStep.VETO.value] += 1
        veto_survivors.append(symbol)

    portfolio_survivors: list[str] = []
    for symbol in veto_survivors:
        inputs = universe_pass[symbol]
        outcome = R.check_portfolio(
            symbol=symbol,
            sector=sectors[symbol],
            already_held_symbols=portfolio.open_positions_symbols,
            open_positions_count=portfolio.open_positions_count,
            open_positions_by_sector=portfolio.open_positions_by_sector,
            params=params,
        )
        if not outcome.passed:
            results.append(RuleResult(symbol, as_of, params.version, inputs, False, RuleStep.PORTFOLIO, outcome.reason))
            continue
        counts[RuleStep.PORTFOLIO.value] += 1
        portfolio_survivors.append(symbol)

    risk_survivors: dict[str, R.RiskMath] = {}
    for symbol in portfolio_survivors:
        inputs = universe_pass[symbol]
        row = rows[symbol]
        risk, outcome = R.compute_risk_math(
            close=float(row["close"]),
            atr_14=inputs.atr_14 or math.nan,
            account_value=portfolio.account_value,
            params=params,
        )
        if not outcome.passed:
            results.append(RuleResult(symbol, as_of, params.version, inputs, False, RuleStep.RISK, outcome.reason))
            continue
        counts[RuleStep.RISK.value] += 1
        risk_survivors[symbol] = risk

    ranked = sorted(risk_survivors.keys(), key=lambda s: universe_pass[s].dip_relative or 0.0)
    for symbol in ranked[1:]:
        results.append(
            RuleResult(symbol, as_of, params.version, universe_pass[symbol], False, RuleStep.RANK, "not_top_ranked")
        )
    if ranked:
        counts[RuleStep.RANK.value] = 1

    signal: Signal | None = None
    if ranked:
        top = ranked[0]
        inputs = universe_pass[top]
        risk = risk_survivors[top]
        last_signal_date = alert_rate.last_signal_date_by_symbol.get(top)
        cooldown_days = None
        if last_signal_date is not None:
            bar_dates = [d.date() for d in frames[top]["date"]]
            offset = trading_days_ago_from_dates(bar_dates, last_signal_date, as_of)
            cooldown_days = offset if offset is not None else (as_of - last_signal_date).days

        rate_outcome = R.check_rate_limit(
            entries_sent_today=alert_rate.entries_sent_today,
            entries_sent_this_week=alert_rate.entries_sent_this_week,
            trading_days_since_last_signal_this_symbol=cooldown_days,
            params=params,
        )
        if not rate_outcome.passed:
            results.append(RuleResult(top, as_of, params.version, inputs, False, RuleStep.RATE_LIMIT, rate_outcome.reason))
        else:
            counts[RuleStep.RATE_LIMIT.value] = 1
            results.append(RuleResult(top, as_of, params.version, inputs, True, None, None))
            expiry = _next_session(frames[top], as_of)
            signal = Signal(
                evaluation_symbol=top,
                evaluation_date=as_of,
                param_version=params.version,
                entry_low=risk.entry_low,
                entry_high=risk.entry_high,
                stop=risk.stop,
                target=risk.target,
                shares=risk.shares,
                dollar_risk=risk.dollar_risk,
                expiry_date=expiry,
                dip_relative=inputs.dip_relative or 0.0,
            )

    return EvaluateResult(
        as_of=as_of,
        param_version=params.version,
        regime_pass=True,
        results=results,
        signal=signal,
        counts_by_step_reached=counts,
    )


def _next_session(frame: pd.DataFrame, as_of: date) -> date:
    """Entry is valid for the next session only; expiry is that next bar's date if
    known from history, else a calendar-day fallback (see engine/calendar.py note)."""
    from northstar.engine.calendar import add_trading_days

    return add_trading_days(as_of, 1)


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _percentile_rank(values: dict[str, float | None]) -> dict[str, float]:
    """Ascending percentile rank across symbols: 0.0 = lowest, 1.0 = highest.
    See indicators.percentile_rank -- callers pick the comparison direction."""
    clean = {k: v for k, v in values.items() if v is not None}
    if not clean:
        return {}
    s = pd.Series(clean)
    ranked = ind.percentile_rank(s)
    return ranked.to_dict()


def _sector_average(values: dict[str, float | None], sectors: dict[str, str]) -> dict[str, float]:
    by_sector: dict[str, list[float]] = {}
    for symbol, value in values.items():
        if value is None:
            continue
        by_sector.setdefault(sectors[symbol], []).append(value)
    return {sector: sum(vals) / len(vals) for sector, vals in by_sector.items() if vals}


def _with(inputs: RuleInputs, **overrides) -> RuleInputs:
    from dataclasses import replace

    return replace(inputs, **overrides)
