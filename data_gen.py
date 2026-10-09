"""
data_gen.py — Synthetic data generator for the AI Query QA & Data-Quality Monitor.

EVERYTHING produced here is SYNTHETIC and generated with a fixed random seed.
It does NOT represent Instawork or any real company, worker, or shift. It exists
only to demonstrate data-quality testing and AI-query reconciliation logic.

The generator produces three objects:
  1. operational dataset  -> a "shifts" table for a fictional gig-work marketplace,
                             with DELIBERATELY injected data-quality issues.
  2. trusted baseline     -> a known-correct aggregate of gross pay by region,
                             computed from a CLEAN copy of the data (the "source of truth").
  3. ai query result      -> an aggregate that mimics an AI-drafted SQL query which is
                             *slightly wrong* (a join/filter mistake), so the reconciliation
                             view has real divergences to catch.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SEED = 42

REGIONS = ["Bay Area", "Los Angeles", "Chicago", "Austin", "Seattle"]
ROLES = ["Server", "Bartender", "Prep Cook", "Warehouse", "Event Staff"]
VALID_STATUSES = ["completed", "cancelled", "no_show"]

# Business rule: hourly rate must sit within this band for these synthetic roles.
RATE_MIN = 15.0
RATE_MAX = 60.0

N_SHIFTS = 1200


def _base_frame(seed: int = SEED) -> pd.DataFrame:
    """Build a clean synthetic shifts table (the source of truth)."""
    rng = np.random.default_rng(seed)

    shift_ids = np.arange(100000, 100000 + N_SHIFTS)
    regions = rng.choice(REGIONS, size=N_SHIFTS, p=[0.30, 0.25, 0.20, 0.15, 0.10])
    roles = rng.choice(ROLES, size=N_SHIFTS)
    worker_ids = rng.integers(5000, 5300, size=N_SHIFTS)

    hourly_rate = np.round(rng.uniform(RATE_MIN, RATE_MAX, size=N_SHIFTS), 2)
    hours_worked = np.round(rng.uniform(2.0, 10.0, size=N_SHIFTS), 2)
    gross_pay = np.round(hourly_rate * hours_worked, 2)

    status = rng.choice(VALID_STATUSES, size=N_SHIFTS, p=[0.82, 0.12, 0.06])
    rating = np.round(rng.uniform(3.0, 5.0, size=N_SHIFTS), 1)

    # 90 days of history ending "today" so freshness tests have something to chew on.
    start = pd.Timestamp("2026-07-10")
    day_offsets = rng.integers(0, 90, size=N_SHIFTS)
    shift_date = start + pd.to_timedelta(day_offsets, unit="D")

    df = pd.DataFrame(
        {
            "shift_id": shift_ids,
            "shift_date": shift_date,
            "region": regions,
            "role": roles,
            "worker_id": worker_ids,
            "hourly_rate": hourly_rate,
            "hours_worked": hours_worked,
            "gross_pay": gross_pay,
            "status": status,
            "rating": rating,
        }
    )
    return df


def generate_clean() -> pd.DataFrame:
    """The trusted, clean version of the operational dataset."""
    return _base_frame()


def generate_operational() -> pd.DataFrame:
    """
    The operational dataset AS INGESTED — clean data with realistic DQ defects
    injected so the test suite has real failures to surface.

    Injected issues (all deterministic under the fixed seed):
      * not-null     : ~18 rows have a missing hourly_rate
      * uniqueness   : ~12 shift_ids are duplicated
      * accepted-range: ~9 rows have an hourly_rate above the $60 band
      * accepted-values: ~7 rows have an invalid status string
      * freshness    : the newest shift_date is pushed ~6 days into the past
    """
    rng = np.random.default_rng(SEED + 1)
    df = generate_clean().copy()

    # not-null violations on hourly_rate
    null_idx = rng.choice(df.index, size=18, replace=False)
    df.loc[null_idx, "hourly_rate"] = np.nan

    # accepted-range violations (rate above the band)
    range_idx = rng.choice(df.index, size=9, replace=False)
    df.loc[range_idx, "hourly_rate"] = np.round(rng.uniform(70, 95, size=9), 2)

    # accepted-values violations on status
    bad_status_idx = rng.choice(df.index, size=7, replace=False)
    df.loc[bad_status_idx, "status"] = "COMPLETE"  # wrong casing / unknown value

    # uniqueness violations: duplicate 12 existing rows (same shift_id reappears)
    dup_rows = df.sample(n=12, random_state=SEED + 2).copy()
    df = pd.concat([df, dup_rows], ignore_index=True)

    # freshness: age the whole table so the newest shift is ~6 days stale vs "today"
    df["shift_date"] = df["shift_date"] - pd.Timedelta(days=6)

    return df.reset_index(drop=True)


def trusted_baseline() -> pd.DataFrame:
    """
    Source-of-truth aggregate: total gross pay by region for COMPLETED shifts only,
    computed from the clean table. This is the number a finance report would trust.
    """
    clean = generate_clean()
    completed = clean[clean["status"] == "completed"]
    out = (
        completed.groupby("region", as_index=False)["gross_pay"]
        .sum()
        .rename(columns={"gross_pay": "baseline_gross_pay"})
    )
    out["baseline_gross_pay"] = out["baseline_gross_pay"].round(2)
    return out.sort_values("region").reset_index(drop=True)


def ai_query_result() -> pd.DataFrame:
    """
    Mimics an AI-DRAFTED SQL query answering "total gross pay by region".

    The AI made two subtle, common mistakes:
      * it forgot the `status = 'completed'` filter (counts cancelled + no_show too),
        inflating most regions; and
      * it is run against the operational table, so a couple of regions are also
        distorted by the injected duplicate rows.

    The result is close enough to look right at a glance but diverges from the
    trusted baseline once you reconcile segment by segment.
    """
    ops = generate_operational()
    # BUG: no status filter -> includes cancelled / no_show / bad-status rows.
    out = (
        ops.groupby("region", as_index=False)["gross_pay"]
        .sum()
        .rename(columns={"gross_pay": "ai_gross_pay"})
    )
    out["ai_gross_pay"] = out["ai_gross_pay"].round(2)
    return out.sort_values("region").reset_index(drop=True)


def dq_history(days: int = 30) -> pd.DataFrame:
    """
    Synthetic daily history of the data-quality score (% of tests passing),
    with a visible dip + recovery so the trend view tells a story.
    """
    rng = np.random.default_rng(SEED + 3)
    dates = pd.date_range(end=pd.Timestamp("2026-10-07"), periods=days, freq="D")

    # Start healthy, dip in the middle (a bad pipeline deploy), then recover.
    base = np.linspace(96, 97, days)
    dip = -8 * np.exp(-((np.arange(days) - days * 0.55) ** 2) / (2 * (days * 0.08) ** 2))
    noise = rng.normal(0, 0.6, size=days)
    score = np.clip(base + dip + noise, 70, 100).round(1)

    tests_run = rng.integers(55, 70, size=days)
    ai_checks = rng.integers(8, 20, size=days)

    return pd.DataFrame(
        {
            "date": dates,
            "pass_pct": score,
            "tests_run": tests_run,
            "ai_checks_run": ai_checks,
        }
    )


if __name__ == "__main__":
    ops = generate_operational()
    base = trusted_baseline()
    ai = ai_query_result()
    hist = dq_history()

    print("SYNTHETIC DATA ONLY — not real Instawork data.\n")
    print(f"operational shifts : {len(ops):,} rows, {ops['shift_id'].nunique():,} unique shift_ids")
    print(f"null hourly_rate   : {int(ops['hourly_rate'].isna().sum())} rows")
    print(f"out-of-range rates : {int((ops['hourly_rate'] > RATE_MAX).sum())} rows")
    print(f"bad status values  : {int((~ops['status'].isin(VALID_STATUSES)).sum())} rows")
    print(f"duplicate shift_ids: {int(len(ops) - ops['shift_id'].nunique())}\n")
    print("Trusted baseline (gross pay by region, completed only):")
    print(base.to_string(index=False))
    print("\nAI query result (gross pay by region, buggy):")
    print(ai.to_string(index=False))
    print(f"\nDQ history: {len(hist)} days, latest pass% = {hist['pass_pct'].iloc[-1]}")
