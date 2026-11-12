"""Unit tests for the cleaning rules. They need no database: `pytest`."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from transform import normalize_topic, parse_timestamp, transform_calls  # noqa: E402

AGENTS = {"A001", "A002"}


def make_raw(**overrides) -> pd.DataFrame:
    """One valid answered call; tests override single fields to break it."""
    row = {
        "call_id": "1", "customer_id": "C000001", "started_at": "2026-05-01 10:00:00",
        "topic": "Billing", "region": "Bishkek", "channel": "phone", "status": "answered",
        "agent_id": "A001", "wait_seconds": "12", "talk_seconds": "200",
        "is_resolved": "True", "csat": "5",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_valid_row_passes_unchanged():
    result = transform_calls(make_raw(), AGENTS)
    assert len(result.clean) == 1 and len(result.rejected) == 0
    row = result.clean.iloc[0]
    assert row["topic_name"] == "Billing"
    assert row["talk_seconds"] == 200
    assert bool(row["is_resolved"]) is True


def test_both_timestamp_formats_are_parsed():
    parsed = parse_timestamp(pd.Series(["2026-05-01 10:00:00", "01.05.2026 10:00", "not a date"]))
    assert parsed[0] == parsed[1] == pd.Timestamp("2026-05-01 10:00:00")
    assert pd.isna(parsed[2])


def test_topic_is_normalized():
    topics = normalize_topic(pd.Series(["  BILLING ", "sim/esim", "Tariff Change", "something new"]))
    assert list(topics) == ["Billing", "SIM / eSIM", "Tariff change", "Other"]


def test_duplicates_are_removed():
    raw = pd.concat([make_raw(), make_raw()], ignore_index=True)
    result = transform_calls(raw, AGENTS)
    assert len(result.clean) == 1
    assert result.duplicates_removed == 1


def test_bad_rows_are_rejected_with_reason():
    cases = {
        "missing or unparsable started_at": make_raw(started_at=None),
        "negative or missing duration": make_raw(talk_seconds="-1"),
        "answered call without agent": make_raw(agent_id=None),
        "agent not in agents reference": make_raw(agent_id="A999"),
    }
    for expected_reason, raw in cases.items():
        result = transform_calls(raw, AGENTS)
        assert len(result.clean) == 0
        assert result.rejected.iloc[0]["reason"] == expected_reason


def test_out_of_range_csat_becomes_null_but_row_is_kept():
    result = transform_calls(make_raw(csat="9"), AGENTS)
    assert len(result.clean) == 1
    assert pd.isna(result.clean.iloc[0]["csat"])
    assert result.csat_nullified == 1


def test_abandoned_call_has_no_agent_and_no_talk_time():
    raw = make_raw(status="abandoned", agent_id=None, talk_seconds="35", is_resolved="False", csat=None)
    row = transform_calls(raw, AGENTS).clean.iloc[0]
    assert row["agent_id"] is None
    assert row["talk_seconds"] == 0
    assert bool(row["is_resolved"]) is False
