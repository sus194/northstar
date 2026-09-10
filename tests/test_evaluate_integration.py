"""End-to-end test of engine/evaluate.py against a hand-constructed
4-symbol, 2-sector universe, exercising the full rule order from spec
section 5.3 without any real vendor.

Fixture design (values tuned and verified against the actual indicator
code -- see git history / session notes for the derivation):
  - AAA (Financials): steep 300-day uptrend, then a small 5-day dip.
    Highest 12-2mo momentum of the four (passes M2) and the only one with
    a deep sector-relative dip (passes D3); the fixture is arranged so it
    is the sole survivor and becomes the signal.
  - BBB (Financials): AAA's sector partner, flat -- pulls the sector
    average down when AAA dips, which is what makes AAA's D2 register as
    a *sector-relative* dip rather than a market-wide one.
  - CCC, DDD (Energy): moderate uptrends, flat in the dip window. DDD's
    momentum is strong enough to clear M2 but it has no dip, so it's
    rejected at the DIP step -- this exercises a candidate that survives
    the momentum step but nothing further.
  - CCC never clears M2, rejected at the MOMENTUM step.
"""

from __future__ import annotations

from datetime import date

from northstar.engine.evaluate import AlertRateState, PortfolioState, evaluate_date
from northstar.models import RuleStep

from .synthetic import InMemoryProvider, make_bars, make_index_bars, make_security

END = date(2024, 6, 28)
N = 300


def _build_provider(index_daily_return: float = 0.0004) -> InMemoryProvider:
    aaa = make_bars(
        N, start_price=20.0, daily_return=0.022, end_date=END,
        tail_returns=[-0.01, -0.008, -0.006, -0.004, -0.003], range_pct=0.003,
    )
    bbb = make_bars(N, start_price=20.0, daily_return=0.0005, end_date=END, tail_returns=[0.0] * 5, range_pct=0.003)
    ccc = make_bars(N, start_price=20.0, daily_return=0.001, end_date=END, tail_returns=[0.0] * 5, range_pct=0.003)
    ddd = make_bars(N, start_price=20.0, daily_return=0.0015, end_date=END, tail_returns=[0.0] * 5, range_pct=0.003)

    securities = [
        make_security("AAA", "Financials"),
        make_security("BBB", "Financials"),
        make_security("CCC", "Energy"),
        make_security("DDD", "Energy"),
    ]
    index_df = make_index_bars(N + 5, end_date=END, daily_return=index_daily_return)

    return InMemoryProvider(
        securities=securities,
        bars={"AAA": aaa, "BBB": bbb, "CCC": ccc, "DDD": ddd},
        index_df=index_df,
    )


def _empty_portfolio() -> PortfolioState:
    return PortfolioState(
        account_value=1_000_000.0,
        open_positions_symbols=frozenset(),
        open_positions_count=0,
        open_positions_by_sector={},
    )


def _empty_alert_rate() -> AlertRateState:
    return AlertRateState(entries_sent_today=0, entries_sent_this_week=0, last_signal_date_by_symbol={})


def test_full_pipeline_selects_the_momentum_dip_survivor(params):
    provider = _build_provider()
    result = evaluate_date(
        as_of=END, provider=provider, params=params, portfolio=_empty_portfolio(), alert_rate=_empty_alert_rate()
    )

    assert result.regime_pass
    assert result.signal is not None
    assert result.signal.evaluation_symbol == "AAA"
    assert result.signal.stop < result.signal.entry_low < result.signal.entry_high < result.signal.target
    assert result.signal.shares > 0

    # BBB and CCC never clear the momentum bar.
    bbb_rejections = [r for r in result.results if r.symbol == "BBB"]
    ccc_rejections = [r for r in result.results if r.symbol == "CCC"]
    assert any(r.reject_step == RuleStep.MOMENTUM for r in bbb_rejections)
    assert any(r.reject_step == RuleStep.MOMENTUM for r in ccc_rejections)
    # DDD clears momentum but has no sector-relative dip.
    ddd_rejections = [r for r in result.results if r.symbol == "DDD"]
    assert any(r.reject_step == RuleStep.DIP for r in ddd_rejections)
    # AAA has exactly one passing result.
    aaa_passes = [r for r in result.results if r.symbol == "AAA" and r.passed]
    assert len(aaa_passes) == 1


def test_regime_gate_blocks_all_candidates_when_index_below_200sma(params):
    provider = _build_provider(index_daily_return=-0.002)  # steadily declining index
    result = evaluate_date(
        as_of=END, provider=provider, params=params, portfolio=_empty_portfolio(), alert_rate=_empty_alert_rate()
    )

    assert not result.regime_pass
    assert result.signal is None
    assert all(r.reject_step == RuleStep.REGIME for r in result.results)
    assert len(result.results) == 4


def test_rate_limit_blocks_signal_when_daily_cap_already_reached(params):
    provider = _build_provider()
    alert_rate = AlertRateState(entries_sent_today=1, entries_sent_this_week=1, last_signal_date_by_symbol={})
    result = evaluate_date(
        as_of=END, provider=provider, params=params, portfolio=_empty_portfolio(), alert_rate=alert_rate
    )
    assert result.signal is None
    aaa_result = next(r for r in result.results if r.symbol == "AAA")
    assert aaa_result.reject_step == RuleStep.RATE_LIMIT
    assert aaa_result.reject_reason == "A1_daily_cap_reached"


def test_portfolio_cap_blocks_signal_when_already_held(params):
    provider = _build_provider()
    portfolio = PortfolioState(
        account_value=1_000_000.0,
        open_positions_symbols=frozenset({"AAA"}),
        open_positions_count=1,
        open_positions_by_sector={"Financials": 1},
    )
    result = evaluate_date(
        as_of=END, provider=provider, params=params, portfolio=portfolio, alert_rate=_empty_alert_rate()
    )
    assert result.signal is None
    aaa_result = next(r for r in result.results if r.symbol == "AAA")
    assert aaa_result.reject_step == RuleStep.PORTFOLIO
    assert aaa_result.reject_reason == "already_held"
