"""SQLite connection + migration (spec section 8: "one file, trivially backed up").

WAL mode is turned on at connect time so the nightly writer and an
occasional read (e.g. rendering a review page) don't block each other.
"""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.row_factory = sqlite3.Row
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    schema_path = resources.files("northstar.db") / "schema.sql"
    conn.executescript(schema_path.read_text())
    conn.commit()
