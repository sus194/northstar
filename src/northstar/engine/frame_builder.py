"""Builds a per-symbol indicator frame from raw daily bars.

One function, one responsibility: turn OHLCV bars into every column the
rule functions in engine/rules.py need to read for a given as-of date.
Kept separate from rules.py so rules.py stays pure boolean logic over a
single row plus a cross-section, easy to unit test with hand-built rows.
"""

from __future__ import annotations

import pandas as pd

from northstar.config import ParameterVersion
from northstar.engine import indicators as ind


def build_indicator_frame(bars: pd.DataFrame, params: ParameterVersion) -> pd.DataFrame:
    """bars: ascending-date OHLCV for one symbol. Returns bars + indicator columns."""
    p = params.parameters
    df = bars.sort_values("date").reset_index(drop=True).copy()
    if df.empty:
        return df

    atr_window = int(p["ATR_window_days"])
    df["atr_14"] = ind.atr(df, window=atr_window)
    df["sma_100"] = ind.sma(df["close"], int(p["M3_trend_sma_days"]))
    df["adv_20d_dollar"] = ind.rolling_avg_dollar_volume(df, 20)
    df["avg_vol_5d"] = ind.rolling_avg_volume(df, 5)
    df["avg_vol_60d"] = ind.rolling_avg_volume(df, 60)
    df["median_spread_60d_pct"] = ind.median_spread_pct(df, window=60)
    df["formation_return"] = ind.formation_return(
        df["close"],
        int(p["M1_formation_start_months"]),
        int(p["M1_formation_end_months"]),
    )
    df["stock_5d_return"] = ind.n_day_return(df["close"], int(p["D1_dip_window_days"]))
    df["close_high_20d"] = ind.rolling_max(df["close"], 20)
    df["max_gap_atr_ratio_5d"] = ind.max_abs_gap_ratio(df, df["atr_14"], int(p["V2_gap_lookback_days"]))
    df["price_history_days"] = df.index + 1
    return df
