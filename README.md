# Northstar

A personal, end-of-day decision-support tool for one self-directed Canadian
investor trading TSX-listed common shares in CAD, holding 3-15 trading
days. Once per trading day, after the close, it scans the liquid TSX
universe for a single rule -- **intermediate-term momentum winner + short-
term sector-relative dip** -- applies risk and veto rules, and (once wired
to email) sends at most one entry review before the next open. It also
watches manually entered positions and sends an exit review when a
predefined condition is met.

It does not place orders, promise performance, act as an advisor, or serve
other users. **Personal use only** -- see "Scope decision" below.

This repository implements the build spec in full: the rule engine,
backtest harness, ledger, quality gate, exit watches, and email/review-page
notification layer. What it does *not* do yet is talk to a real market
data vendor or a real email provider -- those are Phase 0 decisions the
operator has to make (cost, licensing terms), not something to wire up
silently. See "What's not done" below.

## Scope decision

Northstar is private personal-use software. It will not be offered to
others, will not make individualized recommendations to anyone but its
operator, and will not redistribute market data. If that ever changes,
Canadian securities counsel and data-licensing review come first.

## Quickstart

```bash
uv sync                 # installs Python 3.12 + deps into .venv
uv run pytest -q        # 65 unit/integration tests, all pure-function or in-memory
```

There is no real data yet. To see the whole pipeline run end to end
against a small hand-built fixture (four symbols, two sectors, tuned so
one clears every rule), see `tests/synthetic.py` and
`tests/test_evaluate_integration.py`. The same generator can produce a
CSV directory (`CsvMarketDataProvider`'s layout) to drive
`scripts/run_nightly.py` and `scripts/run_backtest.py` manually.

Once real data is in the `CsvMarketDataProvider` layout (see its
docstring) or a real `MarketDataProvider` adapter is written:

```bash
# Nightly job (spec section 4) -- normally run by cron at 17:00 ET
uv run scripts/run_nightly.py --data-dir data/ --db northstar.db --account-value 50000

# In-sample backtest (2010-01-01 .. 2021-12-31, spec section 9.1)
uv run scripts/run_backtest.py --data-dir data/ --db northstar.db

# Holdout (2022-01-01 onward) -- consumes the holdout for this parameter
# version; can only be run once per version (enforced in the ledger)
uv run scripts/run_backtest.py --data-dir data/ --db northstar.db --allow-holdout
```

## What's implemented

- `src/northstar/models.py` -- the full data model (spec section 8).
- `src/northstar/ingest/pipeline.py` + `providers/sqlite_provider.py` --
  the ingest seam from the architecture diagram: whatever `MarketDataProvider`
  the raw source is (CSV today, a real vendor adapter later) gets pulled
  into the local ledger DB once, and the engine always reads back out of
  the DB via `SqliteMarketDataProvider`, never the raw source directly.
  Idempotent (safe to re-run for the same day).
- `src/northstar/engine/` -- every rule from spec section 5.2/5.3 (U1-U4,
  R1, M1-M3, D1-D5, V1-V6, E1-E4, S1-S3, A1) as pure, independently unit-
  tested functions, plus `evaluate.py`, which runs them in the spec's
  exact order and is the single code path both the nightly job and the
  backtest replay call.
- `src/northstar/engine/exits.py` -- the five exit-watch conditions (spec
  section 6).
- `src/northstar/backtest/` -- the cost model (spec section 9.3: zero
  commission, half the Corwin-Schultz spread estimate per side, liquidity-
  tiered slippage, worst-of-trigger-or-gap fills) and a replay harness that
  calls the exact same engine code the nightly job does.
- `src/northstar/report/weekly.py` -- the weekly strategy report (spec
  section 9.4): win rate, mean/median R, worst trades, drawdown, exit
  attribution, veto counts, rejection counts by rule step.
- `src/northstar/ledger/store.py` -- the append-only audit trail (spec
  section 8's `signal_evaluations` / `signals` / `alerts` /
  `audit_events` tables), plus the two most important invariants as code,
  not just discipline: a parameter version can never be silently mutated
  after freezing, and a holdout can never be run twice for the same
  version.
- `src/northstar/notify/` -- email templates matching spec section 7
  verbatim, a static review-page renderer with a one-time token and no
  identifying data in the URL, and a kill switch that blocks sends without
  losing the underlying ledger data.
- `src/northstar/quality/checks.py` -- the data-quality gate: stale bars,
  duplicate rows, negative values, inconsistent OHLC, extreme single-day
  moves; a broad index-level failure blocks the whole run, a per-symbol
  issue excludes just that symbol.
- `scripts/run_nightly.py` / `scripts/run_backtest.py` -- the orchestration
  spec section 8's architecture diagram describes, wired together.
- `tests/` -- 65 tests: one or more per named parameter, hand-computed
  indicator values, and a full 4-symbol/2-sector integration test that
  exercises every rejection step in spec section 5.3's order.

## What's not done (Phase 0 / operator decisions)

1. **A real data vendor.** `CsvMarketDataProvider` reads a flat CSV
   directory so the system is fully testable without one. See
   `docs/data_provider_requirements.md` for the hard requirements
   (delisted-symbol history in particular -- without it the backtest is
   survivorship-biased) before spending money on one.
2. **A real email provider.** `ConsoleEmailSender` logs instead of
   delivering. Swapping in Postmark/Resend/SES is one small adapter class
   once an account and API key exist.
3. **A real TSX trading-day calendar.** `engine/calendar.py` currently
   uses a plain Monday-Friday business calendar. See
   `docs/known_limitations.md` -- this needs fixing before the in-sample
   backtest is run for real, not just before going live.
4. **Cron.** `scripts/run_nightly.py` is the job; scheduling it on the TSX
   calendar at 17:00 ET is a one-line cron/systemd-timer entry once a real
   data vendor's data-landing time is known.
5. **The actual testing run.** Nothing here has been backtested against
   real TSX data -- parameter version `p1` (see below) is frozen and ready
   to be tested against real history the moment a data vendor is chosen.

## Parameter version p1

Frozen at `src/northstar/params/p1.json` (spec section 5.2, section 9.1).
**Never edit this file after real backtesting begins against it** -- a
changed default means minting `p2` and starting a fresh holdout. The
freeze is also enforced at write time:
`ledger.store.freeze_parameter_version` raises if a version's parameters
in the database ever disagree with the JSON on disk, and
`ledger.store.mark_holdout_run` raises if a holdout is run twice for the
same version.

In-sample: 2010-01-01 to 2021-12-31. Holdout: 2022-01-01 onward, untouched
until the in-sample work is written up (spec section 9.1).

## Known limitations

See `docs/known_limitations.md` -- small-sample power, survivorship,
thin Canadian evidence for the reversal leg specifically, long-only
gross-to-net cost drag, the trading-calendar approximation, and the
OHLC-only spread estimator. Every weekly report generated from this code
should be read alongside that document, not instead of it.

## Compliance

Personal-use, single-operator, no redistribution of data, no execution.
Market-data terms must permit personal analytical use; keep the
entitlement document with the repo. If any of that changes, stop and get
counsel (spec section 12).
