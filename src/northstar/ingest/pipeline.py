"""Ingest: vendor EOD bars, corporate events, news flags -> SQLite (spec
section 8's architecture diagram).

This is the seam between "wherever the data actually lives" (a paid vendor
API, or `CsvMarketDataProvider` reading a flat directory) and "what the
engine reads" (always the local ledger DB, via
`providers.sqlite_provider.SqliteMarketDataProvider`). Two consequences of
that seam:

  - A rate-limited or metered vendor is called once per ingest, not once
    per symbol per backtest day.
  - What the engine evaluated against is a durable, inspectable local
    record, not a live call that can't be replayed later.

Idempotent: every write is an upsert keyed on the table's natural key, so
running ingest twice for the same day is a no-op the second time.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from northstar.models import Security
from northstar.providers.base import MarketDataProvider


@dataclass(slots=True)
class IngestSummary:
    securities: int
    bar_rows: int
    index_rows: int
    event_rows: int
    news_rows: int


def ingest_range(
    conn: sqlite3.Connection,
    provider: MarketDataProvider,
    *,
    bars_start: date,
    bars_end: date,
    events_start: date | None = None,
    events_end: date | None = None,
    universe_as_of: date | None = None,
) -> IngestSummary:
    """Bars only ever run up to `bars_end` (no future price data exists).
    Events default to the same window but are independent -- the nightly
    job wants a corporate-events *lookahead* past `bars_end` (an upcoming
    earnings date has to be known before it happens for V3 to veto on it),
    while a multi-year backtest wants events across its whole replay
    window, not just near the end. `universe_as_of` defaults to
    `bars_end` (the securities list as of the most recent day ingested).
    """
    as_of_universe = universe_as_of or bars_end
    events_start = events_start or bars_start
    events_end = events_end or bars_end

    securities = provider.universe(as_of_universe)
    for sec in securities:
        _upsert_security(conn, sec)

    bar_rows = 0
    event_rows = 0
    news_rows = 0
    for sec in securities:
        bars = provider.daily_bars(sec.symbol, bars_start, bars_end)
        bar_rows += _upsert_bars(conn, sec.symbol, bars)

        events = provider.corporate_events(sec.symbol, events_start, events_end)
        event_rows += _upsert_events(conn, events)

        news = provider.news_flags(sec.symbol, events_start, bars_end)
        news_rows += _upsert_news(conn, news)

    index_df = provider.index_bars(bars_start, bars_end)
    index_rows = _upsert_index_bars(conn, index_df)

    conn.commit()
    return IngestSummary(
        securities=len(securities), bar_rows=bar_rows, index_rows=index_rows, event_rows=event_rows, news_rows=news_rows
    )


def _upsert_security(conn: sqlite3.Connection, sec: Security) -> None:
    conn.execute(
        """INSERT INTO securities (symbol, name, gics_sector, listing_date, delisting_date, status, is_etf, is_preferred)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(symbol) DO UPDATE SET
             name=excluded.name, gics_sector=excluded.gics_sector, listing_date=excluded.listing_date,
             delisting_date=excluded.delisting_date, status=excluded.status,
             is_etf=excluded.is_etf, is_preferred=excluded.is_preferred""",
        (
            sec.symbol,
            sec.name,
            sec.gics_sector,
            sec.listing_date.isoformat(),
            sec.delisting_date.isoformat() if sec.delisting_date else None,
            sec.status.value,
            int(sec.is_etf),
            int(sec.is_preferred),
        ),
    )


def _upsert_bars(conn: sqlite3.Connection, symbol: str, bars) -> int:
    if bars.empty:
        return 0
    rows = 0
    for row in bars.itertuples():
        conn.execute(
            """INSERT INTO daily_bars (symbol, date, open, high, low, close, adjusted_close, volume, vendor, ingested_at, is_adjusted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(symbol, date) DO UPDATE SET
                 open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                 adjusted_close=excluded.adjusted_close, volume=excluded.volume,
                 vendor=excluded.vendor, ingested_at=excluded.ingested_at""",
            (
                symbol,
                row.date.date().isoformat() if hasattr(row.date, "date") else str(row.date),
                float(row.open),
                float(row.high),
                float(row.low),
                float(row.close),
                float(getattr(row, "adjusted_close", row.close)),
                int(row.volume),
                str(getattr(row, "vendor", "unknown")),
                str(getattr(row, "ingested_at", "")),
                1,
            ),
        )
        rows += 1
    return rows


def _upsert_index_bars(conn: sqlite3.Connection, index_df) -> int:
    if index_df.empty:
        return 0
    rows = 0
    for row in index_df.itertuples():
        conn.execute(
            """INSERT INTO index_bars (date, close) VALUES (?, ?)
               ON CONFLICT(date) DO UPDATE SET close=excluded.close""",
            (row.date.date().isoformat() if hasattr(row.date, "date") else str(row.date), float(row.close)),
        )
        rows += 1
    return rows


def _upsert_events(conn: sqlite3.Connection, events) -> int:
    rows = 0
    for e in events:
        existing = conn.execute(
            "SELECT id FROM corporate_events WHERE symbol = ? AND type = ? AND date = ?",
            (e.symbol, e.type.value, e.date.isoformat()),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO corporate_events (symbol, type, date, source, detail) VALUES (?, ?, ?, ?, ?)",
            (e.symbol, e.type.value, e.date.isoformat(), e.source, e.detail),
        )
        rows += 1
    return rows


def _upsert_news(conn: sqlite3.Connection, flags) -> int:
    rows = 0
    for n in flags:
        existing = conn.execute(
            "SELECT id FROM news_flags WHERE symbol = ? AND date = ? AND flag = ?",
            (n.symbol, n.date.isoformat(), n.flag),
        ).fetchone()
        if existing:
            continue
        conn.execute(
            "INSERT INTO news_flags (symbol, date, flag, matched_text, source) VALUES (?, ?, ?, ?, ?)",
            (n.symbol, n.date.isoformat(), n.flag, n.matched_text, n.source),
        )
        rows += 1
    return rows
