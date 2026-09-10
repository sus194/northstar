from __future__ import annotations

import pytest

from northstar.backtest.costs import (
    apply_entry_costs,
    apply_exit_costs,
    entry_fill,
    exit_fill,
    slippage_bps,
    spread_cost_per_side,
)


def test_entry_fill_inside_zone():
    result = entry_fill(next_open=100.0, entry_low=99.0, entry_high=101.0)
    assert result.filled
    assert result.fill_price == 100.0


def test_entry_fill_outside_zone_is_expired_unfilled():
    result = entry_fill(next_open=105.0, entry_low=99.0, entry_high=101.0)
    assert not result.filled
    assert result.reason == "expired_unfilled"


def test_slippage_bps_by_liquidity_threshold():
    assert slippage_bps(5_000_000) == 5.0
    assert slippage_bps(15_000_000) == 2.0


def test_spread_cost_is_half_of_median_spread():
    cost = spread_cost_per_side(price=100.0, median_spread_pct_60d=0.50)
    assert cost == pytest.approx(0.25)  # half of 0.50% of 100 = 0.25


def test_apply_entry_costs_increases_price():
    cost_price = apply_entry_costs(fill_price=100.0, median_spread_pct_60d=0.50, dollar_volume_20d=5_000_000)
    assert cost_price > 100.0


def test_apply_exit_costs_decreases_price():
    cost_price = apply_exit_costs(fill_price=100.0, median_spread_pct_60d=0.50, dollar_volume_20d=5_000_000)
    assert cost_price < 100.0


def test_exit_fill_takes_worse_of_trigger_and_open():
    assert exit_fill(trigger_price=96.0, session_open=94.0) == 94.0  # gapped through, worse
    assert exit_fill(trigger_price=96.0, session_open=97.0) == 96.0  # no gap-through, trigger stands
