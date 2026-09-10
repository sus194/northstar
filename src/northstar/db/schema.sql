-- Northstar schema (spec section 8). SQLite, WAL mode.
-- Append-only tables (signal_evaluations, signals, alerts, audit_events) are
-- never UPDATEd except for narrow, explicitly-audited state transitions
-- (signal.state, position closure) -- see ledger/store.py docstrings.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS securities (
    symbol           TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    gics_sector      TEXT NOT NULL,
    listing_date     TEXT NOT NULL,
    delisting_date   TEXT,
    status           TEXT NOT NULL CHECK (status IN ('active','delisted','halted')),
    is_etf           INTEGER NOT NULL DEFAULT 0,
    is_preferred     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_bars (
    symbol           TEXT NOT NULL REFERENCES securities(symbol),
    date             TEXT NOT NULL,
    open             REAL NOT NULL,
    high             REAL NOT NULL,
    low              REAL NOT NULL,
    close            REAL NOT NULL,
    adjusted_close   REAL NOT NULL,
    volume           INTEGER NOT NULL,
    vendor           TEXT NOT NULL,
    ingested_at      TEXT NOT NULL,
    is_adjusted      INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS index_bars (
    date  TEXT PRIMARY KEY,
    close REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS corporate_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol   TEXT NOT NULL REFERENCES securities(symbol),
    type     TEXT NOT NULL,
    date     TEXT NOT NULL,
    source   TEXT NOT NULL,
    detail   TEXT
);
CREATE INDEX IF NOT EXISTS idx_corporate_events_symbol_date ON corporate_events(symbol, date);

CREATE TABLE IF NOT EXISTS news_flags (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT NOT NULL REFERENCES securities(symbol),
    date          TEXT NOT NULL,
    flag          TEXT NOT NULL,
    matched_text  TEXT NOT NULL,
    source        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_news_flags_symbol_date ON news_flags(symbol, date);

CREATE TABLE IF NOT EXISTS parameter_versions (
    version         TEXT PRIMARY KEY,
    setup_name      TEXT NOT NULL,
    frozen_at       TEXT NOT NULL,
    holdout_start   TEXT NOT NULL,
    in_sample_start TEXT NOT NULL,
    in_sample_end   TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    holdout_run_at  TEXT
);

-- One row per (date, symbol) that reached step 3 (momentum) or later --
-- i.e. survived the universe filter. This is the audit trail (spec 5.3).
CREATE TABLE IF NOT EXISTS signal_evaluations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    param_version   TEXT NOT NULL REFERENCES parameter_versions(version),
    inputs_json     TEXT NOT NULL,
    passed          INTEGER NOT NULL,
    reject_step     TEXT,
    reject_reason   TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signal_evaluations_date ON signal_evaluations(date);
CREATE INDEX IF NOT EXISTS idx_signal_evaluations_symbol ON signal_evaluations(symbol);
CREATE UNIQUE INDEX IF NOT EXISTS uq_signal_evaluations_date_symbol_version
    ON signal_evaluations(date, symbol, param_version);

CREATE TABLE IF NOT EXISTS signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    evaluation_id   INTEGER NOT NULL REFERENCES signal_evaluations(id),
    symbol          TEXT NOT NULL,
    date            TEXT NOT NULL,
    param_version   TEXT NOT NULL,
    entry_low       REAL NOT NULL,
    entry_high      REAL NOT NULL,
    stop            REAL NOT NULL,
    target          REAL NOT NULL,
    shares          INTEGER NOT NULL,
    dollar_risk     REAL NOT NULL,
    expiry_date     TEXT NOT NULL,
    dip_relative    REAL NOT NULL,
    state           TEXT NOT NULL DEFAULT 'new',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol           TEXT NOT NULL,
    shares           INTEGER NOT NULL,
    fill_price       REAL NOT NULL,
    fill_date        TEXT NOT NULL,
    stop             REAL NOT NULL,
    target           REAL NOT NULL,
    time_limit_date  TEXT NOT NULL,
    closed_date      TEXT,
    outcome          TEXT,
    signal_id        INTEGER REFERENCES signals(id),
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);

CREATE TABLE IF NOT EXISTS alerts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    type               TEXT NOT NULL CHECK (type IN ('entry','quiet','exit')),
    signal_id          INTEGER REFERENCES signals(id),
    position_id        INTEGER REFERENCES positions(id),
    condition          TEXT,
    subject            TEXT NOT NULL,
    body               TEXT NOT NULL,
    provider_message_id TEXT,
    sent_at            TEXT,
    delivered_at       TEXT,
    opened_at          TEXT,
    review_token       TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_signal ON alerts(signal_id);
CREATE INDEX IF NOT EXISTS idx_alerts_position ON alerts(position_id);

CREATE TABLE IF NOT EXISTS audit_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
