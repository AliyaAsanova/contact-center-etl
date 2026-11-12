"""Run the whole pipeline: schema -> extract -> transform -> load -> checks -> report.

Usage:
    python run_pipeline.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import etl  # noqa: E402
from db import create_database_if_missing, get_engine, run_sql_file  # noqa: E402
from quality_checks import run_checks  # noqa: E402
from report import build_report  # noqa: E402


def main() -> int:
    create_database_if_missing()
    engine = get_engine()
    run_sql_file(engine, "01_schema.sql")
    run_sql_file(engine, "02_indexes.sql")

    run_id = etl.start_run(engine)
    print(f"Pipeline run #{run_id}")
    try:
        rows_extracted = etl.extract(engine)
        print(f"1. Extract:   {rows_extracted:,} rows -> staging.calls_raw")

        result = etl.transform(engine)
        print(f"2. Transform: {len(result.clean):,} clean, {len(result.rejected):,} rejected, "
              f"{result.duplicates_removed:,} duplicates removed, {result.csat_nullified:,} bad CSAT set to NULL")
        for reason, count in result.rejected["reason"].value_counts().items():
            print(f"     rejected - {reason}: {count}")

        rows_loaded = etl.load(engine, run_id, result)
        already = len(result.clean) - rows_loaded
        print(f"3. Load:      {rows_loaded:,} new rows -> core.fact_call ({already:,} were already loaded)")

        print("4. Data-quality checks:")
        checks_ok = run_checks(engine, run_id)
    except Exception:
        etl.finish_run(engine, run_id, "failed")
        raise

    etl.finish_run(
        engine, run_id, "success" if checks_ok else "failed_checks",
        rows_extracted=rows_extracted, duplicates_removed=result.duplicates_removed,
        rows_rejected=len(result.rejected), rows_loaded=rows_loaded, rows_already_in_db=already,
    )
    if not checks_ok:
        print("A critical data-quality check failed: the report was NOT built.")
        return 1

    print(f"5. Report:    {build_report(engine, run_id)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
