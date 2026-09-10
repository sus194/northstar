"""Append-only writes for the audit trail (spec section 8, table `signal_evaluations`).

Every function here does one INSERT (or, for parameter_versions, one
INSERT-if-absent -- freezing is idempotent but never overwrites). Nothing
in this module computes anything; it only persists what engine/evaluate.py
already decided.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, date, datetime

from northstar.config import ParameterVersion
from northstar.engine.evaluate import EvaluateResult
from northstar.models import RuleResult, Signal


def _now() -> str:
    return datetime.now(UTC).isoformat()


def freeze_parameter_version(conn: sqlite3.Connection, params: ParameterVersion) -> None:
    existing = conn.execute(
        "SELECT parameters_json FROM parameter_versions WHERE version = ?", (params.version,)
    ).fetchone()
    new_json = json.dumps(params.parameters, sort_keys=True)
    if existing is not None:
        if existing["parameters_json"] != new_json:
            raise ValueError(
                f"parameter_versions row for {params.version!r} already exists with different "
                "parameters. Freezing must never mutate a version in place -- mint a new "
                "version id instead (spec section 9.1)."
            )
        return
    conn.execute(
        """INSERT INTO parameter_versions
           (version, setup_name, frozen_at, holdout_start, in_sample_start, in_sample_end, parameters_json)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            params.version,
            params.setup_name,
            params.frozen_at,
            params.holdout_start,
            params.in_sample_start,
            params.in_sample_end,
            new_json,
        ),
    )
    conn.commit()


def mark_holdout_run(conn: sqlite3.Connection, version: str, run_at: str | None = None) -> None:
    row = conn.execute("SELECT holdout_run_at FROM parameter_versions WHERE version = ?", (version,)).fetchone()
    if row is None:
        raise ValueError(f"unknown parameter version {version!r}")
    if row["holdout_run_at"] is not None:
        raise ValueError(
            f"holdout for parameter version {version!r} was already run at {row['holdout_run_at']}. "
            "Per spec section 9.1, holdout may be consumed at most once per version."
        )
    conn.execute(
        "UPDATE parameter_versions SET holdout_run_at = ? WHERE version = ?",
        (run_at or _now(), version),
    )
    conn.commit()


def record_evaluation_result(conn: sqlite3.Connection, result: RuleResult) -> int:
    inputs_dict = asdict(result.inputs)
    inputs_dict["as_of"] = inputs_dict["as_of"].isoformat()
    cur = conn.execute(
        """INSERT OR REPLACE INTO signal_evaluations
           (date, symbol, param_version, inputs_json, passed, reject_step, reject_reason, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            result.as_of.isoformat(),
            result.symbol,
            result.param_version,
            json.dumps(inputs_dict, default=str),
            int(result.passed),
            result.reject_step.value if result.reject_step else None,
            result.reject_reason,
            _now(),
        ),
    )
    conn.commit()
    return cur.lastrowid


def record_evaluate_result(conn: sqlite3.Connection, evaluate_result: EvaluateResult) -> dict[str, int]:
    """Persist every RuleResult from one nightly run; returns symbol -> evaluation_id."""
    ids: dict[str, int] = {}
    for result in evaluate_result.results:
        ids[result.symbol] = record_evaluation_result(conn, result)
    return ids


def record_signal(conn: sqlite3.Connection, evaluation_id: int, signal: Signal) -> int:
    cur = conn.execute(
        """INSERT INTO signals
           (evaluation_id, symbol, date, param_version, entry_low, entry_high, stop, target,
            shares, dollar_risk, expiry_date, dip_relative, state, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            evaluation_id,
            signal.evaluation_symbol,
            signal.evaluation_date.isoformat(),
            signal.param_version,
            signal.entry_low,
            signal.entry_high,
            signal.stop,
            signal.target,
            signal.shares,
            signal.dollar_risk,
            signal.expiry_date.isoformat(),
            signal.dip_relative,
            signal.state,
            _now(),
        ),
    )
    conn.commit()
    return cur.lastrowid


def record_audit_event(conn: sqlite3.Connection, event_type: str, detail: dict) -> None:
    conn.execute(
        "INSERT INTO audit_events (at, event_type, detail_json) VALUES (?, ?, ?)",
        (_now(), event_type, json.dumps(detail, default=str)),
    )
    conn.commit()


def last_signal_dates(conn: sqlite3.Connection, as_of: date) -> dict[str, date]:
    rows = conn.execute(
        "SELECT symbol, MAX(date) as last_date FROM signals WHERE date < ? GROUP BY symbol",
        (as_of.isoformat(),),
    ).fetchall()
    return {row["symbol"]: date.fromisoformat(row["last_date"]) for row in rows}


def record_position(conn: sqlite3.Connection, position, signal_id: int | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO positions
           (symbol, shares, fill_price, fill_date, stop, target, time_limit_date, signal_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            position.symbol,
            position.shares,
            position.fill_price,
            position.fill_date.isoformat(),
            position.stop,
            position.target,
            position.time_limit_date.isoformat(),
            signal_id,
            _now(),
        ),
    )
    conn.commit()
    return cur.lastrowid


def close_position(conn: sqlite3.Connection, position_id: int, closed_date: date, outcome: str) -> None:
    conn.execute(
        "UPDATE positions SET closed_date = ?, outcome = ? WHERE id = ?",
        (closed_date.isoformat(), outcome, position_id),
    )
    conn.commit()


def exit_condition_already_sent(conn: sqlite3.Connection, position_id: int, condition: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM alerts WHERE type = 'exit' AND position_id = ? AND condition = ?",
        (position_id, condition),
    ).fetchone()
    return row is not None


def record_alert(
    conn: sqlite3.Connection,
    *,
    type_: str,
    subject: str,
    body: str,
    signal_id: int | None = None,
    position_id: int | None = None,
    condition: str | None = None,
    review_token: str | None = None,
    sent_at: str | None = None,
) -> int:
    cur = conn.execute(
        """INSERT INTO alerts
           (type, signal_id, position_id, condition, subject, body, review_token, sent_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (type_, signal_id, position_id, condition, subject, body, review_token, sent_at or _now()),
    )
    conn.commit()
    return cur.lastrowid


def entries_sent_counts(conn: sqlite3.Connection, as_of: date) -> tuple[int, int]:
    """(sent today, sent this ISO week) counting 'entry' alerts."""
    today_row = conn.execute(
        """SELECT COUNT(*) as n FROM alerts
           WHERE type = 'entry' AND date(sent_at) = ?""",
        (as_of.isoformat(),),
    ).fetchone()
    week_start = date.fromisocalendar(*as_of.isocalendar()[:2], 1)
    week_row = conn.execute(
        """SELECT COUNT(*) as n FROM alerts
           WHERE type = 'entry' AND date(sent_at) >= ? AND date(sent_at) <= ?""",
        (week_start.isoformat(), as_of.isoformat()),
    ).fetchone()
    return int(today_row["n"]), int(week_row["n"])
