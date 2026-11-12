# Contact Center ETL Pipeline

An end-to-end data pipeline for a mobile operator's contact center, built with **Python, pandas and PostgreSQL**.
It takes a dirty CSV export of calls, cleans and validates it, loads it into a normalized PostgreSQL schema,
runs data-quality checks, and produces an Excel report from SQL queries with window functions.

> **About the data.** The dataset is **synthetic**: `src/generate_data.py` creates six months of calls
> (about 62,000) and deliberately adds the problems real exports have — duplicates, two date formats,
> hand-typed categories, impossible values, broken references. No real customer data is used.

## What the pipeline does

```
data/raw/*.csv ──extract──> staging.*  ──transform──> clean rows ──load──> core.dim_*, core.fact_call
   (dirty text)             (raw text)    (pandas)    rejected rows ─────> core.rejected_call (with reason)
                                                                                 │
                                              dq.check_result <──quality checks──┤
                                              reports/*.xlsx  <──SQL analytics───┘
```

| Step | What happens | Code |
|---|---|---|
| Extract | CSV files are loaded into `staging` unchanged, as text | `src/etl.py` |
| Transform | Deduplication, type conversion, topic normalization, validation | `src/transform.py` |
| Load | Dimensions and facts are loaded in one transaction; safe to re-run | `src/etl.py` |
| Quality checks | 8 SQL checks; a failed critical check blocks the report | `src/quality_checks.py` |
| Report | 5 analytical queries → one Excel file with a chart | `src/report.py`, `sql/analytics/` |

## Results of a run

```
1. Extract:   62,961 rows -> staging.calls_raw
2. Transform: 62,059 clean, 403 rejected, 499 duplicates removed, 122 bad CSAT set to NULL
     rejected - answered call without agent: 187
     rejected - negative or missing duration: 123
     rejected - agent not in agents reference: 62
     rejected - missing or unparsable started_at: 31
3. Load:      62,059 new rows -> core.fact_call (0 were already loaded)
4. Data-quality checks: 8 of 8 passed
```

Every source row is accounted for: 62,059 loaded + 403 rejected + 499 duplicates = 62,961 extracted.
Running the pipeline a second time loads **0 new rows** — the load is idempotent.

### What the report shows

| Metric (May–Oct 2026) | Value |
|---|---|
| Calls | 62,059 |
| Service level (answered within 20 s) | 44.8% |
| Abandon rate | 22.5% |
| Average handling time | 291 s |
| Average CSAT | 3.94 / 5 |

- **Peak hours are understaffed.** At 11:00 the abandon rate is 32.6% and the 90th-percentile wait is 82 s;
  at night it is under 5%. The hours 10:00–16:00 hold more than half of all calls.
- **Complaints and Internet issues come back.** 17.6% of answered Complaint calls and 12.9% of Internet
  calls are followed by another call on the same topic within 24 hours, against 4.4% for Tariff change.
  Repeat Internet calls alone cost about 143 agent-hours over the period.

These numbers describe generated data, so they demonstrate the analysis, not a real contact center.

## Database design

- **`staging`** — raw data exactly as received. If a cleaning rule turns out to be wrong, the original is still there.
- **`core`** — a star schema: `fact_call` with foreign keys to `dim_agent`, `dim_topic`, `dim_region`.
  Business rules are enforced by constraints, e.g. an answered call must have an agent and an abandoned one must not.
- **`core.rejected_call`** — rows that failed validation, stored with the reason and the full original row as `jsonb`.
- **`dq`** — a log of pipeline runs and the result of every quality check.

Schema: [`sql/01_schema.sql`](sql/01_schema.sql). Indexes: [`sql/02_indexes.sql`](sql/02_indexes.sql).

## SQL analytics

| File | Question | SQL features |
|---|---|---|
| [`01_daily_service_level.sql`](sql/analytics/01_daily_service_level.sql) | How do daily KPIs change? | `FILTER`, named `WINDOW`, 7-day moving average |
| [`02_agent_ranking.sql`](sql/analytics/02_agent_ranking.sql) | Who performs above or below their team? | `RANK`, `NTILE`, `AVG() OVER (PARTITION BY)` |
| [`03_repeat_calls_by_topic.sql`](sql/analytics/03_repeat_calls_by_topic.sql) | Which topics are not solved on the first call? | `LAG`, interval arithmetic, correlated subquery |
| [`04_hourly_load.sql`](sql/analytics/04_hourly_load.sql) | When do customers wait longest? | `PERCENTILE_CONT`, `DENSE_RANK`, share of total |
| [`05_monthly_topic_trend.sql`](sql/analytics/05_monthly_topic_trend.sql) | Which topics are growing? | `LAG` for month-over-month, running total |

## Query optimization

`src/explain_demo.py` runs `EXPLAIN (ANALYZE, BUFFERS)` for three typical queries without and with an index
and writes the real plans to [`docs/query_optimization.md`](docs/query_optimization.md).

| Query | Without index | With index | Speed-up |
|---|---|---|---|
| Call history of one customer | 5.304 ms | 0.044 ms | 121x |
| One agent's calls for one week | 5.854 ms | 0.107 ms | 55x |
| All calls of one day | 4.439 ms | 0.696 ms | 6x |

Measured on 62,059 rows with PostgreSQL 17 on a laptop; the table is small, so absolute times are low,
but the change of plan from a sequential scan to an index scan is what matters as the table grows.

## How to run

Requirements: Python 3.11+ and PostgreSQL 14+.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows;  source .venv/bin/activate on Linux/macOS
pip install -r requirements.txt

copy .env.example .env            # then put your PostgreSQL password into .env

python src/generate_data.py       # creates data/raw/agents.csv and calls.csv
python run_pipeline.py            # creates the database, loads data, builds reports/*.xlsx
python src/explain_demo.py        # optional: regenerates docs/query_optimization.md
pytest                            # unit tests for the cleaning rules (no database needed)
```

## Project structure

```
├── run_pipeline.py          # runs all steps in order
├── src/
│   ├── generate_data.py     # synthetic data with data-quality problems
│   ├── db.py                # connection settings from .env
│   ├── etl.py               # extract, load
│   ├── transform.py         # cleaning and validation rules (pure pandas)
│   ├── quality_checks.py    # post-load checks
│   ├── report.py            # Excel report
│   └── explain_demo.py      # index benchmarks
├── sql/
│   ├── 01_schema.sql
│   ├── 02_indexes.sql
│   └── analytics/           # five report queries
├── tests/test_transform.py
└── docs/query_optimization.md
```

## Possible next steps

- Incremental extract: load only files or rows newer than the last successful run.
- Schedule the pipeline (Windows Task Scheduler, cron or Airflow).
- Partition `fact_call` by month once the table grows.
