from __future__ import annotations

from datetime import date

from northstar.engine.exits import ExitContext, evaluate_exit
from northstar.models import Position


def _position():
    return Position(
        symbol="ABC",
        shares=100,
        fill_price=100.0,
        fill_date=date(2024, 1, 2),
        stop=96.0,
        target=108.0,
        time_limit_date=date(2024, 1, 20),
    )


def test_stop_condition_triggers(params):
    ctx = ExitContext(
        close=95.0,
        as_of_date=date(2024, 1, 5),
        trading_days_since_fill=3,
        regime_failed_two_consecutive=False,
        trading_days_to_nearest_earnings=None,
    )
    reviews = evaluate_exit(_position(), ctx, params)
    assert any(r.condition == "stop" for r in reviews)


def test_target_condition_triggers(params):
    ctx = ExitContext(
        close=110.0,
        as_of_date=date(2024, 1, 5),
        trading_days_since_fill=3,
        regime_failed_two_consecutive=False,
        trading_days_to_nearest_earnings=None,
    )
    reviews = evaluate_exit(_position(), ctx, params)
    assert any(r.condition == "target" for r in reviews)


def test_time_condition_triggers_at_e4(params):
    ctx = ExitContext(
        close=100.0,
        as_of_date=date(2024, 1, 20),
        trading_days_since_fill=10,  # E4 = 10
        regime_failed_two_consecutive=False,
        trading_days_to_nearest_earnings=None,
    )
    reviews = evaluate_exit(_position(), ctx, params)
    assert any(r.condition == "time" for r in reviews)


def test_regime_condition_triggers_on_two_consecutive_fails(params):
    ctx = ExitContext(
        close=100.0,
        as_of_date=date(2024, 1, 5),
        trading_days_since_fill=3,
        regime_failed_two_consecutive=True,
        trading_days_to_nearest_earnings=None,
    )
    reviews = evaluate_exit(_position(), ctx, params)
    assert any(r.condition == "regime" for r in reviews)


def test_event_condition_triggers_within_2_trading_days(params):
    ctx = ExitContext(
        close=100.0,
        as_of_date=date(2024, 1, 5),
        trading_days_since_fill=3,
        regime_failed_two_consecutive=False,
        trading_days_to_nearest_earnings=1,
    )
    reviews = evaluate_exit(_position(), ctx, params)
    assert any(r.condition == "event" for r in reviews)


def test_no_conditions_trigger_when_clean(params):
    ctx = ExitContext(
        close=101.0,
        as_of_date=date(2024, 1, 5),
        trading_days_since_fill=3,
        regime_failed_two_consecutive=False,
        trading_days_to_nearest_earnings=10,
    )
    reviews = evaluate_exit(_position(), ctx, params)
    assert reviews == []
