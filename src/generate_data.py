"""Generate synthetic contact-center data with realistic data-quality problems.

The data is NOT real. It imitates six months of calls to a mobile operator's
contact center, and it is deliberately "dirty" (duplicates, mixed date formats,
impossible values) so that the ETL pipeline has something to clean.

Usage:
    python src/generate_data.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
START_DATE = "2026-05-01"
END_DATE = "2026-10-31"
N_AGENTS = 40
N_CUSTOMERS = 12_000

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

# topic -> (share of calls, median talk time in seconds, chance to resolve on first call)
TOPICS = {
    "Billing": (0.24, 240, 0.82),
    "Internet": (0.22, 330, 0.68),
    "Tariff change": (0.16, 180, 0.90),
    "Roaming": (0.07, 300, 0.74),
    "SIM / eSIM": (0.09, 210, 0.85),
    "Device settings": (0.08, 360, 0.70),
    "Complaint": (0.06, 420, 0.55),
    "Other": (0.08, 150, 0.88),
}

REGIONS = {
    "Bishkek": 0.38, "Chuy": 0.16, "Osh": 0.17, "Jalal-Abad": 0.11,
    "Issyk-Kul": 0.07, "Naryn": 0.04, "Talas": 0.03, "Batken": 0.04,
}

# Relative call volume for each hour of the day (index = hour)
HOUR_PROFILE = np.array([
    1, 1, 1, 1, 1, 2, 4, 8, 14, 20, 24, 25,
    22, 21, 22, 23, 22, 20, 18, 15, 11, 7, 4, 2,
], dtype=float)

FIRST_NAMES = ["Aibek", "Aigerim", "Bakyt", "Begimai", "Daniyar", "Elnura", "Erlan",
               "Gulzat", "Kanat", "Meerim", "Nurlan", "Saltanat", "Timur", "Zhyldyz"]
LAST_NAMES = ["Abdyldaev", "Bekov", "Dzhumabaev", "Isakov", "Kasymov", "Mamytov",
              "Osmonov", "Sadykov", "Toktogulov", "Usenov"]


def make_agents(rng: np.random.Generator) -> pd.DataFrame:
    """Create the agents reference table."""
    teams = ["Team A", "Team B", "Team C", "Team D"]
    rows = []
    for i in range(1, N_AGENTS + 1):
        hire = pd.Timestamp("2023-01-01") + pd.Timedelta(days=int(rng.integers(0, 1150)))
        rows.append({
            "agent_id": f"A{i:03d}",
            "full_name": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
            "team": teams[(i - 1) % len(teams)],
            "hire_date": hire.date().isoformat(),
            "shift": rng.choice(["day", "evening", "night"], p=[0.55, 0.35, 0.10]),
        })
    return pd.DataFrame(rows)


def make_calls(rng: np.random.Generator, agents: pd.DataFrame) -> pd.DataFrame:
    """Create clean call records. Dirt is added later in add_data_quality_issues()."""
    topic_names = list(TOPICS)
    topic_p = np.array([TOPICS[t][0] for t in topic_names])
    region_names = list(REGIONS)
    region_p = np.array(list(REGIONS.values()))

    # Every agent has a personal skill: a faster/slower talker, better/worse resolver.
    agent_ids = agents["agent_id"].to_numpy()
    agent_speed = dict(zip(agent_ids, rng.normal(1.0, 0.12, len(agent_ids))))
    agent_quality = dict(zip(agent_ids, rng.normal(0.0, 0.05, len(agent_ids))))

    rows = []
    for day in pd.date_range(START_DATE, END_DATE, freq="D"):
        weekday_factor = 1.0 if day.day_of_week < 5 else 0.6
        # Slow growth of traffic over the period + random daily noise
        trend = 1.0 + 0.15 * (day - pd.Timestamp(START_DATE)).days / 183
        n_calls = rng.poisson(330 * weekday_factor * trend)

        hours = rng.choice(24, size=n_calls, p=HOUR_PROFILE / HOUR_PROFILE.sum())
        for hour in hours:
            started_at = day + pd.Timedelta(hours=int(hour), seconds=int(rng.integers(0, 3600)))
            topic = rng.choice(topic_names, p=topic_p)
            _, talk_median, resolve_p = TOPICS[topic]

            # Busy hours -> longer queue. Customers hang up if they wait too long.
            load = HOUR_PROFILE[hour] / HOUR_PROFILE.max()
            wait = int(rng.exponential(8 + 45 * load ** 2))
            patience = rng.exponential(110)
            answered = wait <= patience

            row = {
                "customer_id": f"C{rng.integers(1, N_CUSTOMERS + 1):06d}",
                "started_at": started_at,
                "topic": topic,
                "region": rng.choice(region_names, p=region_p),
                "channel": rng.choice(["phone", "chat"], p=[0.8, 0.2]),
            }
            if answered:
                agent = rng.choice(agent_ids)
                talk = int(rng.lognormal(np.log(talk_median * agent_speed[agent]), 0.45))
                resolved = rng.random() < resolve_p + agent_quality[agent]
                csat = None
                if rng.random() < 0.35:  # only some customers answer the survey
                    score = 4.3 - 0.012 * wait + (0.4 if resolved else -1.3) + rng.normal(0, 0.8)
                    csat = int(np.clip(round(score), 1, 5))
                row.update(status="answered", agent_id=agent, wait_seconds=wait,
                           talk_seconds=max(talk, 15), is_resolved=resolved, csat=csat)
            else:
                row.update(status="abandoned", agent_id=None, wait_seconds=int(patience),
                           talk_seconds=0, is_resolved=False, csat=None)
            rows.append(row)

            # An unresolved problem often makes the customer call again within a day.
            if answered and not row["is_resolved"] and rng.random() < 0.45:
                repeat = dict(row)
                repeat["started_at"] = started_at + pd.Timedelta(minutes=int(rng.integers(20, 1400)))
                repeat["agent_id"] = rng.choice(agent_ids)
                repeat["wait_seconds"] = int(rng.exponential(25))
                repeat["is_resolved"] = rng.random() < 0.8
                repeat["csat"] = None
                rows.append(repeat)

    calls = pd.DataFrame(rows).sort_values("started_at").reset_index(drop=True)
    calls = calls[calls["started_at"] <= pd.Timestamp(END_DATE) + pd.Timedelta(hours=23, minutes=59)]
    calls.insert(0, "call_id", np.arange(1_000_001, 1_000_001 + len(calls)))
    return calls


def add_data_quality_issues(rng: np.random.Generator, calls: pd.DataFrame) -> pd.DataFrame:
    """Spoil the clean data the way real source systems do."""
    raw = calls.copy()
    n = len(raw)

    def pick(share: float) -> np.ndarray:
        return rng.choice(n, size=int(n * share), replace=False)

    # Everything is text in a CSV export, so convert before spoiling.
    raw["started_at"] = raw["started_at"].dt.strftime("%Y-%m-%d %H:%M:%S")
    raw["csat"] = raw["csat"].astype("Int64").astype("string")
    raw["topic"] = raw["topic"].astype("object")

    # 1. A second source system writes dates as DD.MM.YYYY HH:MM
    idx = pick(0.03)
    raw.loc[idx, "started_at"] = pd.to_datetime(raw.loc[idx, "started_at"]).dt.strftime("%d.%m.%Y %H:%M")

    # 2. Topic is typed by hand: random case and extra spaces
    idx = pick(0.05)
    raw.loc[idx, "topic"] = [
        rng.choice([t.upper(), t.lower(), f"  {t} ", t.replace(" / ", "/")]) for t in raw.loc[idx, "topic"]
    ]

    # 3. Impossible values
    raw.loc[pick(0.002), "talk_seconds"] = -1
    raw.loc[pick(0.002), "csat"] = rng.choice(["0", "9"])

    # 4. Broken references and missing values
    answered = raw.index[raw["status"] == "answered"].to_numpy()
    raw.loc[rng.choice(answered, size=int(n * 0.003), replace=False), "agent_id"] = None
    raw.loc[rng.choice(answered, size=int(n * 0.001), replace=False), "agent_id"] = "A999"
    raw.loc[pick(0.0005), "started_at"] = None

    # 5. Duplicate rows (the same call exported twice)
    duplicates = raw.iloc[pick(0.008)]
    raw = pd.concat([raw, duplicates], ignore_index=True)

    return raw.sample(frac=1, random_state=SEED).reset_index(drop=True)


def main() -> None:
    rng = np.random.default_rng(SEED)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    agents = make_agents(rng)
    calls = make_calls(rng, agents)
    raw_calls = add_data_quality_issues(rng, calls)

    agents.to_csv(RAW_DIR / "agents.csv", index=False)
    raw_calls.to_csv(RAW_DIR / "calls.csv", index=False)
    print(f"agents.csv: {len(agents):,} rows")
    print(f"calls.csv:  {len(raw_calls):,} rows ({len(calls):,} unique calls before adding dirt)")


if __name__ == "__main__":
    main()
