"""
analytics.py — Framework-free data-quality tests and AI-query reconciliation.

No testing/DQ framework (no dbt, no Great Expectations) is used; the dbt-style
checks are implemented from scratch over pandas DataFrames so the logic is fully
visible and unit-testable.

Two capabilities:
  1. A small suite of dbt-style data-quality tests:
       row_count, not_null, unique, accepted_range, accepted_values, freshness
     Each returns a structured result dict (status, passed/failed counts, detail).
  2. Reconciliation of an AI-drafted query's output against a trusted baseline,
     segment by segment, flagging material divergences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd


# --------------------------------------------------------------------------- #
# Test result container
# --------------------------------------------------------------------------- #
@dataclass
class TestResult:
    test: str                 # test type, e.g. "not_null"
    column: str               # column (or "*" for table-level)
    status: str               # "pass" or "fail"
    failing_rows: int         # count of offending rows
    total_rows: int           # rows evaluated
    detail: str = ""          # human-readable note

    def as_dict(self) -> dict:
        return {
            "test": self.test,
            "column": self.column,
            "status": self.status,
            "failing_rows": self.failing_rows,
            "total_rows": self.total_rows,
            "detail": self.detail,
        }


# --------------------------------------------------------------------------- #
# Individual dbt-style tests
# --------------------------------------------------------------------------- #
def test_row_count(df: pd.DataFrame, min_rows: int) -> TestResult:
    """Fail if the table has fewer than `min_rows` rows."""
    n = len(df)
    passed = n >= min_rows
    return TestResult(
        test="row_count",
        column="*",
        status="pass" if passed else "fail",
        failing_rows=0 if passed else 1,
        total_rows=n,
        detail=f"expected >= {min_rows:,} rows, found {n:,}",
    )


def test_not_null(df: pd.DataFrame, column: str) -> TestResult:
    """Fail for every row where `column` is null."""
    nulls = int(df[column].isna().sum())
    return TestResult(
        test="not_null",
        column=column,
        status="pass" if nulls == 0 else "fail",
        failing_rows=nulls,
        total_rows=len(df),
        detail=f"{nulls} null value(s)",
    )


def test_unique(df: pd.DataFrame, column: str) -> TestResult:
    """Fail for every duplicated value in `column`."""
    dup_mask = df[column].duplicated(keep=False)
    dup_rows = int(dup_mask.sum())
    distinct_dups = int(df.loc[dup_mask, column].nunique())
    return TestResult(
        test="unique",
        column=column,
        status="pass" if dup_rows == 0 else "fail",
        failing_rows=dup_rows,
        total_rows=len(df),
        detail=f"{dup_rows} row(s) across {distinct_dups} duplicated value(s)",
    )


def test_accepted_range(
    df: pd.DataFrame, column: str, min_value: float, max_value: float
) -> TestResult:
    """Fail for non-null rows where `column` is outside [min_value, max_value]."""
    col = df[column]
    mask = col.notna() & ((col < min_value) | (col > max_value))
    bad = int(mask.sum())
    return TestResult(
        test="accepted_range",
        column=column,
        status="pass" if bad == 0 else "fail",
        failing_rows=bad,
        total_rows=len(df),
        detail=f"{bad} value(s) outside [{min_value}, {max_value}]",
    )


def test_accepted_values(
    df: pd.DataFrame, column: str, accepted: Iterable
) -> TestResult:
    """Fail for non-null rows whose `column` value is not in `accepted`."""
    accepted = set(accepted)
    col = df[column]
    mask = col.notna() & ~col.isin(accepted)
    bad = int(mask.sum())
    offenders = sorted(map(str, df.loc[mask, column].unique()))
    return TestResult(
        test="accepted_values",
        column=column,
        status="pass" if bad == 0 else "fail",
        failing_rows=bad,
        total_rows=len(df),
        detail=(
            f"{bad} row(s) with unexpected value(s): {', '.join(offenders)}"
            if bad
            else "all values accepted"
        ),
    )


def test_freshness(
    df: pd.DataFrame, column: str, as_of: pd.Timestamp, max_age_days: int
) -> TestResult:
    """
    Fail if the most recent timestamp in `column` is older than `max_age_days`
    relative to `as_of`.
    """
    latest = pd.to_datetime(df[column]).max()
    age_days = (pd.Timestamp(as_of) - latest).days
    passed = age_days <= max_age_days
    return TestResult(
        test="freshness",
        column=column,
        status="pass" if passed else "fail",
        failing_rows=0 if passed else 1,
        total_rows=len(df),
        detail=f"newest row is {age_days} day(s) old (threshold {max_age_days})",
    )


# --------------------------------------------------------------------------- #
# Suite runner
# --------------------------------------------------------------------------- #
@dataclass
class SuiteSummary:
    results: list = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == "pass")

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_pct(self) -> float:
        return round(100.0 * self.passed / self.total, 1) if self.total else 0.0

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([r.as_dict() for r in self.results])

    def failures(self) -> list:
        return [r for r in self.results if r.status == "fail"]


def run_default_suite(
    df: pd.DataFrame, as_of: pd.Timestamp = pd.Timestamp("2026-10-07")
) -> SuiteSummary:
    """
    Run a representative suite against the synthetic shifts table.
    Returns a SuiteSummary with one TestResult per check.
    """
    results = [
        test_row_count(df, min_rows=1000),
        test_not_null(df, "shift_id"),
        test_not_null(df, "hourly_rate"),
        test_not_null(df, "gross_pay"),
        test_unique(df, "shift_id"),
        test_accepted_range(df, "hourly_rate", 15.0, 60.0),
        test_accepted_range(df, "rating", 1.0, 5.0),
        test_accepted_values(df, "status", ["completed", "cancelled", "no_show"]),
        test_freshness(df, "shift_date", as_of=as_of, max_age_days=2),
    ]
    return SuiteSummary(results=results)


# --------------------------------------------------------------------------- #
# AI query vs trusted baseline reconciliation
# --------------------------------------------------------------------------- #
def reconcile(
    baseline: pd.DataFrame,
    ai_result: pd.DataFrame,
    segment: str,
    baseline_value: str,
    ai_value: str,
    tolerance_pct: float = 0.5,
) -> pd.DataFrame:
    """
    Compare an AI-generated aggregate against a trusted baseline, segment by segment.

    Returns a DataFrame with one row per segment:
        segment, baseline_value, ai_value, abs_diff, pct_diff, flag

    A segment is flagged "DIVERGENT" when |pct_diff| exceeds `tolerance_pct`,
    and "MISSING" when it appears in only one of the two result sets.
    """
    merged = baseline.merge(ai_result, on=segment, how="outer", indicator=True)

    rows = []
    for _, r in merged.iterrows():
        b = r.get(baseline_value)
        a = r.get(ai_value)
        indicator = r["_merge"]

        if indicator != "both":
            flag = "MISSING"
            abs_diff = float("nan")
            pct_diff = float("nan")
        else:
            abs_diff = round(float(a) - float(b), 2)
            pct_diff = round(100.0 * abs_diff / b, 2) if b else float("inf")
            flag = "OK" if abs(pct_diff) <= tolerance_pct else "DIVERGENT"

        rows.append(
            {
                segment: r[segment],
                baseline_value: None if pd.isna(b) else round(float(b), 2),
                ai_value: None if pd.isna(a) else round(float(a), 2),
                "abs_diff": abs_diff,
                "pct_diff": pct_diff,
                "flag": flag,
            }
        )

    out = pd.DataFrame(rows).sort_values(segment).reset_index(drop=True)
    return out


def reconciliation_summary(recon: pd.DataFrame) -> dict:
    """Headline numbers for the reconciliation view."""
    n = len(recon)
    divergent = int((recon["flag"] == "DIVERGENT").sum())
    missing = int((recon["flag"] == "MISSING").sum())
    matched = n - divergent - missing

    total_base = recon["baseline_gross_pay"].sum(skipna=True) if "baseline_gross_pay" in recon else 0
    total_ai = recon["ai_gross_pay"].sum(skipna=True) if "ai_gross_pay" in recon else 0
    overstatement_pct = (
        round(100.0 * (total_ai - total_base) / total_base, 2) if total_base else 0.0
    )

    return {
        "segments": n,
        "matched": matched,
        "divergent": divergent,
        "missing": missing,
        "total_baseline": round(float(total_base), 2),
        "total_ai": round(float(total_ai), 2),
        "overstatement_pct": overstatement_pct,
    }
