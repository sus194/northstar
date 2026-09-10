"""Pure indicator functions over pandas Series/DataFrames of daily bars.

Every function here is deterministic and side-effect free so it can be
called identically from the nightly scan and from the backtest replay
(spec section 8: "backtest and live scan share the same engine code path").

Input DataFrames are expected to be sorted ascending by date and indexed
0..n-1 (not by date), with at least columns: open, high, low, close, volume.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def true_range(bars: pd.DataFrame) -> pd.Series:
    prior_close = bars["close"].shift(1)
    hl = bars["high"] - bars["low"]
    hc = (bars["high"] - prior_close).abs()
    lc = (bars["low"] - prior_close).abs()
    return pd.concat([hl, hc, lc], axis=1).max(axis=1)


def atr(bars: pd.DataFrame, window: int = 14) -> pd.Series:
    """Wilder-style ATR via simple rolling mean of true range (spec ATR_window_days)."""
    tr = true_range(bars)
    return tr.rolling(window=window, min_periods=window).mean()


def dollar_volume(bars: pd.DataFrame) -> pd.Series:
    return bars["close"] * bars["volume"]


def rolling_avg_dollar_volume(bars: pd.DataFrame, window: int) -> pd.Series:
    return dollar_volume(bars).rolling(window=window, min_periods=window).mean()


def rolling_avg_volume(bars: pd.DataFrame, window: int) -> pd.Series:
    return bars["volume"].rolling(window=window, min_periods=window).mean()


def corwin_schultz_spread(bars: pd.DataFrame) -> pd.Series:
    """Corwin & Schultz (2012) high-low bid-ask spread estimator.

    v1 has no NBBO feed. Naively using (high-low)/close as a spread proxy
    conflates spread with intraday volatility -- a volatile momentum name
    with a 2-3% daily range would then show a "spread" many times U2's
    0.50% cap, which has nothing to do with actual trading cost. Corwin-
    Schultz isolates the spread component from two-day high-low ranges
    (the same estimator family the trading-cost literature in section 13
    -- Novy-Marx & Velikov -- draws on), so it stays low for a smoothly
    volatile trending stock and only rises when quoted spreads actually
    widen. Estimate is clipped at 0 (the closed form can go slightly
    negative for very liquid names).
    """
    log_hl = np.log(bars["high"] / bars["low"])
    beta = (log_hl**2) + (log_hl.shift(1) ** 2)
    two_day_high = bars["high"].rolling(2).max()
    two_day_low = bars["low"].rolling(2).min()
    gamma = np.log(two_day_high / two_day_low) ** 2

    denom = 3 - 2 * np.sqrt(2)
    alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / denom - np.sqrt(gamma / denom)
    spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    return spread.clip(lower=0.0)


def median_spread_pct(bars: pd.DataFrame, window: int = 60) -> pd.Series:
    """Rolling median of the Corwin-Schultz spread estimate, as a percent of price."""
    spread = corwin_schultz_spread(bars)
    return spread.rolling(window=window, min_periods=window).median() * 100.0


def n_day_return(close: pd.Series, n: int) -> pd.Series:
    return close / close.shift(n) - 1.0


def formation_return(
    close: pd.Series, start_months_ago: int, end_months_ago: int, trading_days_per_month: int = 21
) -> pd.Series:
    """Return over an offset window measured in trading days, e.g. months -12 to -2 (M1).

    start_months_ago and end_months_ago are negative ints, e.g. -12 and -2.
    The window return is close[t - |end|*21] / close[t - |start|*21] - 1.
    """
    start_offset = abs(start_months_ago) * trading_days_per_month
    end_offset = abs(end_months_ago) * trading_days_per_month
    return close.shift(end_offset) / close.shift(start_offset) - 1.0


def rolling_max(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).max()


def percentile_rank(values: pd.Series) -> pd.Series:
    """Ascending percentile rank within a cross-section: 0.0 = lowest value, 1.0 = highest.

    Both momentum and dip thresholds read off this same ascending rank --
    "top 30% by return" is rank_pct >= 0.70 (M2); "bottom 30% by D2" is
    rank_pct <= 0.30 (D3) -- the direction lives in the caller's comparison,
    not in a second rank function.
    """
    return values.rank(pct=True, method="average")


def max_abs_gap_ratio(bars: pd.DataFrame, atr_series: pd.Series, lookback: int) -> pd.Series:
    """Max over the trailing `lookback` days of |open - prior_close| / ATR (V2 input)."""
    prior_close = bars["close"].shift(1)
    gap = (bars["open"] - prior_close).abs()
    ratio = gap / atr_series
    return ratio.rolling(window=lookback, min_periods=1).max()


def is_nan(value: float | None) -> bool:
    return value is None or (isinstance(value, float) and np.isnan(value))
