"""An in-memory MarketDataProvider for integration-testing engine/evaluate.py
against hand-constructed price paths, per the Phase 1 requirement that the
engine be tested without a real vendor."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd

from northstar.models import CorporateEvent, NewsFlag, Security, SecurityStatus


def make_bars(
    n: int,
    start_price: float,
    daily_return: float,
    end_date: date,
    tail_returns: list[float] | None = None,
    range_pct: float = 0.02,
    volume: int = 500_000,
) -> pd.DataFrame:
    """n trading days ending at end_date. daily_return applied for the whole
    series except the final len(tail_returns) days, which use tail_returns
    verbatim (so a dip can be hand-specified precisely)."""
    tail_returns = tail_returns or []
    n_head = n - len(tail_returns)
    closes = [start_price]
    for _ in range(n_head - 1):
        closes.append(closes[-1] * (1 + daily_return))
    for r in tail_returns:
        closes.append(closes[-1] * (1 + r))

    dates = pd.bdate_range(end=end_date, periods=n)
    closes = np.array(closes)
    highs = closes * (1 + range_pct / 2)
    lows = closes * (1 - range_pct / 2)
    opens = np.roll(closes, 1)
    opens[0] = closes[0]

    return pd.DataFrame(
        {
            "date": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "adjusted_close": closes,
            "volume": [volume] * n,
            "vendor": "test",
            "ingested_at": datetime.now(UTC),
        }
    )


@dataclass
class InMemoryProvider:
    securities: list[Security]
    bars: dict[str, pd.DataFrame]
    index_df: pd.DataFrame
    events: dict[str, list[CorporateEvent]] = field(default_factory=dict)
    news: dict[str, list[NewsFlag]] = field(default_factory=dict)

    def universe(self, as_of: date) -> list[Security]:
        return list(self.securities)

    def daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        df = self.bars.get(symbol)
        if df is None:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "adjusted_close", "volume"])
        mask = (df["date"].dt.date >= start) & (df["date"].dt.date <= end)
        return df[mask].reset_index(drop=True)

    def index_bars(self, start: date, end: date) -> pd.DataFrame:
        mask = (self.index_df["date"].dt.date >= start) & (self.index_df["date"].dt.date <= end)
        return self.index_df[mask].reset_index(drop=True)

    def corporate_events(self, symbol: str, start: date, end: date) -> list[CorporateEvent]:
        return [e for e in self.events.get(symbol, []) if start <= e.date <= end]

    def news_flags(self, symbol: str, start: date, end: date) -> list[NewsFlag]:
        return [n for n in self.news.get(symbol, []) if start <= n.date <= end]


def make_index_bars(n: int, end_date: date, daily_return: float = 0.0004, start_price: float = 20000.0) -> pd.DataFrame:
    dates = pd.bdate_range(end=end_date, periods=n)
    closes = [start_price]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1 + daily_return))
    return pd.DataFrame({"date": dates, "close": closes})


def make_security(symbol: str, sector: str) -> Security:
    return Security(
        symbol=symbol,
        name=f"{symbol} Corp",
        gics_sector=sector,
        listing_date=date(2000, 1, 1),
        delisting_date=None,
        status=SecurityStatus.ACTIVE,
    )
