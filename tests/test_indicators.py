from __future__ import annotations

import pandas as pd
import pytest

from northstar.engine import indicators as ind


def _bars(closes, highs=None, lows=None, opens=None, volumes=None):
    n = len(closes)
    return pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=n, freq="B"),
            "open": opens or closes,
            "high": highs or [c + 1 for c in closes],
            "low": lows or [c - 1 for c in closes],
            "close": closes,
            "volume": volumes or [1000] * n,
        }
    )


def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5])
    result = ind.sma(s, window=3)
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[3] == pytest.approx(3.0)
    assert pd.isna(result.iloc[1])


def test_true_range_and_atr_hand_computed():
    # 3 bars: TR should be max(high-low, |high-prevclose|, |low-prevclose|)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=3, freq="B"),
            "open": [10, 10, 10],
            "high": [12, 13, 11],
            "low": [9, 11, 8],
            "close": [10, 12, 9],
            "volume": [100, 100, 100],
        }
    )
    tr = ind.true_range(df)
    assert tr.iloc[0] == pytest.approx(3.0)  # high-low, no prior close
    # bar 2: high-low=2, |high-prevclose|=|13-10|=3, |low-prevclose|=|11-10|=1 -> max=3
    assert tr.iloc[1] == pytest.approx(3.0)
    # bar 3: high-low=3, |high-prevclose|=|11-12|=1, |low-prevclose|=|8-12|=4 -> max=4
    assert tr.iloc[2] == pytest.approx(4.0)

    atr = ind.atr(df, window=3)
    assert atr.iloc[2] == pytest.approx((3.0 + 3.0 + 4.0) / 3)


def test_dollar_volume_and_rolling_avg():
    df = _bars(closes=[10, 20, 30], volumes=[100, 200, 300])
    dv = ind.dollar_volume(df)
    assert list(dv) == [1000, 4000, 9000]
    avg = ind.rolling_avg_dollar_volume(df, window=2)
    assert avg.iloc[1] == pytest.approx((1000 + 4000) / 2)
    assert avg.iloc[2] == pytest.approx((4000 + 9000) / 2)


def test_n_day_return():
    s = pd.Series([100, 105, 110, 121])
    r = ind.n_day_return(s, n=2)
    assert r.iloc[2] == pytest.approx(0.10)  # 110/100 - 1
    assert r.iloc[3] == pytest.approx(121 / 105 - 1)  # close two rows back is 105


def test_formation_return_offsets():
    # 40 days of data; return should compare close at t-2*21 to t-12*21... use small
    # trading_days_per_month to keep the fixture short.
    closes = list(range(100, 140))  # 40 values, index 0..39
    s = pd.Series(closes)
    r = ind.formation_return(s, start_months_ago=-2, end_months_ago=-1, trading_days_per_month=5)
    # start_offset = 10, end_offset = 5 -> r[t] = close[t-5]/close[t-10] - 1
    t = 20
    expected = closes[t - 5] / closes[t - 10] - 1.0
    assert r.iloc[t] == pytest.approx(expected)


def test_percentile_rank_ascending_direction():
    s = pd.Series({"a": 1.0, "b": 5.0, "c": 3.0})
    ranks = ind.percentile_rank(s)
    assert ranks["a"] < ranks["c"] < ranks["b"]
    assert ranks["b"] == pytest.approx(1.0)
    assert ranks["a"] == pytest.approx(1 / 3)


def test_max_abs_gap_ratio():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=3, freq="B"),
            "open": [10, 15, 10],
            "high": [11, 16, 11],
            "low": [9, 14, 9],
            "close": [10, 10, 10],
            "volume": [100, 100, 100],
        }
    )
    atr_series = pd.Series([2.0, 2.0, 2.0])
    ratio = ind.max_abs_gap_ratio(df, atr_series, lookback=3)
    # bar 1 gap = |15 - 10| = 5, ratio = 2.5
    assert ratio.iloc[1] == pytest.approx(2.5)
