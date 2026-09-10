"""Pure rule functions, one per spec section 5.3 step.

Every function takes plain scalars (not DataFrame rows) so it can be
unit-tested with hand-constructed numbers, per the Phase 1 requirement.
Cross-sectional inputs (percentile ranks, sector-average returns) are
computed once per nightly run in evaluate.py and passed in already-reduced.

None of these functions know about dates-as-strings, SQLite, or email --
they return a RuleOutcome and, where relevant, the computed numbers that
belong in the ledger.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from northstar.config import ParameterVersion
from northstar.models import RuleStep, SecurityStatus


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    passed: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RiskMath:
    entry_low: float
    entry_high: float
    entry_mid: float
    stop: float
    target: float
    shares: int
    dollar_risk: float
    position_value: float


def check_universe(
    *,
    adv_20d_dollar: float | None,
    median_spread_60d_pct: float | None,
    price_history_days: int | None,
    price: float | None,
    is_etf: bool,
    is_preferred: bool,
    status: SecurityStatus,
    params: ParameterVersion,
) -> RuleOutcome:
    p = params.parameters
    if is_etf:
        return RuleOutcome(False, "is_etf")
    if is_preferred:
        return RuleOutcome(False, "is_preferred_share")
    if status != SecurityStatus.ACTIVE:
        return RuleOutcome(False, f"status_{status.value}")
    if price_history_days is None or price_history_days < int(p["U3_min_price_history_days"]):
        return RuleOutcome(False, "U3_insufficient_price_history")
    if price is None or price < float(p["U4_min_price"]):
        return RuleOutcome(False, "U4_price_below_minimum")
    if adv_20d_dollar is None or adv_20d_dollar < float(p["U1_min_adv_20d_dollar"]):
        return RuleOutcome(False, "U1_dollar_volume_below_minimum")
    if median_spread_60d_pct is None or median_spread_60d_pct > float(p["U2_max_median_spread_60d_pct"]):
        return RuleOutcome(False, "U2_spread_above_maximum")
    return RuleOutcome(True)


def check_regime(*, index_close: float | None, index_sma_200: float | None) -> RuleOutcome:
    if index_close is None or index_sma_200 is None or math.isnan(index_sma_200):
        return RuleOutcome(False, "R1_insufficient_index_history")
    if index_close <= index_sma_200:
        return RuleOutcome(False, "R1_index_below_200sma")
    return RuleOutcome(True)


def check_momentum(
    *,
    close: float,
    sma_100: float | None,
    formation_return: float | None,
    momentum_rank_pct: float | None,
    params: ParameterVersion,
) -> RuleOutcome:
    p = params.parameters
    if formation_return is None or momentum_rank_pct is None:
        return RuleOutcome(False, "M1_insufficient_formation_history")
    if momentum_rank_pct < float(p["M2_momentum_rank_threshold_pct"]):
        return RuleOutcome(False, "M2_not_top_momentum_tercile")
    if sma_100 is None or math.isnan(sma_100) or close <= sma_100:
        return RuleOutcome(False, "M3_below_100sma")
    return RuleOutcome(True)


def dip_depth_in_atr(*, close: float, close_high_20d: float, atr_14: float) -> float:
    if atr_14 == 0 or math.isnan(atr_14):
        return math.nan
    return (close_high_20d - close) / atr_14


def check_dip(
    *,
    dip_relative_rank_pct: float | None,
    depth_in_atr: float,
    params: ParameterVersion,
) -> RuleOutcome:
    p = params.parameters
    if dip_relative_rank_pct is None or math.isnan(depth_in_atr):
        return RuleOutcome(False, "D_insufficient_data")
    if dip_relative_rank_pct > float(p["D3_dip_rank_threshold_pct"]):
        return RuleOutcome(False, "D3_not_bottom_dip_tercile")
    if depth_in_atr < float(p["D4_dip_depth_floor_atr_mult"]):
        return RuleOutcome(False, "D4_dip_too_shallow")
    if depth_in_atr > float(p["D5_dip_depth_ceiling_atr_mult"]):
        return RuleOutcome(False, "D5_dip_too_deep")
    return RuleOutcome(True)


def check_turnover_veto(*, avg_vol_5d: float | None, avg_vol_60d: float | None, params: ParameterVersion) -> RuleOutcome:
    p = params.parameters
    if avg_vol_5d is None or avg_vol_60d is None or avg_vol_60d == 0:
        return RuleOutcome(False, "V1_insufficient_volume_history")
    if avg_vol_5d > float(p["V1_turnover_veto_mult"]) * avg_vol_60d:
        return RuleOutcome(False, "V1_turnover_veto")
    return RuleOutcome(True)


def check_gap_veto(*, max_gap_atr_ratio_5d: float | None, params: ParameterVersion) -> RuleOutcome:
    p = params.parameters
    if max_gap_atr_ratio_5d is None or math.isnan(max_gap_atr_ratio_5d):
        return RuleOutcome(False, "V2_insufficient_data")
    if max_gap_atr_ratio_5d > float(p["V2_gap_veto_atr_mult"]):
        return RuleOutcome(False, "V2_gap_veto")
    return RuleOutcome(True)


def check_earnings_veto(*, trading_days_to_nearest_earnings: int | None, params: ParameterVersion) -> RuleOutcome:
    p = params.parameters
    if trading_days_to_nearest_earnings is None:
        return RuleOutcome(True)
    if abs(trading_days_to_nearest_earnings) <= int(p["V3_earnings_veto_window_days"]):
        return RuleOutcome(False, "V3_earnings_veto")
    return RuleOutcome(True)


def check_event_veto(*, trading_days_to_nearest_event: int | None, params: ParameterVersion) -> RuleOutcome:
    p = params.parameters
    if trading_days_to_nearest_event is None:
        return RuleOutcome(True)
    if abs(trading_days_to_nearest_event) <= int(p["V4_event_veto_window_days"]):
        return RuleOutcome(False, "V4_distribution_event_veto")
    return RuleOutcome(True)


def check_halt_veto(*, trading_days_since_halt: int | None, params: ParameterVersion) -> RuleOutcome:
    p = params.parameters
    if trading_days_since_halt is None:
        return RuleOutcome(True)
    if trading_days_since_halt <= int(p["V5_halt_veto_lookback_days"]):
        return RuleOutcome(False, "V5_halt_veto")
    return RuleOutcome(True)


def check_news_veto(*, matched_flags: tuple[str, ...]) -> RuleOutcome:
    if matched_flags:
        return RuleOutcome(False, f"V6_news_veto:{','.join(matched_flags)}")
    return RuleOutcome(True)


def check_portfolio(
    *,
    symbol: str,
    sector: str,
    already_held_symbols: frozenset[str],
    open_positions_count: int,
    open_positions_by_sector: dict[str, int],
    params: ParameterVersion,
) -> RuleOutcome:
    p = params.parameters
    if symbol in already_held_symbols:
        return RuleOutcome(False, "already_held")
    if open_positions_count >= int(p["S2_max_open_positions"]):
        return RuleOutcome(False, "S2_max_open_positions")
    if open_positions_by_sector.get(sector, 0) >= int(p["S3_max_positions_per_sector"]):
        return RuleOutcome(False, "S3_max_positions_per_sector")
    return RuleOutcome(True)


def compute_risk_math(
    *,
    close: float,
    atr_14: float,
    account_value: float,
    params: ParameterVersion,
) -> tuple[RiskMath, RuleOutcome]:
    p = params.parameters
    entry_low = close - float(p["E1_entry_zone_atr_mult"]) * atr_14
    entry_high = close + float(p["E1_entry_zone_atr_mult"]) * atr_14
    entry_mid = (entry_low + entry_high) / 2.0
    stop = entry_mid - float(p["E2_stop_atr_mult"]) * atr_14
    target = entry_mid + float(p["E3_target_atr_mult"]) * atr_14
    risk_per_share = entry_mid - stop
    if risk_per_share <= 0:
        risk = RiskMath(entry_low, entry_high, entry_mid, stop, target, 0, 0.0, 0.0)
        return risk, RuleOutcome(False, "non_positive_risk_per_share")

    shares = math.floor((account_value * float(p["S1_risk_per_trade_pct"])) / risk_per_share)
    dollar_risk = shares * risk_per_share
    position_value = shares * entry_mid
    risk = RiskMath(entry_low, entry_high, entry_mid, stop, target, shares, dollar_risk, position_value)

    if shares <= 0:
        return risk, RuleOutcome(False, "zero_shares_at_this_risk_budget")
    if position_value > float(p["MAX_POSITION_PCT_OF_ACCOUNT"]) * account_value:
        return risk, RuleOutcome(False, "position_too_large_relative_to_stop")
    return risk, RuleOutcome(True)


def check_rate_limit(
    *,
    entries_sent_today: int,
    entries_sent_this_week: int,
    trading_days_since_last_signal_this_symbol: int | None,
    params: ParameterVersion,
) -> RuleOutcome:
    p = params.parameters
    if entries_sent_today >= int(p["A1_max_entry_emails_per_day"]):
        return RuleOutcome(False, "A1_daily_cap_reached")
    if entries_sent_this_week >= int(p["A1_max_entry_emails_per_week"]):
        return RuleOutcome(False, "A1_weekly_cap_reached")
    min_gap = int(p["A1_min_days_between_same_symbol_signal"])
    if (
        trading_days_since_last_signal_this_symbol is not None
        and trading_days_since_last_signal_this_symbol < min_gap
    ):
        return RuleOutcome(False, "A1_symbol_cooldown")
    return RuleOutcome(True)


ORDERED_STEPS: tuple[RuleStep, ...] = (
    RuleStep.UNIVERSE,
    RuleStep.REGIME,
    RuleStep.MOMENTUM,
    RuleStep.DIP,
    RuleStep.VETO,
    RuleStep.PORTFOLIO,
    RuleStep.RISK,
    RuleStep.RANK,
    RuleStep.RATE_LIMIT,
)
