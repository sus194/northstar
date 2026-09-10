"""Unit tests for engine/rules.py, one (or a few) per named parameter in
spec section 5.2, using hand-constructed numbers rather than real bars."""

from __future__ import annotations

from northstar import models
from northstar.engine import rules as R

# ---------- U1-U4: universe ----------


def test_universe_passes_when_all_thresholds_clear(params):
    outcome = R.check_universe(
        adv_20d_dollar=3_000_000,
        median_spread_60d_pct=0.30,
        price_history_days=300,
        price=10.0,
        is_etf=False,
        is_preferred=False,
        status=models.SecurityStatus.ACTIVE,
        params=params,
    )
    assert outcome.passed


def test_universe_fails_below_min_dollar_volume(params):
    outcome = R.check_universe(
        adv_20d_dollar=1_000_000,  # below U1 = 2,000,000
        median_spread_60d_pct=0.30,
        price_history_days=300,
        price=10.0,
        is_etf=False,
        is_preferred=False,
        status=models.SecurityStatus.ACTIVE,
        params=params,
    )
    assert not outcome.passed
    assert outcome.reason == "U1_dollar_volume_below_minimum"


def test_universe_fails_above_max_spread(params):
    outcome = R.check_universe(
        adv_20d_dollar=3_000_000,
        median_spread_60d_pct=0.75,  # above U2 = 0.50
        price_history_days=300,
        price=10.0,
        is_etf=False,
        is_preferred=False,
        status=models.SecurityStatus.ACTIVE,
        params=params,
    )
    assert not outcome.passed
    assert outcome.reason == "U2_spread_above_maximum"


def test_universe_fails_insufficient_history(params):
    outcome = R.check_universe(
        adv_20d_dollar=3_000_000,
        median_spread_60d_pct=0.30,
        price_history_days=100,  # below U3 = 260
        price=10.0,
        is_etf=False,
        is_preferred=False,
        status=models.SecurityStatus.ACTIVE,
        params=params,
    )
    assert not outcome.passed
    assert outcome.reason == "U3_insufficient_price_history"


def test_universe_fails_below_min_price(params):
    outcome = R.check_universe(
        adv_20d_dollar=3_000_000,
        median_spread_60d_pct=0.30,
        price_history_days=300,
        price=3.0,  # below U4 = 5.00
        is_etf=False,
        is_preferred=False,
        status=models.SecurityStatus.ACTIVE,
        params=params,
    )
    assert not outcome.passed
    assert outcome.reason == "U4_price_below_minimum"


def test_universe_excludes_etf_and_preferred_and_delisted(params):
    base = {
        "adv_20d_dollar": 3_000_000,
        "median_spread_60d_pct": 0.30,
        "price_history_days": 300,
        "price": 10.0,
        "params": params,
    }
    assert not R.check_universe(**base, is_etf=True, is_preferred=False, status=models.SecurityStatus.ACTIVE).passed
    assert not R.check_universe(**base, is_etf=False, is_preferred=True, status=models.SecurityStatus.ACTIVE).passed
    assert not R.check_universe(**base, is_etf=False, is_preferred=False, status=models.SecurityStatus.DELISTED).passed


# ---------- R1: regime gate ----------


def test_regime_passes_above_200sma():
    assert R.check_regime(index_close=21000, index_sma_200=20000).passed


def test_regime_fails_at_or_below_200sma():
    assert not R.check_regime(index_close=20000, index_sma_200=20000).passed
    assert not R.check_regime(index_close=19000, index_sma_200=20000).passed


def test_regime_fails_without_sufficient_history():
    assert not R.check_regime(index_close=21000, index_sma_200=None).passed


# ---------- M1-M3: momentum ----------


def test_momentum_passes_top_tercile_and_above_100sma(params):
    outcome = R.check_momentum(close=50, sma_100=45, formation_return=0.30, momentum_rank_pct=0.85, params=params)
    assert outcome.passed


