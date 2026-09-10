#!/usr/bin/env python3
"""Nightly job (spec section 4): ingest -> quality -> universe -> regime ->
setup rule -> vetoes -> risk math -> rank -> ledger -> exit-watch -> email.

Run by cron on the TSX trading calendar at 17:00 ET. This script wires
together the pieces built as a library under src/northstar/ -- it holds no
rule logic itself.

Usage:
    uv run scripts/run_nightly.py --data-dir data/ --db northstar.db \
        --account-value 50000 [--kill-switch]

The provider defaults to CsvMarketDataProvider (see providers/csv_provider.py)
until a real vendor is wired up -- see docs/data_provider_requirements.md.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from northstar.config import load_parameter_version
from northstar.db.connection import connect, migrate
from northstar.engine import indicators as ind
from northstar.engine.calendar import trading_days_ago_from_dates
from northstar.engine.evaluate import HISTORY_LOOKBACK_DAYS, AlertRateState, PortfolioState, evaluate_date
from northstar.engine.exits import ExitContext, evaluate_exit
from northstar.ingest.pipeline import ingest_range
from northstar.ledger import store
from northstar.models import Position
from northstar.notify.email import (
    ConsoleEmailSender,
    EmailMessage,
    KillSwitchGuardedSender,
)
from northstar.notify.review_page import (
    new_review_token,
    render_review_page,
    write_review_page,
)
from northstar.notify.templates import (
    entry_body,
    entry_subject,
    exit_body,
    exit_subject,
    quiet_body,
    quiet_subject,
)
from northstar.providers.csv_provider import CsvMarketDataProvider
from northstar.providers.sqlite_provider import SqliteMarketDataProvider
from northstar.quality.checks import build_report, check_index_bars, check_symbol_bars

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("northstar.nightly")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--db", default="northstar.db")
    parser.add_argument("--review-dir", default="output/reviews")
    parser.add_argument("--param-version", default="p1")
    parser.add_argument("--account-value", type=float, required=True)
    parser.add_argument("--operator-email", default="operator@example.com")
    parser.add_argument("--as-of", default=None, help="ISO date; defaults to today")
    parser.add_argument("--kill-switch", action="store_true", help="disable sends without affecting ledger writes")
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    params = load_parameter_version(args.param_version)

    conn = connect(args.db)
    migrate(conn)
    store.freeze_parameter_version(conn, params)

    # Ingest: pull from the raw vendor/CSV source into the local ledger DB,
    # then read everything else back out of the DB. This is the seam where
    # a real vendor adapter gets swapped in later -- nothing below this
    # line needs to change when that happens.
    raw_provider = CsvMarketDataProvider(data_dir=Path(args.data_dir))
    ingest_summary = ingest_range(
        conn,
        raw_provider,
        bars_start=as_of - timedelta(days=HISTORY_LOOKBACK_DAYS),
        bars_end=as_of,
        events_start=as_of - timedelta(days=40),
        events_end=as_of + timedelta(days=15),
    )
    logger.info("ingest: %s", ingest_summary)
    provider = SqliteMarketDataProvider(conn=conn)

    sender = KillSwitchGuardedSender(inner=ConsoleEmailSender(), enabled=not args.kill_switch)

    # --- data quality gate ---
    index_df = provider.index_bars(as_of - timedelta(days=30), as_of)
    index_issues = check_index_bars(index_df, as_of)
    symbol_issues = {}
    securities = provider.universe(as_of)
    for sec in securities:
        bars = provider.daily_bars(sec.symbol, as_of - timedelta(days=30), as_of)
        issues = check_symbol_bars(sec.symbol, bars, as_of)
        if issues:
            symbol_issues[sec.symbol] = issues
    quality_report = build_report(as_of, index_issues, symbol_issues)

    if quality_report.block_send:
        store.record_audit_event(conn, "data_quality_block", {"issues": [i.__dict__ for i in quality_report.issues]})
        msg = EmailMessage(
            to=args.operator_email,
            subject=f"Northstar: data quality failure for {as_of.isoformat()}",
            body_text="Nightly run blocked. Issues:\n" + "\n".join(f"- {i.check}: {i.detail}" for i in quality_report.issues),
        )
        _safe_send(sender, msg)
        return 1

    # --- portfolio + alert-rate state from the ledger ---
    open_position_rows = conn.execute("SELECT * FROM positions WHERE closed_date IS NULL").fetchall()
    open_positions = [
        Position(
            symbol=r["symbol"],
            shares=r["shares"],
            fill_price=r["fill_price"],
            fill_date=date.fromisoformat(r["fill_date"]),
            stop=r["stop"],
            target=r["target"],
            time_limit_date=date.fromisoformat(r["time_limit_date"]),
        )
        for r in open_position_rows
    ]
    sector_by_symbol = {s.symbol: s.gics_sector for s in securities}
    by_sector: dict[str, int] = {}
    for pos in open_positions:
        sector = sector_by_symbol.get(pos.symbol, "unknown")
        by_sector[sector] = by_sector.get(sector, 0) + 1

    portfolio = PortfolioState(
        account_value=args.account_value,
        open_positions_symbols=frozenset(p.symbol for p in open_positions),
        open_positions_count=len(open_positions),
        open_positions_by_sector=by_sector,
    )
    entries_today, entries_week = store.entries_sent_counts(conn, as_of)
    alert_rate = AlertRateState(
        entries_sent_today=entries_today,
        entries_sent_this_week=entries_week,
        last_signal_date_by_symbol=store.last_signal_dates(conn, as_of),
    )

    # --- exit watches on open positions ---
    regime_failed_two_consecutive = _regime_failed_last_two_closes(provider, as_of)
    for pos, row in zip(open_positions, open_position_rows):
        bars = provider.daily_bars(pos.symbol, pos.fill_date - timedelta(days=30), as_of)
        if bars.empty:
            continue
        today_row = bars[bars["date"].dt.date == as_of]
        if today_row.empty:
            continue
        close = float(today_row.iloc[0]["close"])
        bar_dates = bars["date"].dt.date.tolist()
        days_since_fill = trading_days_ago_from_dates(bar_dates, pos.fill_date, as_of) or 0

        events = provider.corporate_events(pos.symbol, as_of - timedelta(days=5), as_of + timedelta(days=5))
        earnings_offsets = [
            trading_days_ago_from_dates(bar_dates, as_of, e.date) for e in events if e.type.value == "earnings"
        ]
        earnings_offsets = [o for o in earnings_offsets if o is not None]
        nearest_earnings = min(earnings_offsets, key=abs) if earnings_offsets else None

        ctx = ExitContext(
            close=close,
            as_of_date=as_of,
            trading_days_since_fill=days_since_fill,
            regime_failed_two_consecutive=regime_failed_two_consecutive,
            trading_days_to_nearest_earnings=nearest_earnings,
        )
        for review in evaluate_exit(pos, ctx, params):
            if store.exit_condition_already_sent(conn, row["id"], review.condition):
                continue
            msg = EmailMessage(to=args.operator_email, subject=exit_subject(review), body_text=exit_body(review))
            if _safe_send(sender, msg):
                store.record_alert(
                    conn, type_="exit", subject=msg.subject, body=msg.body_text, position_id=row["id"], condition=review.condition
                )

    # --- entry evaluation ---
    result = evaluate_date(as_of=as_of, provider=provider, params=params, portfolio=portfolio, alert_rate=alert_rate)
    eval_ids = store.record_evaluate_result(conn, result)

    if result.signal is None:
        msg = EmailMessage(
            to=args.operator_email,
            subject=quiet_subject(as_of),
            body_text=quiet_body(as_of=as_of, regime_pass=result.regime_pass, counts_by_step=result.counts_by_step_reached),
        )
        if _safe_send(sender, msg):
            store.record_alert(conn, type_="quiet", subject=msg.subject, body=msg.body_text)
        return 0

    signal = result.signal
    signal_result = next(r for r in result.results if r.symbol == signal.evaluation_symbol and r.passed)
    signal_id = store.record_signal(conn, eval_ids[signal.evaluation_symbol], signal)
    security = next(s for s in securities if s.symbol == signal.evaluation_symbol)

    token = new_review_token()
    review_html = render_review_page(
        company_name=security.name,
        sector=security.gics_sector,
        signal=signal,
        inputs=signal_result.inputs,
        vendor="csv-import",
        bar_timestamp=as_of.isoformat(),
    )
    write_review_page(args.review_dir, token, review_html)
    review_url = f"file://{Path(args.review_dir).resolve()}/{token}.html"

    msg = EmailMessage(
        to=args.operator_email,
        subject=entry_subject(signal.evaluation_symbol, signal),
        body_text=entry_body(
            symbol=signal.evaluation_symbol,
            company_name=security.name,
            sector=security.gics_sector,
            signal=signal,
            inputs=signal_result.inputs,
            vendor="csv-import",
            bar_timestamp=as_of.isoformat(),
            review_url=review_url,
        ),
    )
    if _safe_send(sender, msg):
        store.record_alert(conn, type_="entry", subject=msg.subject, body=msg.body_text, signal_id=signal_id, review_token=token)
    return 0


def _regime_failed_last_two_closes(provider, as_of: date) -> bool:
    """R1 (index close > 200-day SMA), evaluated for each of the last two
    sessions on record -- the exit-watch regime condition (spec section 6)
    fires only when it fails on both, not just today's."""
    index_df = provider.index_bars(as_of - timedelta(days=400), as_of)
    if index_df.empty:
        return False
    sma200 = ind.sma(index_df["close"], 200)
    last_two = sorted(index_df["date"].dt.date.unique())[-2:]
    if len(last_two) < 2:
        return False
    for d in last_two:
        pos = index_df.index[index_df["date"].dt.date == d]
        if not len(pos):
            return False
        sma = sma200.loc[pos[0]]
        close = index_df.loc[pos[0], "close"]
        if math.isnan(sma) or close > sma:
            return False
    return True


def _safe_send(sender, message: EmailMessage) -> bool:
    """Returns True if the message was actually sent. The kill switch must
    disable sends "without data loss" (acceptance criteria) -- so the
    signal_evaluations/signals rows above are written either way, but we
    must not write an alerts row claiming a send that never happened."""
    from northstar.notify.email import KillSwitchEngaged

    try:
        sender.send(message)
        return True
    except KillSwitchEngaged:
        logger.warning("Kill switch engaged; suppressed send of %r", message.subject)
        return False


if __name__ == "__main__":
    raise SystemExit(main())
