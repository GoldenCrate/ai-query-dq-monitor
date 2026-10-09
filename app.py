"""
app.py — AI Query QA & Data-Quality Monitor (Streamlit)

A portfolio demo for a Business Operations (AI & Automation) workflow: before an
AI-drafted SQL result is trusted, it is (a) run through a dbt-style data-quality
test suite and (b) reconciled against a known-correct baseline, segment by segment.

Author: Leo Chan — github.com/GoldenCrate
ALL DATA IS SYNTHETIC. Nothing here represents Instawork or any real data.

Charting follows Cole Nussbaumer Knaflic's "Storytelling with Data":
muted gray context, a single accent reserved for what matters, direct labels,
no chartjunk, and a takeaway in words next to every visual.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import analytics as A
import data_gen as dg

# --------------------------------------------------------------------------- #
# Knaflic palette: gray is context, one accent carries the message.
# --------------------------------------------------------------------------- #
GRAY = "#B3B3B3"
DARK = "#4D4D4D"
ACCENT = "#C44E52"   # reserved for "attention / problem"
GOOD = "#55A868"     # reserved for "passing / trusted"
BLUE = "#4C78A8"

AS_OF = pd.Timestamp("2026-10-07")

st.set_page_config(
    page_title="AI Query QA & Data-Quality Monitor",
    page_icon="check",
    layout="wide",
)


@st.cache_data
def load_data():
    return {
        "ops": dg.generate_operational(),
        "clean": dg.generate_clean(),
        "baseline": dg.trusted_baseline(),
        "ai": dg.ai_query_result(),
        "history": dg.dq_history(),
    }


D = load_data()


def so_what(text: str):
    """Render a consistent 'So what / recommendation' callout."""
    st.markdown(
        f"""
        <div style="border-left:4px solid {ACCENT};background:#faf1f1;
                    padding:0.75rem 1rem;border-radius:4px;margin-top:0.5rem;color:#222;">
        <strong>So what →</strong> {text}
        </div>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
st.sidebar.title("AI Query QA Monitor")
st.sidebar.caption("Validate AI-drafted SQL against trusted source data.")
view = st.sidebar.radio(
    "View",
    [
        "Overview (KPIs)",
        "Data-Quality Test Suite",
        "AI Query vs Baseline",
        "Quality Trend",
    ],
)
st.sidebar.markdown("---")
st.sidebar.info(
    "**100% synthetic data.** Fixed seed; no real company, worker, or shift. "
    "Built by Leo Chan — github.com/GoldenCrate."
)

# Shared suite run (used by several views)
suite = A.run_default_suite(D["ops"], as_of=AS_OF)
recon = A.reconcile(
    D["baseline"], D["ai"], segment="region",
    baseline_value="baseline_gross_pay", ai_value="ai_gross_pay",
    tolerance_pct=0.5,
)
recon_summary = A.reconciliation_summary(recon)


