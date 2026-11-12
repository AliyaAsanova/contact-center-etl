"""Data-quality checks that run after every load.

Each check is one SQL query that returns a single number, plus a rule for that
number. Results are stored in dq.check_result, so quality can be tracked over time.
A failed *critical* check stops the pipeline before any report is built.
"""

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import Engine, text


@dataclass
class Check:
    name: str
    severity: str                      # 'critical' or 'warning'
    sql: str                           # must return one numeric value
    rule: Callable[[float], bool]
    expected: str


CHECKS = [
    Check(
        name="reconciliation: staging rows = loaded + rejected + duplicates",
        severity="critical",
        sql="""
            SELECT (SELECT count(*) FROM staging.calls_raw)
                 - (SELECT count(DISTINCT call_id) FROM staging.calls_raw
                    WHERE call_id::bigint IN (SELECT call_id FROM core.fact_call))
                 - (SELECT count(*) FROM core.rejected_call WHERE run_id = :run_id)
                 - (SELECT count(*) - count(DISTINCT call_id) FROM staging.calls_raw)
        """,
        rule=lambda v: v == 0,
        expected="0 rows unaccounted for",
    ),
    Check(
        name="uniqueness: call_id is unique in fact_call",
        severity="critical",
        sql="SELECT count(*) - count(DISTINCT call_id) FROM core.fact_call",
        rule=lambda v: v == 0,
        expected="0 duplicates",
    ),
    Check(
        name="integrity: every answered call has an existing agent",
        severity="critical",
        sql="""
            SELECT count(*)
            FROM core.fact_call f
            LEFT JOIN core.dim_agent a USING (agent_id)
            WHERE f.status = 'answered' AND a.agent_id IS NULL
        """,
        rule=lambda v: v == 0,
        expected="0 orphan calls",
    ),
    Check(
        name="validity: abandoned calls have no talk time",
        severity="critical",
        sql="SELECT count(*) FROM core.fact_call WHERE status = 'abandoned' AND talk_seconds > 0",
        rule=lambda v: v == 0,
        expected="0 rows",
    ),
    Check(
        name="validity: no calls dated in the future",
        severity="critical",
        sql="SELECT count(*) FROM core.fact_call WHERE started_at > now()",
        rule=lambda v: v == 0,
        expected="0 rows",
    ),
    Check(
        name="completeness: no days without calls inside the loaded period",
        severity="warning",
        sql="""
            SELECT count(*)
            FROM generate_series(
                     (SELECT min(call_date) FROM core.fact_call),
                     (SELECT max(call_date) FROM core.fact_call),
                     interval '1 day') AS d(day)
            WHERE NOT EXISTS (SELECT 1 FROM core.fact_call f WHERE f.call_date = d.day::date)
        """,
        rule=lambda v: v == 0,
        expected="0 missing days",
    ),
    Check(
        name="reject rate: share of rejected rows, percent",
        severity="warning",
        sql="""
            SELECT round(100.0 * (SELECT count(*) FROM core.rejected_call WHERE run_id = :run_id)
                         / NULLIF((SELECT count(*) FROM staging.calls_raw), 0), 2)
        """,
        rule=lambda v: v < 2,
        expected="< 2",
    ),
    Check(
        name="plausibility: calls longer than 1 hour, percent",
        severity="warning",
        sql="""
            SELECT round(100.0 * count(*) FILTER (WHERE talk_seconds > 3600) / NULLIF(count(*), 0), 2)
            FROM core.fact_call
        """,
        rule=lambda v: v < 1,
        expected="< 1",
    ),
]


def run_checks(engine: Engine, run_id: int) -> bool:
    """Run all checks, save results, print a summary. Returns False if a critical check failed."""
    all_critical_passed = True
    with engine.begin() as conn:
        for check in CHECKS:
            params = {"run_id": run_id} if ":run_id" in check.sql else {}
            value = conn.execute(text(check.sql), params).scalar()
            passed = value is not None and check.rule(float(value))
            conn.execute(
                text("""
                    INSERT INTO dq.check_result (run_id, check_name, severity, passed, observed, expected)
                    VALUES (:run_id, :name, :severity, :passed, :observed, :expected)
                """),
                {"run_id": run_id, "name": check.name, "severity": check.severity,
                 "passed": passed, "observed": str(value), "expected": check.expected},
            )
            mark = "PASS" if passed else ("FAIL" if check.severity == "critical" else "WARN")
            print(f"  [{mark}] {check.name}: {value} (expected {check.expected})")
            if not passed and check.severity == "critical":
                all_critical_passed = False
    return all_critical_passed
