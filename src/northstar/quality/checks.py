"""Data-quality gate (spec section 8: "block send on failure").

Runs after ingest, before the universe filter. If any check fails for a
symbol whose bar would otherwise be used tonight, the run is not aborted
silently -- see acceptance criteria: the nightly job must always emit an
entry review, a quiet digest, or a data-quality failure notice, never
nothing. Callers decide whether a failure blocks the whole run or just
excludes the affected symbol; both are represented here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd


@dataclass(frozen=True, slots=True)
class QualityIssue:
    symbol: str
    check: str
    detail: str


@dataclass(slots=True)
class QualityReport:
    as_of: date
    issues: list[QualityIssue] = field(default_factory=list)

    @property
    def block_send(self) -> bool:
        """Blocks the whole run only for issues that cast doubt on data integrity
        broadly (e.g. the reference index itself looks wrong); per-symbol issues
        just exclude that symbol and are reported in the quiet digest."""
        return any(i.check == "index_bar_missing_or_stale" for i in self.issues)

    def symbols_to_exclude(self) -> set[str]:
        return {i.symbol for i in self.issues if i.symbol}


def check_symbol_bars(symbol: str, bars: pd.DataFrame, as_of: date, max_staleness_days: int = 4) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    if bars.empty:
        return [QualityIssue(symbol, "no_data", "no bars returned")]

    df = bars.sort_values("date")
    dates = df["date"].dt.date.tolist()

    latest = dates[-1]
    if (as_of - latest) > timedelta(days=max_staleness_days):
        issues.append(QualityIssue(symbol, "stale_bar", f"latest bar {latest} is stale as of {as_of}"))

    dup = df["date"].duplicated().sum()
    if dup:
        issues.append(QualityIssue(symbol, "duplicate_rows", f"{dup} duplicate date rows"))

    for col in ("open", "high", "low", "close", "volume"):
        if (df[col] < 0).any():
            issues.append(QualityIssue(symbol, "negative_value", f"{col} has negative values"))

    bad_ohlc = df[(df["high"] < df["low"]) | (df["close"] > df["high"]) | (df["close"] < df["low"])]
    if not bad_ohlc.empty:
        issues.append(QualityIssue(symbol, "ohlc_inconsistent", f"{len(bad_ohlc)} rows with high<low or close outside range"))

    returns = df["close"].pct_change().dropna()
    if len(returns) > 30:
        outliers = returns[returns.abs() > 0.50]
        if not outliers.empty:
            issues.append(
                QualityIssue(symbol, "extreme_return", f"{len(outliers)} daily moves > 50% (unadjusted split/data error?)")
            )

    return issues


def check_index_bars(index_df: pd.DataFrame, as_of: date, max_staleness_days: int = 4) -> list[QualityIssue]:
    if index_df.empty:
        return [QualityIssue("", "index_bar_missing_or_stale", "no index bars returned")]
    latest = index_df["date"].dt.date.max()
    if (as_of - latest) > timedelta(days=max_staleness_days):
        return [QualityIssue("", "index_bar_missing_or_stale", f"latest index bar {latest} is stale as of {as_of}")]
    return []


def build_report(as_of: date, index_issues: list[QualityIssue], symbol_issues: dict[str, list[QualityIssue]]) -> QualityReport:
    all_issues = list(index_issues)
    for issues in symbol_issues.values():
        all_issues.extend(issues)
    return QualityReport(as_of=as_of, issues=all_issues)