# =========================================================================== #
# VIEW 1 — OVERVIEW / KPIs
# =========================================================================== #
if view == "Overview (KPIs)":
    st.title("AI Query QA & Data-Quality Monitor")
    st.caption(
        "A guardrail layer for AI-assisted analytics: test the source data, then "
        "reconcile the AI's answer against a trusted baseline before anyone acts on it."
    )

    datasets_monitored = 1
    discrepancies = recon_summary["divergent"] + recon_summary["missing"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Datasets monitored", datasets_monitored)
    c2.metric("Tests passing", f"{suite.pass_pct:.0f}%", f"{suite.failed} failing")
    c3.metric("AI-query checks run", len(recon))
    c4.metric("Discrepancies found", discrepancies, delta_color="inverse")

    st.markdown("---")
    left, right = st.columns([3, 2])

    with left:
        st.subheader("Where the data-quality tests stand")
        frame = suite.to_frame()
        frame["label"] = frame["test"] + " · " + frame["column"]
        frame["fails"] = frame["failing_rows"].where(frame["status"] == "fail", 0)
        chart = (
            alt.Chart(frame)
            .mark_bar()
            .encode(
                x=alt.X("fails:Q", title="Failing rows"),
                y=alt.Y("label:N", sort="-x", title=None),
                color=alt.condition(
                    alt.datum.status == "fail",
                    alt.value(ACCENT),
                    alt.value(GRAY),
                ),
                tooltip=["test", "column", "status", "failing_rows", "detail"],
            )
            .properties(height=320)
        )
        st.altair_chart(chart, width='stretch')

    with right:
        st.subheader("AI answer vs. trusted total")
        tot = pd.DataFrame(
            {
                "source": ["Trusted baseline", "AI query"],
                "value": [recon_summary["total_baseline"], recon_summary["total_ai"]],
            }
        )
        bar = (
            alt.Chart(tot)
            .mark_bar()
            .encode(
                x=alt.X("source:N", title=None, sort=["Trusted baseline", "AI query"]),
                y=alt.Y("value:Q", title="Total gross pay ($)"),
                color=alt.condition(
                    alt.datum.source == "AI query",
                    alt.value(ACCENT),
                    alt.value(GOOD),
                ),
                tooltip=["source", alt.Tooltip("value:Q", format="$,.0f")],
            )
            .properties(height=320)
        )
        st.altair_chart(bar, width='stretch')

    so_what(
        f"The AI-drafted query overstates total gross pay by "
        f"<strong>{recon_summary['overstatement_pct']:.1f}%</strong> "
        f"(${recon_summary['total_ai']:,.0f} vs. ${recon_summary['total_baseline']:,.0f}) and "
        f"the source table is failing <strong>{suite.failed}</strong> of {suite.total} "
        f"quality tests. Do not ship this number to finance until the "
        f"completed-status filter is restored and the source defects are fixed."
    )


# =========================================================================== #
# VIEW 2 — DATA-QUALITY TEST SUITE
# =========================================================================== #
elif view == "Data-Quality Test Suite":
    st.title("Data-Quality Test Suite")
    st.caption(
        "dbt-style tests run from scratch on the synthetic `shifts` table: row count, "
        "not-null, uniqueness, accepted-range, accepted-values, and freshness."
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Tests run", suite.total)
    c2.metric("Passing", f"{suite.pass_pct:.0f}%")
    c3.metric("Failing", suite.failed, delta_color="inverse")

    st.markdown("---")
    frame = suite.to_frame()

    st.subheader("Results")
    def _style(row):
        color = "#f7d9d9" if row["status"] == "fail" else "#e2efe0"
        return [f"background-color:{color}"] * len(row)

    st.dataframe(
        frame[["test", "column", "status", "failing_rows", "total_rows", "detail"]]
        .style.apply(_style, axis=1),
        width='stretch',
        hide_index=True,
    )

    st.subheader("Failures, worst first")
    fails = frame[frame["status"] == "fail"].sort_values("failing_rows", ascending=False)
    if len(fails):
        chart = (
            alt.Chart(fails)
            .mark_bar(color=ACCENT)
            .encode(
                x=alt.X("failing_rows:Q", title="Failing rows"),
                y=alt.Y("test:N", sort="-x", title=None),
                tooltip=["test", "column", "failing_rows", "detail"],
            )
            .properties(height=260)
        )
        text = chart.mark_text(align="left", dx=3, color=DARK).encode(text="failing_rows:Q")
        st.altair_chart(chart + text, width='stretch')

        top = fails.iloc[0]
        so_what(
            f"The largest single failure is <strong>{top['test']}</strong> on "
            f"<strong>{top['column']}</strong> ({int(top['failing_rows'])} rows). "
            f"Uniqueness and not-null breaks mean any downstream SUM or COUNT — "
            f"including an AI's — will be wrong. Quarantine the "
            f"{suite.failed} failing checks before the table feeds a report."
        )
    else:
        st.success("All tests passing.")


# =========================================================================== #
# VIEW 3 — AI QUERY VS BASELINE
# =========================================================================== #
elif view == "AI Query vs Baseline":
    st.title("AI Query vs Trusted Baseline")
    st.caption(
        "An AI assistant drafted SQL for 'total gross pay by region.' We reconcile it "
        "against the finance-trusted baseline, segment by segment, and flag divergence."
    )

    tol = st.slider("Divergence tolerance (|%| difference)", 0.0, 10.0, 0.5, 0.5)
    recon_v = A.reconcile(
        D["baseline"], D["ai"], segment="region",
        baseline_value="baseline_gross_pay", ai_value="ai_gross_pay",
        tolerance_pct=tol,
    )
    summ = A.reconciliation_summary(recon_v)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Segments checked", summ["segments"])
    c2.metric("Within tolerance", summ["matched"])
    c3.metric("Divergent", summ["divergent"], delta_color="inverse")
    c4.metric("Total overstatement", f"{summ['overstatement_pct']:.1f}%", delta_color="inverse")

    st.markdown("---")
    st.subheader("Baseline vs AI by region")

    long = recon_v.melt(
        id_vars=["region", "flag"],
        value_vars=["baseline_gross_pay", "ai_gross_pay"],
        var_name="source",
        value_name="gross_pay",
    )
    long["source"] = long["source"].map(
        {"baseline_gross_pay": "Trusted baseline", "ai_gross_pay": "AI query"}
    )
    grouped = (
        alt.Chart(long)
        .mark_bar()
        .encode(
            x=alt.X("source:N", title=None, sort=["Trusted baseline", "AI query"], axis=alt.Axis(labels=False)),
            y=alt.Y("gross_pay:Q", title="Gross pay ($)"),
            color=alt.Color(
                "source:N",
                scale=alt.Scale(
                    domain=["Trusted baseline", "AI query"], range=[GOOD, ACCENT]
                ),
                legend=alt.Legend(title=None, orient="top"),
            ),
            column=alt.Column("region:N", title=None, header=alt.Header(labelOrient="bottom")),
            tooltip=["region", "source", alt.Tooltip("gross_pay:Q", format="$,.0f")],
        )
        .properties(height=260, width=90)
    )
    st.altair_chart(grouped)

    st.subheader("Reconciliation detail")
    def _flag_style(row):
        colors = {"DIVERGENT": "#f7d9d9", "MISSING": "#fff3cd", "OK": "#e2efe0"}
        return [f"background-color:{colors.get(row['flag'], '')}"] * len(row)

    st.dataframe(
        recon_v.style.apply(_flag_style, axis=1).format(
            {"baseline_gross_pay": "${:,.0f}", "ai_gross_pay": "${:,.0f}",
             "abs_diff": "{:,.0f}", "pct_diff": "{:+.1f}%"}
        ),
        width='stretch',
        hide_index=True,
    )

    worst = recon_v.loc[recon_v["pct_diff"].abs().idxmax()] if len(recon_v) else None
    if worst is not None:
        so_what(
            f"Every region is overstated because the AI dropped the "
            f"<code>status = 'completed'</code> filter; the worst is "
            f"<strong>{worst['region']}</strong> at "
            f"<strong>{worst['pct_diff']:+.1f}%</strong> "
            f"(${worst['abs_diff']:,.0f}). Send the AI back with the filter and the "
            f"deduped source table; a plausible-looking total was off by "
            f"<strong>{summ['overstatement_pct']:.1f}%</strong> company-wide."
        )


# =========================================================================== #
# VIEW 4 — QUALITY TREND
# =========================================================================== #
elif view == "Quality Trend":
    st.title("Data-Quality Trend")
    st.caption("Share of tests passing per day over the last 30 days (synthetic history).")

    hist = D["history"].copy()
    latest = hist["pass_pct"].iloc[-1]
    low = hist["pass_pct"].min()
    low_date = hist.loc[hist["pass_pct"].idxmin(), "date"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Latest pass rate", f"{latest:.1f}%")
    c2.metric("30-day low", f"{low:.1f}%")
    c3.metric("Avg AI checks / day", f"{hist['ai_checks_run'].mean():.0f}")

    st.markdown("---")

    base = alt.Chart(hist).encode(x=alt.X("date:T", title=None))
    line = base.mark_line(color=GRAY, strokeWidth=2).encode(
        y=alt.Y("pass_pct:Q", title="Tests passing (%)", scale=alt.Scale(domain=[70, 100]))
    )
    # Accent only the dip, to draw the eye to the story.
    dip = (
        alt.Chart(hist[hist["pass_pct"] < 90])
        .mark_point(color=ACCENT, size=60, filled=True)
        .encode(x="date:T", y="pass_pct:Q",
                tooltip=["date:T", alt.Tooltip("pass_pct:Q", format=".1f")])
    )
    rule = alt.Chart(pd.DataFrame({"y": [95]})).mark_rule(
        color=DARK, strokeDash=[4, 4]
    ).encode(y="y:Q")
    rule_text = rule.mark_text(
        text="95% target", align="left", dx=5, dy=-6, color=DARK
    ).encode(x=alt.value(5))
    st.altair_chart((line + dip + rule + rule_text).properties(height=360),
                    width='stretch')

    so_what(
        f"Quality dipped to <strong>{low:.1f}%</strong> around "
        f"<strong>{low_date:%b %d}</strong> — a classic post-deploy regression — then "
        f"recovered to {latest:.1f}%. Wire this suite into CI so the next regression "
        f"blocks the pipeline instead of surfacing in a finance deck."
    )
