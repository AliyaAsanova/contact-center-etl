"""Build the Excel report from the SQL files in sql/analytics/.

Every .sql file becomes one sheet. The first sheet is a summary with headline
KPIs, the last one shows the data-quality checks of the current run.
"""

from datetime import date

import pandas as pd
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import Engine, text

from db import PROJECT_DIR, SQL_DIR

REPORT_DIR = PROJECT_DIR / "reports"

SHEETS = {
    "Daily KPIs": "01_daily_service_level.sql",
    "Agents": "02_agent_ranking.sql",
    "Repeat calls": "03_repeat_calls_by_topic.sql",
    "Hourly load": "04_hourly_load.sql",
    "Topic trend": "05_monthly_topic_trend.sql",
}

SUMMARY_SQL = """
    SELECT
        min(call_date)                                               AS period_start,
        max(call_date)                                               AS period_end,
        count(*)                                                     AS total_calls,
        round(100.0 * avg((status = 'abandoned')::int), 1)           AS abandon_rate_pct,
        round(100.0 * avg((status = 'answered' AND wait_seconds <= 20)::int), 1) AS service_level_pct,
        round(avg(talk_seconds) FILTER (WHERE status = 'answered'))  AS aht_seconds,
        round(avg(csat), 2)                                          AS avg_csat
    FROM core.fact_call
"""

DQ_SQL = """
    SELECT check_name, severity, passed, observed, expected
    FROM dq.check_result
    WHERE run_id = :run_id
    ORDER BY check_id
"""


def _format_sheet(ws) -> None:
    """Bold header, frozen first row, readable column widths."""
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="305496")
    ws.freeze_panes = "A2"
    for i, column in enumerate(ws.columns, start=1):
        width = max(len(str(c.value)) if c.value is not None else 0 for c in column)
        ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 60)


def _add_daily_chart(ws, n_rows: int, headers: list[str]) -> None:
    chart = LineChart()
    chart.title = "Service level, 7-day moving average (%)"
    chart.height, chart.width = 8, 22
    col = headers.index("service_level_ma7_pct") + 1
    chart.add_data(Reference(ws, min_col=col, min_row=1, max_row=n_rows + 1), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=n_rows + 1))
    ws.add_chart(chart, f"{get_column_letter(len(headers) + 2)}2")


def build_report(engine: Engine, run_id: int) -> str:
    REPORT_DIR.mkdir(exist_ok=True)
    path = REPORT_DIR / f"contact_center_report_{date.today():%Y-%m-%d}.xlsx"

    with engine.connect() as conn:
        summary = pd.read_sql(text(SUMMARY_SQL), conn).T.reset_index()
        summary.columns = ["metric", "value"]
        frames = {"Summary": summary}
        for sheet, filename in SHEETS.items():
            sql = (SQL_DIR / "analytics" / filename).read_text(encoding="utf-8")
            frames[sheet] = pd.read_sql(text(sql), conn)
        frames["Data quality"] = pd.read_sql(text(DQ_SQL), conn, params={"run_id": run_id})

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet, frame in frames.items():
            frame.to_excel(writer, sheet_name=sheet, index=False)
            _format_sheet(writer.sheets[sheet])
        daily = frames["Daily KPIs"]
        _add_daily_chart(writer.sheets["Daily KPIs"], len(daily), list(daily.columns))

    return str(path)
