"""
test_analytics.py — pytest suite for the framework-free DQ tests and reconciliation.

Run with:  pytest -q
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import analytics as a
import data_gen as dg


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def ops():
    return dg.generate_operational()


@pytest.fixture
def clean():
    return dg.generate_clean()


# --------------------------------------------------------------------------- #
# Individual tests
# --------------------------------------------------------------------------- #
def test_row_count_pass(clean):
    r = a.test_row_count(clean, min_rows=1000)
    assert r.status == "pass"


def test_row_count_fail():
    df = pd.DataFrame({"x": [1, 2, 3]})
    r = a.test_row_count(df, min_rows=10)
    assert r.status == "fail"
    assert r.total_rows == 3


def test_not_null_detects_injected_nulls(ops):
    r = a.test_not_null(ops, "hourly_rate")
    assert r.status == "fail"
    assert r.failing_rows == int(ops["hourly_rate"].isna().sum())
    assert r.failing_rows > 0


def test_not_null_clean_passes(clean):
    assert a.test_not_null(clean, "hourly_rate").status == "pass"


def test_unique_detects_duplicates(ops):
    r = a.test_unique(ops, "shift_id")
    assert r.status == "fail"
    # 12 duplicate rows were appended -> 24 rows share a duplicated id.
    assert r.failing_rows == 24


def test_unique_clean_passes(clean):
    assert a.test_unique(clean, "shift_id").status == "pass"


def test_accepted_range_flags_high_rates(ops):
    r = a.test_accepted_range(ops, "hourly_rate", 15.0, 60.0)
    assert r.status == "fail"
    assert r.failing_rows == int((ops["hourly_rate"] > 60.0).sum())


def test_accepted_range_ignores_nulls():
    df = pd.DataFrame({"v": [10.0, np.nan, 50.0]})
    r = a.test_accepted_range(df, "v", 0.0, 100.0)
    assert r.status == "pass"  # null is not a range violation


def test_accepted_values_flags_bad_status(ops):
    r = a.test_accepted_values(ops, "status", ["completed", "cancelled", "no_show"])
    assert r.status == "fail"
    assert "COMPLETE" in r.detail


def test_accepted_values_clean_passes(clean):
    r = a.test_accepted_values(clean, "status", ["completed", "cancelled", "no_show"])
    assert r.status == "pass"


def test_freshness_fails_on_stale_data(ops):
    # Operational data is aged 6 days; threshold of 2 days must fail.
    r = a.test_freshness(ops, "shift_date", as_of=pd.Timestamp("2026-10-07"), max_age_days=2)
    assert r.status == "fail"


def test_freshness_passes_when_recent():
    df = pd.DataFrame({"d": pd.to_datetime(["2026-10-06", "2026-10-07"])})
    r = a.test_freshness(df, "d", as_of=pd.Timestamp("2026-10-07"), max_age_days=2)
    assert r.status == "pass"


# --------------------------------------------------------------------------- #
# Suite runner
# --------------------------------------------------------------------------- #
def test_suite_runs_all_checks(ops):
    s = a.run_default_suite(ops)
    assert s.total == 9
    assert s.failed >= 1
    assert 0 <= s.pass_pct <= 100
    frame = s.to_frame()
    assert set(["test", "column", "status"]).issubset(frame.columns)


def test_suite_clean_has_fewer_failures(clean, ops):
    clean_summary = a.run_default_suite(clean)
    ops_summary = a.run_default_suite(ops)
    assert clean_summary.failed < ops_summary.failed


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #
def test_reconcile_flags_divergence():
    baseline = dg.trusted_baseline()
    ai = dg.ai_query_result()
    recon = a.reconcile(
        baseline, ai, segment="region",
        baseline_value="baseline_gross_pay", ai_value="ai_gross_pay",
        tolerance_pct=0.5,
    )
    assert len(recon) == baseline["region"].nunique()
    # The AI query dropped the completed-status filter -> it must overstate.
    assert (recon["flag"] == "DIVERGENT").sum() >= 1
    assert (recon["ai_gross_pay"] >= recon["baseline_gross_pay"]).all()


def test_reconcile_identical_is_ok():
    baseline = dg.trusted_baseline()
    # Compare the baseline against itself -> everything within tolerance.
    ai = baseline.rename(columns={"baseline_gross_pay": "ai_gross_pay"})
    recon = a.reconcile(
        baseline, ai, segment="region",
        baseline_value="baseline_gross_pay", ai_value="ai_gross_pay",
    )
    assert (recon["flag"] == "OK").all()


def test_reconcile_detects_missing_segment():
    baseline = pd.DataFrame({"region": ["A", "B"], "baseline_gross_pay": [100.0, 200.0]})
    ai = pd.DataFrame({"region": ["A"], "ai_gross_pay": [100.0]})
    recon = a.reconcile(
        baseline, ai, segment="region",
        baseline_value="baseline_gross_pay", ai_value="ai_gross_pay",
    )
    assert (recon["flag"] == "MISSING").sum() == 1


def test_reconciliation_summary_overstatement():
    baseline = dg.trusted_baseline()
    ai = dg.ai_query_result()
    recon = a.reconcile(
        baseline, ai, segment="region",
        baseline_value="baseline_gross_pay", ai_value="ai_gross_pay",
    )
    summary = a.reconciliation_summary(recon)
    assert summary["segments"] == len(recon)
    assert summary["overstatement_pct"] > 0  # AI result inflates the total
    assert summary["total_ai"] > summary["total_baseline"]
