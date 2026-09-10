"""Core data model for Northstar.

These are plain dataclasses, not ORM models. Storage (db/schema.sql) mirrors
these shapes but is kept separate so the engine can be tested with
hand-constructed in-memory objects, per the build spec's Phase 1 requirement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class SecurityStatus(str, Enum):
    ACTIVE = "active"
    DELISTED = "delisted"
    HALTED = "halted"


@dataclass(frozen=True, slots=True)
class Security:
    symbol: str
    name: str
    gics_sector: str
    listing_date: date
    delisting_date: date | None
    status: SecurityStatus
    is_etf: bool = False
    is_preferred: bool = False


@dataclass(frozen=True, slots=True)
class Bar:
    """One daily OHLCV bar. adjusted_close accounts for splits/dividends."""

    symbol: str
    date: date
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: int
    vendor: str
    ingested_at: datetime
    is_adjusted: bool = True


class CorporateEventType(str, Enum):
    EARNINGS = "earnings"
    EX_DIVIDEND = "ex_dividend"
    SPLIT = "split"
    CONSOLIDATION = "consolidation"
    HALT = "halt"
    ACQUISITION = "acquisition"
    DELISTING_NOTICE = "delisting_notice"
    OTHER_MATERIAL = "other_material"


@dataclass(frozen=True, slots=True)
class CorporateEvent:
    symbol: str
    type: CorporateEventType
    date: date
    source: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class NewsFlag:
    symbol: str
    date: date
    flag: str
    matched_text: str
    source: str


@dataclass(frozen=True, slots=True)
class IndexBar:
    """S&P/TSX Composite daily close, used for the regime gate (R1)."""

    date: date
    close: float


class RuleStep(str, Enum):
    """Ordered rule steps from spec section 5.3. Order matters for the ledger."""

    UNIVERSE = "universe"
    REGIME = "regime"
    MOMENTUM = "momentum"
    DIP = "dip"
    VETO = "veto"
    PORTFOLIO = "portfolio"
    RISK = "risk"
    RANK = "rank"
    RATE_LIMIT = "rate_limit"
    PASSED = "passed"


@dataclass(frozen=True, slots=True)
class RuleInputs:
    """Every computed input used by the rule engine for one (symbol, date).

    Stored verbatim in signal_evaluations so any alert -- or rejection -- is
    reproducible without recomputation.
    """

    symbol: str
    as_of: date

    # universe
    adv_20d_dollar: float | None = None
    median_spread_60d_pct: float | None = None
    price_history_days: int | None = None
    price: float | None = None

    # regime
    index_close: float | None = None
    index_sma_200: float | None = None

    # momentum
    formation_return: float | None = None
    formation_return_rank_pct: float | None = None
    sma_100: float | None = None

    # dip
    stock_5d_return: float | None = None
    sector_5d_return: float | None = None
    dip_relative: float | None = None  # D2
    dip_relative_rank_pct: float | None = None
    atr_14: float | None = None
    close_high_20d: float | None = None
    dip_depth_in_atr: float | None = None

    # vetoes
    turnover_ratio: float | None = None
    max_gap_atr_ratio_5d: float | None = None
    days_to_next_earnings: int | None = None
    days_since_event: int | None = None
    days_since_halt: int | None = None
    news_flags_10d: tuple[str, ...] = field(default_factory=tuple)

    gics_sector: str | None = None


@dataclass(frozen=True, slots=True)
class RuleResult:
    """Outcome of evaluating one symbol on one date."""

    symbol: str
    as_of: date
    param_version: str
    inputs: RuleInputs
    passed: bool
    reject_step: RuleStep | None
    reject_reason: str | None


@dataclass(frozen=True, slots=True)
class Signal:
    evaluation_symbol: str
    evaluation_date: date
    param_version: str
    entry_low: float
    entry_high: float
    stop: float
    target: float
    shares: int
    dollar_risk: float
    expiry_date: date
    dip_relative: float
    state: str = "new"  # new, filled, expired_unfilled, stopped, targeted, timed_out


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    shares: int
    fill_price: float
    fill_date: date
    stop: float
    target: float
    time_limit_date: date
    closed_date: date | None = None
    outcome: str | None = None  # stop, target, time, regime, event


@dataclass(frozen=True, slots=True)
class ExitReview:
    symbol: str
    condition: str  # stop, target, time, regime, event
    close: float
    as_of: date
