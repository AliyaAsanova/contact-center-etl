"""Extract -> Transform -> Load for contact-center calls.

extract : CSV files           -> staging.* tables (raw text, nothing changed)
transform: staging.calls_raw  -> clean DataFrame + rejected rows (src/transform.py)
load    : clean DataFrame     -> core.dim_* and core.fact_call

The load is idempotent: running the pipeline twice does not duplicate calls,
because rows are inserted with ON CONFLICT (call_id) DO NOTHING.
"""

import json

import pandas as pd
from sqlalchemy import Connection, Engine, text

from db import PROJECT_DIR
from transform import TransformResult, transform_calls

RAW_DIR = PROJECT_DIR / "data" / "raw"


def start_run(engine: Engine) -> int:
    with engine.begin() as conn:
        return conn.execute(text("INSERT INTO dq.pipeline_run DEFAULT VALUES RETURNING run_id")).scalar_one()


def extract(engine: Engine) -> int:
    """Load CSV files into staging as text. Staging is fully replaced on each run."""
    calls = pd.read_csv(RAW_DIR / "calls.csv", dtype=str, keep_default_na=False, na_values=[""])
    agents = pd.read_csv(RAW_DIR / "agents.csv", dtype=str)

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE staging.calls_raw, staging.agents_raw"))
        agents.to_sql("agents_raw", conn, schema="staging", if_exists="append", index=False)
        calls.to_sql("calls_raw", conn, schema="staging", if_exists="append", index=False,
                     method="multi", chunksize=5_000)
    return len(calls)


def transform(engine: Engine) -> TransformResult:
    with engine.connect() as conn:
        raw = pd.read_sql(text("SELECT * FROM staging.calls_raw"), conn)
        agents = pd.read_sql(text("SELECT agent_id FROM staging.agents_raw"), conn)
    return transform_calls(raw, known_agents=set(agents["agent_id"]))


def _load_dimensions(conn: Connection, clean: pd.DataFrame) -> None:
    # Agents: update attributes if the reference changed (a simple SCD type 1)
    conn.execute(text("""
        INSERT INTO core.dim_agent (agent_id, full_name, team, hire_date, shift)
        SELECT agent_id, full_name, team, hire_date::date, shift
        FROM staging.agents_raw
        ON CONFLICT (agent_id) DO UPDATE
            SET full_name = EXCLUDED.full_name,
                team      = EXCLUDED.team,
                shift     = EXCLUDED.shift
    """))
    for table, column, values in [
        ("dim_topic", "topic_name", clean["topic_name"].unique()),
        ("dim_region", "region_name", clean["region_name"].unique()),
    ]:
        conn.execute(
            text(f"INSERT INTO core.{table} ({column}) VALUES (:v) ON CONFLICT ({column}) DO NOTHING"),
            [{"v": v} for v in sorted(values)],
        )


def load(engine: Engine, run_id: int, result: TransformResult) -> int:
    """Load dimensions, facts and rejected rows in ONE transaction: all or nothing."""
    with engine.begin() as conn:
        _load_dimensions(conn, result.clean)

        # Put clean rows into a temporary table, then insert with dimension lookups.
        conn.execute(text("""
            CREATE TEMP TABLE tmp_call (
                call_id bigint, customer_id text, started_at timestamp, call_date date,
                agent_id text, topic_name text, region_name text, channel text, status text,
                wait_seconds integer, talk_seconds integer, is_resolved boolean, csat smallint
            ) ON COMMIT DROP
        """))
        result.clean.to_sql("tmp_call", conn, if_exists="append", index=False,
                            method="multi", chunksize=5_000)
        inserted = conn.execute(text("""
            INSERT INTO core.fact_call (
                call_id, customer_id, started_at, call_date, agent_id, topic_id, region_id,
                channel, status, wait_seconds, talk_seconds, is_resolved, csat)
            SELECT t.call_id, t.customer_id, t.started_at, t.call_date, t.agent_id,
                   dt.topic_id, dr.region_id,
                   t.channel, t.status, t.wait_seconds, t.talk_seconds, t.is_resolved, t.csat
            FROM tmp_call t
            JOIN core.dim_topic  dt ON dt.topic_name  = t.topic_name
            JOIN core.dim_region dr ON dr.region_name = t.region_name
            ON CONFLICT (call_id) DO NOTHING
        """)).rowcount

        # Rejected rows are saved with the reason and the full original row
        rejected = result.rejected
        if len(rejected):
            raw_columns = [c for c in rejected.columns if c != "reason"]
            rows = [
                {
                    "run_id": run_id,
                    "call_id": row["call_id"],
                    "reason": row["reason"],
                    "raw_row": json.dumps({c: row[c] for c in raw_columns}),
                }
                for row in rejected.astype(object).where(rejected.notna(), None).to_dict("records")
            ]
            conn.execute(text("""
                INSERT INTO core.rejected_call (run_id, call_id, reason, raw_row)
                VALUES (:run_id, :call_id, :reason, CAST(:raw_row AS jsonb))
            """), rows)
    return inserted


def finish_run(engine: Engine, run_id: int, status: str, **counters: int) -> None:
    assignments = ", ".join(f"{name} = :{name}" for name in counters)
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE dq.pipeline_run SET finished_at = now(), status = :status"
                 f"{', ' + assignments if assignments else ''} WHERE run_id = :run_id"),
            {"status": status, "run_id": run_id, **counters},
        )
