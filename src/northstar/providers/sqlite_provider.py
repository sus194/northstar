"""A MarketDataProvider backed by the local ledger DB.

This is what the engine actually reads from in normal operation: the
nightly job and the backtest both run `ingest.pipeline.ingest_range()`
once against whatever vendor adapter is configured, then hand this class
to `engine.evaluate.evaluate_date()` / `backtest.harness.run_backtest()`.
That keeps "data acquisition" and "what the engine saw" as separate,
independently-inspectable steps (spec section 8's architecture diagram).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

import pandas as pd

from northstar.models import (
    CorporateEvent,
    CorporateEventType,
    NewsFlag,
    Security,
    SecurityStatus,
)

_BAR_COLUMNS = ["date", "open", "high", "low", "close", "adjusted_close", "volume", "vendor", "ingested_at"]


@dataclass(slots=True)
class SqliteMarketDataProvider:
    conn: sqlite3.Connection

    def universe(self, as_of: date) -> list[Security]:
        rows = self.conn.execute("SELECT * FROM securities").fetchall()
        out: list[Security] = []
        for row in rows:
            listing_date = date.fromisoformat(row["listing_date"])
            delisting_date = date.fromisoformat(row["delisting_date"]) if row["delisting_date"] else None
            if listing_date > as_of:
                continue
            if delisting_date is not None and delisting_date < as_of:
                continue
            out.append(
                Security(
                    symbol=row["symbol"],
                    name=row["name"],
                    gics_sector=row["gics_sector"],
                    listing_date=listing_date,
                    delisting_date=delisting_date,
                    status=SecurityStatus(row["status"]),
                    is_etf=bool(row["is_etf"]),
                    is_preferred=bool(row["is_preferred"]),
                )
            )
        return out

    def daily_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        rows = self.conn.execute(
            """SELECT date, open, high, low, close, adjusted_close, volume, vendor, ingested_at
               FROM daily_bars WHERE symbol = ? AND date >= ? AND date <= ? ORDER BY date""",
            (symbol, start.isoformat(), end.isoformat()),
        ).fetchall()
        if not rows:
            return pd.DataFrame(columns=_BAR_COLUMNS)
        df = pd.DataFrame([dict(r) for r in rows])
        df["date"] = pd.to_datetime(df["date"])
        return df

    def index_bars(self, start: date, end: date) -> pd.DataFrame:
        rows = self.conn.execute(
            "SELECT date, close FROM index_bars WHERE date >= ? AND date <= ? ORDER BY date",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        if not rows:
            return pd.DataFrame(columns=["date", "close"])
        df = pd.DataFrame([dict(r) for r in rows])
        df["date"] = pd.to_datetime(df["date"])
        return df

    def corporate_events(self, symbol: str, start: date, end: date) -> list[CorporateEvent]:
        rows = self.conn.execute(
            "SELECT * FROM corporate_events WHERE symbol = ? AND date >= ? AND date <= ?",
            (symbol, start.isoformat(), end.isoformat()),
        ).fetchall()
        return [
            CorporateEvent(
                symbol=r["symbol"],
                type=CorporateEventType(r["type"]),
                date=date.fromisoformat(r["date"]),
                source=r["source"],
                detail=r["detail"],
            )
            for r in rows
        ]

    def news_flags(self, symbol: str, start: date, end: date) -> list[NewsFlag]:
        rows = self.conn.execute(
            "SELECT * FROM news_flags WHERE symbol = ? AND date >= ? AND date <= ?",
            (symbol, start.isoformat(), end.isoformat()),
        ).fetchall()
        return [
            NewsFlag(symbol=r["symbol"], date=date.fromisoformat(r["date"]), flag=r["flag"], matched_text=r["matched_text"], source=r["source"])
            for r in rows
        ]
