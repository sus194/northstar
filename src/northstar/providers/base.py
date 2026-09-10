"""Market data provider interface (spec section 8).

Northstar's engine only ever talks to this Protocol. Swapping vendors, or
running the backtest against a CSV snapshot, means writing one adapter --
nothing in engine/, backtest/, or notify/ changes.

Choosing a real vendor is a Phase 0 decision (spec section 10) and is
explicitly NOT made by this code: it involves cost and data-licensing terms
only the operator can agree to. See docs/data_provider_requirements.md.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

import pandas as pd

from northstar.models import CorporateEvent, IndexBar, NewsFlag, Security


class MarketDataProvider(Protocol):
    def universe(self, as_of: date) -> list[Security]:
        """TSX common shares active as of the given date (survivorship-aware if possible)."""
        ...

    def daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        """Columns: date, open, high, low, close, adjusted_close, volume, vendor, ingested_at."""
        ...

    def index_bars(self, start: date, end: date) -> pd.DataFrame:
        """S&P/TSX Composite daily closes. Columns: date, close."""
        ...

    def corporate_events(self, symbol: str, start: date, end: date) -> list[CorporateEvent]:
        ...

    def news_flags(self, symbol: str, start: date, end: date) -> list[NewsFlag]:
        ...


def index_bars_to_models(df: pd.DataFrame) -> list[IndexBar]:
    return [IndexBar(date=row.date, close=float(row.close)) for row in df.itertuples()]