def test_momentum_fails_below_rank_threshold(params):
    outcome = R.check_momentum(close=50, sma_100=45, formation_return=0.05, momentum_rank_pct=0.50, params=params)
    assert not outcome.passed
    assert outcome.reason == "M2_not_top_momentum_tercile"


def test_momentum_fails_below_100sma_even_if_top_rank(params):
    outcome = R.check_momentum(close=40, sma_100=45, formation_return=0.30, momentum_rank_pct=0.90, params=params)
    assert not outcome.passed
    assert outcome.reason == "M3_below_100sma"


# ---------- D1-D5: dip ----------


def test_dip_depth_calculation():
    depth = R.dip_depth_in_atr(close=95, close_high_20d=100, atr_14=2.0)
    assert depth == 2.5


def test_dip_passes_within_floor_and_ceiling_and_bottom_tercile(params):
    outcome = R.check_dip(dip_relative_rank_pct=0.10, depth_in_atr=1.5, params=params)
    assert outcome.passed


def test_dip_fails_not_bottom_tercile(params):
    outcome = R.check_dip(dip_relative_rank_pct=0.50, depth_in_atr=1.5, params=params)
    assert not outcome.passed
    assert outcome.reason == "D3_not_bottom_dip_tercile"


def test_dip_fails_too_shallow(params):
    outcome = R.check_dip(dip_relative_rank_pct=0.10, depth_in_atr=0.2, params=params)  # below D4=0.5
    assert not outcome.passed
    assert outcome.reason == "D4_dip_too_shallow"


def test_dip_fails_too_deep(params):
    outcome = R.check_dip(dip_relative_rank_pct=0.10, depth_in_atr=3.0, params=params)  # above D5=2.5
    assert not outcome.passed
    assert outcome.reason == "D5_dip_too_deep"


# ---------- V1-V6: vetoes ----------


def test_turnover_veto_triggers_above_2x(params):
    outcome = R.check_turnover_veto(avg_vol_5d=250_000, avg_vol_60d=100_000, params=params)
    assert not outcome.passed
    assert outcome.reason == "V1_turnover_veto"


def test_turnover_veto_clears_at_or_below_2x(params):
    outcome = R.check_turnover_veto(avg_vol_5d=200_000, avg_vol_60d=100_000, params=params)
    assert outcome.passed


def test_gap_veto_triggers_above_1_5x_atr(params):
    outcome = R.check_gap_veto(max_gap_atr_ratio_5d=2.0, params=params)
    assert not outcome.passed
    assert outcome.reason == "V2_gap_veto"


def test_gap_veto_clears_below_threshold(params):
    outcome = R.check_gap_veto(max_gap_atr_ratio_5d=1.0, params=params)
    assert outcome.passed


def test_earnings_veto_triggers_within_5_trading_days(params):
    assert not R.check_earnings_veto(trading_days_to_nearest_earnings=3, params=params).passed
    assert not R.check_earnings_veto(trading_days_to_nearest_earnings=-5, params=params).passed


def test_earnings_veto_clears_outside_window(params):
    assert R.check_earnings_veto(trading_days_to_nearest_earnings=6, params=params).passed
    assert R.check_earnings_veto(trading_days_to_nearest_earnings=None, params=params).passed


def test_event_veto_triggers_within_3_trading_days(params):
    assert not R.check_event_veto(trading_days_to_nearest_event=2, params=params).passed


def test_event_veto_clears_outside_window(params):
    assert R.check_event_veto(trading_days_to_nearest_event=4, params=params).passed


def test_halt_veto_triggers_within_20_trading_days(params):
    assert not R.check_halt_veto(trading_days_since_halt=10, params=params).passed


def test_halt_veto_clears_outside_window(params):
    assert R.check_halt_veto(trading_days_since_halt=25, params=params).passed


def test_news_veto_triggers_on_any_matched_flag():
    assert not R.check_news_veto(matched_flags=("acquisition",)).passed


