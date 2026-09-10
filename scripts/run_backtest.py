#!/usr/bin/env python3
"""Run the in-sample backtest (spec section 9.1: 2010-01-01 to 2021-12-31).

This script refuses to touch the holdout period (2022-01-01 onward) unless
--allow-holdout is passed explicitly, and even then it records the run via
ledger.store.mark_holdout_run so a version's holdout can't be silently
re-run after seeing results (spec section 9.1 / acceptance criteria).

Usage:
    uv run scripts/run_backtest.py --data-dir data/ --db northstar.db
    uv run scripts/run_backtest.py --data-dir data/ --db northstar.db --allow-holdout
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from northstar.backtest.harness import run_backtest
from northstar.config import load_parameter_version
from northstar.db.connection import connect, migrate
from northstar.ingest.pipeline import ingest_range
from northstar.ledger import store
from northstar.providers.csv_provider import CsvMarketDataProvider
from northstar.providers.sqlite_provider import SqliteMarketDataProvider
from northstar.report.weekly import build_report, render_markdown


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--db", default="northstar.db")
    parser.add_argument("--param-version", default="p1")
    parser.add_argument("--account-value", type=float, default=100_000.0)
    parser.add_argument("--allow-holdout", action="store_true")
    parser.add_argument("--out", default="output/backtest_report.md")
    args = parser.parse_args()

    params = load_parameter_version(args.param_version)
    conn = connect(args.db)
    migrate(conn)
    store.freeze_parameter_version(conn, params)

    holdout_start = date.fromisoformat(params.holdout_start)
    end = date.fromisoformat(params.in_sample_end) if not args.allow_holdout else date.today()
    start = date.fromisoformat(params.in_sample_start)

    if args.allow_holdout:
        print(f"Running HOLDOUT for {params.version}: {holdout_start} .. {end}")
        start = holdout_start
        store.mark_holdout_run(conn, params.version)
    else:
        print(f"Running IN-SAMPLE for {params.version}: {start} .. {end}")

    raw_provider = CsvMarketDataProvider(data_dir=Path(args.data_dir))
    ingest_summary = ingest_range(
        conn,
        raw_provider,
        bars_start=start - timedelta(days=730),  # buffer for the 12-month formation window
        bars_end=end,
        events_start=start - timedelta(days=60),
        events_end=end + timedelta(days=20),
    )
    print(f"ingest: {ingest_summary}")
    provider = SqliteMarketDataProvider(conn=conn)

    bt = run_backtest(provider=provider, params=params, start=start, end=end, starting_equity=args.account_value)
    report = build_report(bt)
    markdown = render_markdown(report)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown)
    print(markdown)
    print(f"\nWritten to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
