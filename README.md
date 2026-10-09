# AI Query QA & Data-Quality Monitor

**Author: Leo Chan — [github.com/GoldenCrate](https://github.com/GoldenCrate)**

A Streamlit app that puts a guardrail between an AI assistant and the numbers a
business acts on. Before an AI-drafted SQL result is trusted, it is (1) run
through a **dbt-style data-quality test suite** on the source table, and
(2) **reconciled against a known-correct baseline**, segment by segment, so you
catch where the AI's answer quietly diverges from the source of truth.

Built as a portfolio piece for the **Business Operations Associate, AI & Automation**
workflow — the day-to-day of validating AI-generated queries against trusted data.

> ### ⚠️ Synthetic data disclaimer
> **Every dataset in this project is 100% synthetic**, generated locally with a
> fixed random seed (`data_gen.py`). It does **not** represent Instawork or any
> real company, worker, shift, or financial figure. It exists solely to
> demonstrate data-quality and reconciliation logic.

---

## What it does

The app has five views, each ending in a plain-language **"So what / recommendation."**

1. **Overview (KPIs)** — datasets monitored, % of tests passing, AI-query checks
   run, and discrepancies found, with the headline "AI answer vs. trusted total."
2. **Data-Quality Test Suite** — runs six dbt-style test types on a synthetic
   `shifts` table and lists every failure:
   `row_count`, `not_null`, `unique`, `accepted_range`, `accepted_values`, `freshness`.
3. **AI Query vs Baseline** — compares an AI-drafted "gross pay by region" query
   against the finance-trusted baseline and flags each divergent segment, with an
   adjustable tolerance.
4. **Quality Trend** — 30-day history of the pass rate, highlighting a dip-and-recovery.
5. **So what / recommendation** — surfaced on every view.

### The deliberate "AI mistake"

The synthetic AI query makes two realistic errors: it **drops the
`status = 'completed'` filter** and runs against an **un-deduplicated source
table**. The result looks plausible but overstates total gross pay by ~20%. The
reconciliation view is what catches it.

---

## Data-quality tests (framework-free)

`analytics.py` implements the checks from scratch (no dbt, no Great Expectations),
so the logic is fully visible and unit-tested:

| Test | Fails when |
|------|-----------|
| `row_count` | table has fewer than N rows |
| `not_null` | a column contains nulls |
| `unique` | a column has duplicate values |
| `accepted_range` | numeric values fall outside `[min, max]` |
| `accepted_values` | a column holds values outside an allowed set |
| `freshness` | the newest timestamp is older than the threshold |

---

## Project structure

```
app.py              # Multi-view Streamlit UI (Knaflic-style charts)
analytics.py        # Framework-free DQ tests + AI-vs-baseline reconciliation
data_gen.py         # Synthetic data generator (fixed seed, injected DQ issues)
test_analytics.py   # pytest suite (18 tests)
requirements.txt
README.md
.gitignore
```

## Run it locally

```bash
pip install -r requirements.txt

# regenerate / inspect the synthetic data
python data_gen.py

# run the tests
pytest -q

# launch the app
streamlit run app.py
```

## Design notes

Charts follow Cole Nussbaumer Knaflic's *Storytelling with Data*: gray carries
context, a single accent color is reserved for the problem (divergence, failures,
the quality dip), values are labeled directly, and every view states its takeaway
in words rather than leaving the reader to decode the chart.
