"""Round-trip test: ingest a hand-built provider's data into a fresh
SQLite ledger DB, then read it back out through SqliteMarketDataProvider
and confirm the two providers agree -- the ingest/SQLite seam described in
ingest/pipeline.py's docstring."""

from __future__ import annotations

from datetime import date

from northstar.db.connection import connect, migrate
from northstar.ingest.pipeline import ingest_range
from northstar.providers.sqlite_provider import SqliteMarketDataProvider

from .synthetic import InMemoryProvider, make_bars, make_index_bars, make_security

END = date(2024, 6, 28)
N = 60


def _source_provider() -> InMemoryProvider:
    aaa = make_bars(N, start_price=20.0, daily_return=0.001, end_date=END, range_pct=0.01)
    bbb = make_bars(N, start_price=30.0, daily_return=0.0005, end_date=END, range_pct=0.01)
    index_df = make_index_bars(N, end_date=END)
    return InMemoryProvider(
        securities=[make_security("AAA", "Financials"), make_security("BBB", "Energy")],
        bars={"AAA": aaa, "BBB": bbb},
        index_df=index_df,
    )


def test_ingest_then_read_back_matches_source(tmp_path):
    source = _source_provider()
    conn = connect(tmp_path / "test.db")
    migrate(conn)

    start = date(2024, 1, 1)
    summary = ingest_range(conn, source, bars_start=start, bars_end=END)

    assert summary.securities == 2
    assert summary.bar_rows > 0
    assert summary.index_rows > 0

    sqlite_provider = SqliteMarketDataProvider(conn=conn)

    securities = sqlite_provider.universe(END)
    assert {s.symbol for s in securities} == {"AAA", "BBB"}
    sectors = {s.symbol: s.gics_sector for s in securities}
    assert sectors["AAA"] == "Financials"
    assert sectors["BBB"] == "Energy"

    source_bars = source.daily_bars("AAA", start, END)
    round_tripped_bars = sqlite_provider.daily_bars("AAA", start, END)
    assert len(round_tripped_bars) == len(source_bars)
    assert round_tripped_bars["close"].iloc[-1] == source_bars["close"].iloc[-1]

    source_index = source.index_bars(start, END)
    round_tripped_index = sqlite_provider.index_bars(start, END)
    assert len(round_tripped_index) == len(source_index)


def test_ingest_is_idempotent(tmp_path):
    source = _source_provider()
    conn = connect(tmp_path / "test.db")
    migrate(conn)
    start = date(2024, 1, 1)

    first = ingest_range(conn, source, bars_start=start, bars_end=END)
    second = ingest_range(conn, source, bars_start=start, bars_end=END)

    assert first.bar_rows == second.bar_rows
    row_count = conn.execute("SELECT COUNT(*) as n FROM daily_bars").fetchone()["n"]
    assert row_count == first.bar_rows  # no duplicate rows from re-ingesting
