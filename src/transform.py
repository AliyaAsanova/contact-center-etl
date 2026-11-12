"""Cleaning rules for raw call records.

This module has no database code on purpose: it takes a DataFrame and returns
DataFrames, so every rule can be unit-tested (see tests/test_transform.py).
"""

from dataclasses import dataclass

import pandas as pd

CANONICAL_TOPICS = [
    "Billing", "Internet", "Tariff change", "Roaming",
    "SIM / eSIM", "Device settings", "Complaint", "Other",
]


def _topic_key(value: str) -> str:
    """'  sim/ESIM ' and 'SIM / eSIM' must give the same key."""
    return "".join(str(value).lower().split())


TOPIC_BY_KEY = {_topic_key(t): t for t in CANONICAL_TOPICS}


@dataclass
class TransformResult:
    clean: pd.DataFrame      # rows ready to load into core.fact_call
    rejected: pd.DataFrame   # original rows + "reason" column
    duplicates_removed: int
    csat_nullified: int


def parse_timestamp(series: pd.Series) -> pd.Series:
    """Source systems use two formats: ISO and DD.MM.YYYY HH:MM."""
    iso = pd.to_datetime(series, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    dotted = pd.to_datetime(series, format="%d.%m.%Y %H:%M", errors="coerce")
    return iso.fillna(dotted)


def normalize_topic(series: pd.Series) -> pd.Series:
    """Fix case and spacing; anything unknown becomes 'Other'."""
    return series.map(_topic_key).map(TOPIC_BY_KEY).fillna("Other")


def transform_calls(raw: pd.DataFrame, known_agents: set[str]) -> TransformResult:
    """Deduplicate, convert types, validate. Bad rows go to `rejected` with a reason."""
    df = raw.copy()

    # 1. The same call exported twice -> keep one copy
    before = len(df)
    df = df.drop_duplicates(subset="call_id", keep="first")
    duplicates_removed = before - len(df)

    # 2. Types
    df["started_at_parsed"] = parse_timestamp(df["started_at"])
    df["wait_num"] = pd.to_numeric(df["wait_seconds"], errors="coerce")
    df["talk_num"] = pd.to_numeric(df["talk_seconds"], errors="coerce")
    df["csat_num"] = pd.to_numeric(df["csat"], errors="coerce")
    df["agent_id"] = df["agent_id"].where(df["agent_id"].notna() & (df["agent_id"] != ""), None)

    # 3. Validation. The first matching rule gives the reject reason.
    rules = [
        ("missing or unparsable started_at", df["started_at_parsed"].isna()),
        ("unknown status", ~df["status"].isin(["answered", "abandoned"])),
        ("negative or missing duration",
         df["wait_num"].isna() | df["talk_num"].isna() | (df["wait_num"] < 0) | (df["talk_num"] < 0)),
        ("answered call without agent", (df["status"] == "answered") & df["agent_id"].isna()),
        ("agent not in agents reference",
         df["agent_id"].notna() & ~df["agent_id"].isin(known_agents)),
    ]
    df["reason"] = None
    for reason, mask in rules:
        df.loc[mask & df["reason"].isna(), "reason"] = reason

    rejected = df.loc[df["reason"].notna(), list(raw.columns) + ["reason"]]
    ok = df[df["reason"].isna()]

    # 4. Repairable problems are fixed instead of rejected
    bad_csat = ok["csat_num"].notna() & ~ok["csat_num"].between(1, 5)
    is_abandoned = ok["status"] == "abandoned"

    clean = pd.DataFrame({
        "call_id": ok["call_id"].astype("int64"),
        "customer_id": ok["customer_id"].str.strip(),
        "started_at": ok["started_at_parsed"],
        "call_date": ok["started_at_parsed"].dt.date,
        "agent_id": ok["agent_id"].where(~is_abandoned, None),
        "topic_name": normalize_topic(ok["topic"]),
        "region_name": ok["region"].str.strip(),
        "channel": ok["channel"].str.strip().str.lower(),
        "status": ok["status"],
        "wait_seconds": ok["wait_num"].astype("int64"),
        "talk_seconds": ok["talk_num"].where(~is_abandoned, 0).astype("int64"),
        "is_resolved": ok["is_resolved"].astype(str).str.lower().eq("true") & ~is_abandoned,
        "csat": ok["csat_num"].where(~bad_csat).astype("Int64"),
    })

    return TransformResult(clean, rejected, duplicates_removed, int(bad_csat.sum()))
