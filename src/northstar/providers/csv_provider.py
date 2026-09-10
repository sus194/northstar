"""A MarketDataProvider backed by flat CSV files.

This is the provider to use until a real vendor is chosen and wired up
(Phase 0). It reads a directory laid out as:

    data/
      securities.csv        symbol,name,gics_sector,listing_date,delisting_date,status,is_etf,is_preferred
      index.csv              date,close
      bars/<SYMBOL>.csv       date,open,high,low,close,adjusted_close,volume
      corporate_events.csv   symbol,type,date,source,detail
      news_flags.csv         symbol,date,flag,matched_text,source

Any vendor export can be reshaped into this layout with a small script,
which keeps the reshaping logic out of the engine entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from northstar.models import (
    CorporateEvent,
    CorporateEventType,
    NewsFlag,
    Security,
    SecurityStatus,
)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


@dataclass(slots=True)
class CsvMarketDataProvider:
    data_dir: Path
    vendor_name: str = "csv-import"

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)

    def universe(self, as_of: date) -> list[Security]:
        path = self.data_dir / "securities.csv"
        df = pd.read_csv(path)
        out: list[Security] = []
        for row in df.itertuples():
            listing_date = _parse_date(row.listing_date)
            delisting_date = (
                _parse_date(row.delisting_date)
                if isinstance(row.delisting_date, str) and row.delisting_date
                else None
            )
            if listing_date > as_of:
                continue
            if delisting_date is not None and delisting_date < as_of:
                continue
            out.append(
                Security(
                    symbol=row.symbol,
                    name=row.name,
                    gics_sector=row.gics_sector,
                    listing_date=listing_date,
                    delisting_date=delisting_date,
                    status=SecurityStatus(row.status),
                    is_etf=bool(getattr(row, "is_etf", False)),
                    is_preferred=bool(getattr(row, "is_preferred", False)),
                )
            )
        return out

    def daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        path = self.data_dir / "bars" / f"{symbol}.csv"
        if not path.exists():
            return pd.DataFrame(
                columns=[
                    "date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "adjusted_close",
                    "volume",
                    "vendor",
                    "ingested_at",
                ]
            )
        df = pd.read_csv(path, parse_dates=["date"])
        df = df[(df["date"].dt.date >= start) & (df["date"].dt.date <= end)].reset_index(drop=True)
        df["vendor"] = self.vendor_name
        df["ingested_at"] = datetime.now(UTC)
        return df

    def index_bars(self, start: date, end: date) -> pd.DataFrame:
        path = self.data_dir / "index.csv"
        df = pd.read_csv(path, parse_dates=["date"])
        return df[(df["date"].dt.date >= start) & (df["date"].dt.date <= end)].reset_index(drop=True)

    def corporate_events(self, symbol: str, start: date, end: date) -> list[CorporateEvent]:
        path = self.data_dir / "corporate_events.csv"
        if not path.exists():
            return []
        df = pd.read_csv(path)
        df = df[df["symbol"] == symbol]
        out = []
        for row in df.itertuples():
            d = _parse_date(row.date)
            if not (start <= d <= end):
                continue
            out.append(
                CorporateEvent(
                    symbol=row.symbol,
                    type=CorporateEventType(row.type),
                    date=d,
                    source=row.source,
                    detail=getattr(row, "detail", None),
                )
            )
        return out

    def news_flags(self, symbol: str, start: date, end: date) -> list[NewsFlag]:
        path = self.data_dir / "news_flags.csv"
        if not path.exists():
            return []
        df = pd.read_csv(path)
        df = df[df["symbol"] == symbol]
        out = []
        for row in df.itertuples():
            d = _parse_date(row.date)
            if not (start <= d <= end):
                continue
            out.append(
                NewsFlag(
                    symbol=row.symbol,
                    date=d,
                    flag=row.flag,
                    matched_text=row.matched_text,
                    source=row.source,
                )
            )
        return out