def test_news_veto_clears_with_no_flags():
    assert R.check_news_veto(matched_flags=()).passed


# ---------- S2-S3: portfolio ----------


def test_portfolio_blocks_already_held(params):
    outcome = R.check_portfolio(
        symbol="ABC",
        sector="Financials",
        already_held_symbols=frozenset({"ABC"}),
        open_positions_count=1,
        open_positions_by_sector={"Financials": 1},
        params=params,
    )
    assert not outcome.passed
    assert outcome.reason == "already_held"


def test_portfolio_blocks_at_max_open_positions(params):
    outcome = R.check_portfolio(
        symbol="XYZ",
        sector="Energy",
        already_held_symbols=frozenset(),
        open_positions_count=4,  # S2 = 4
        open_positions_by_sector={},
        params=params,
    )
    assert not outcome.passed
    assert outcome.reason == "S2_max_open_positions"


def test_portfolio_blocks_at_max_per_sector(params):
    outcome = R.check_portfolio(
        symbol="XYZ",
        sector="Energy",
        already_held_symbols=frozenset(),
        open_positions_count=2,
        open_positions_by_sector={"Energy": 2},  # S3 = 2
        params=params,
    )
    assert not outcome.passed
    assert outcome.reason == "S3_max_positions_per_sector"


def test_portfolio_passes_under_all_caps(params):
    outcome = R.check_portfolio(
        symbol="XYZ",
        sector="Energy",
        already_held_symbols=frozenset(),
        open_positions_count=1,
        open_positions_by_sector={"Energy": 1},
        params=params,
    )
    assert outcome.passed


# ---------- E1-E4 / risk math ----------


def test_risk_math_computes_expected_zone_stop_target(params):
    risk, outcome = R.compute_risk_math(close=100.0, atr_14=2.0, account_value=100_000.0, params=params)
    assert risk.entry_low == 99.0
    assert risk.entry_high == 101.0
    assert risk.entry_mid == 100.0
    assert risk.stop == 96.0  # 100 - 2*2.0
    assert risk.target == 108.0  # 100 + 4*2.0
    # shares = floor(100_000 * 0.0075 / (100 - 96)) = floor(750 / 4) = 187
    assert risk.shares == 187
    assert outcome.passed


def test_risk_math_rejects_when_position_too_large(params):
    # Tiny ATR means tiny risk-per-share, so the risk budget buys a huge
    # position relative to the account -> should reject on the 25% cap.
    _risk, outcome = R.compute_risk_math(close=100.0, atr_14=0.05, account_value=10_000.0, params=params)
    assert not outcome.passed
    assert outcome.reason == "position_too_large_relative_to_stop"


# ---------- A1: rate limit ----------


def test_rate_limit_blocks_at_daily_cap(params):
    outcome = R.check_rate_limit(
        entries_sent_today=1, entries_sent_this_week=1, trading_days_since_last_signal_this_symbol=None, params=params
    )
    assert not outcome.passed
    assert outcome.reason == "A1_daily_cap_reached"


def test_rate_limit_blocks_at_weekly_cap(params):
    outcome = R.check_rate_limit(
        entries_sent_today=0, entries_sent_this_week=3, trading_days_since_last_signal_this_symbol=None, params=params
    )
    assert not outcome.passed
    assert outcome.reason == "A1_weekly_cap_reached"


def test_rate_limit_blocks_symbol_cooldown(params):
    outcome = R.check_rate_limit(
        entries_sent_today=0, entries_sent_this_week=0, trading_days_since_last_signal_this_symbol=5, params=params
    )
    assert not outcome.passed
    assert outcome.reason == "A1_symbol_cooldown"


def test_rate_limit_passes_when_clear(params):
    outcome = R.check_rate_limit(
        entries_sent_today=0, entries_sent_this_week=0, trading_days_since_last_signal_this_symbol=20, params=params
    )
    assert outcome.passed
