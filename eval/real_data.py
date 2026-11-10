"""Real, public wearable data, as the daily table the agent reads.

LifeSnaps (Fitbit Sense, CC BY 4.0, https://zenodo.org/records/7229547) and PMData (Fitbit Versa 2,
CC BY 4.0, https://datasets.simula.no/pmdata/). Both live in the git-ignored `data/eval/`, unpacked
by hand, and nothing from them enters git but aggregate results. People are drawn at random from
everyone with enough data, because keeping only the most complete would favour the most diligent.
"""

import json
import random
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("data/eval")
LIFESNAPS = ROOT / "lifesnaps/x/rais_anonymized/csv_rais_anonymized"
PMDATA = ROOT / "pmdata/x"
MIN_DAYS = 28
SEED = 503
LIFESNAPS_PEOPLE = 30
LOW_WEAR_NOT_RECORDED = 900.0  # LifeSnaps has no wear time; nights and steps exist, so assume worn


def _daily(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.sort_index()
    index = pd.date_range(frame.index.min(), frame.index.max(), freq="D", name="date")
    return frame.reindex(index)


def enough(frame: pd.DataFrame) -> bool:
    return all(
        c in frame and frame[c].notna().sum() >= MIN_DAYS for c in ("sleep_minutes", "steps")
    )


def load_lifesnaps() -> dict[str, pd.DataFrame]:
    """Everyone with enough sleep and steps; the 30 are chosen by `choose_lifesnaps`."""
    raw = pd.read_csv(
        LIFESNAPS / "daily_fitbit_sema_df_unprocessed.csv", index_col=0, low_memory=False
    )
    people = {}
    for pid, rows in raw.groupby("id"):
        rows = (
            rows.assign(date=pd.to_datetime(rows["date"])).drop_duplicates("date").set_index("date")
        )
        asleep = pd.to_numeric(rows["minutesAsleep"], errors="coerce")
        zone = lambda n: pd.to_numeric(rows[f"minutes_in_default_zone_{n}"], errors="coerce")  # noqa: E731
        frame = pd.DataFrame(
            {
                "steps": pd.to_numeric(rows["steps"], errors="coerce"),
                "calories": pd.to_numeric(rows["calories"], errors="coerce"),
                "distance_km": pd.to_numeric(rows["distance"], errors="coerce") / 1000,
                "resting_hr": pd.to_numeric(rows["resting_hr"], errors="coerce"),
                "hrv_ms": pd.to_numeric(rows["rmssd"], errors="coerce"),
                "respiratory_rate": pd.to_numeric(
                    rows["full_sleep_breathing_rate"], errors="coerce"
                ),
                "sleep_minutes": asleep,
                "time_in_bed": pd.to_numeric(rows["sleep_duration"], errors="coerce") / 60_000,
                "sleep_efficiency": pd.to_numeric(rows["sleep_efficiency"], errors="coerce"),
                "awake_in_bed_minutes": pd.to_numeric(rows["minutesAwake"], errors="coerce"),
                "deep_sleep_minutes": pd.to_numeric(rows["sleep_deep_ratio"], errors="coerce")
                * asleep,
                "rem_sleep_minutes": pd.to_numeric(rows["sleep_rem_ratio"], errors="coerce")
                * asleep,
                "light_sleep_minutes": pd.to_numeric(rows["sleep_light_ratio"], errors="coerce")
                * asleep,
                "sedentary_minutes": pd.to_numeric(rows["sedentary_minutes"], errors="coerce"),
                "lightly_active_minutes": pd.to_numeric(
                    rows["lightly_active_minutes"], errors="coerce"
                ),
                "moderately_active_minutes": pd.to_numeric(
                    rows["moderately_active_minutes"], errors="coerce"
                ),
                "very_active_minutes": pd.to_numeric(rows["very_active_minutes"], errors="coerce"),
                "active_zone_minutes": zone(1) + 2 * (zone(2) + zone(3)),
            }
        )
        frame["wear_minutes"] = LOW_WEAR_NOT_RECORDED
        frame = _daily(frame)
        if enough(frame):
            people[f"ls_{str(pid)[-6:]}"] = frame
    return people


def choose_lifesnaps(people: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """A random 30 of those with enough data, the same 30 every time."""
    names = sorted(people)
    chosen = random.Random(SEED).sample(names, min(LIFESNAPS_PEOPLE, len(names)))
    return {name: people[name] for name in sorted(chosen)}


def _read(path: Path) -> list[dict]:
    return json.loads(path.read_text()) if path.exists() else []


def _per_minute_sum(path: Path, divide: float = 1.0) -> pd.Series:
    rows = _read(path)
    if not rows:
        return pd.Series(dtype=float)
    series = pd.DataFrame(rows)
    series["day"] = pd.to_datetime(series["dateTime"]).dt.normalize()
    series["value"] = pd.to_numeric(series["value"], errors="coerce")
    return series.groupby("day")["value"].sum() / divide


def _per_day(path: Path) -> pd.Series:
    rows = _read(path)
    if not rows:
        return pd.Series(dtype=float)
    series = pd.DataFrame(rows)
    return (
        pd.Series(
            pd.to_numeric(series["value"], errors="coerce").values,
            index=pd.to_datetime(series["dateTime"]).dt.normalize(),
        )
        .groupby(level=0)
        .last()
    )


def _resting(path: Path) -> pd.Series:
    found = {}
    for row in _read(path):
        value = row.get("value") or {}
        if value.get("value"):
            found[pd.to_datetime(row["dateTime"]).normalize()] = float(value["value"])
    return pd.Series(found, dtype=float)


def _sleep(path: Path) -> pd.DataFrame:
    rows = [r for r in _read(path) if r.get("mainSleep")]
    if not rows:
        return pd.DataFrame()
    found = {}
    for row in rows:
        stages = (row.get("levels") or {}).get("summary") or {}
        start = pd.Timestamp(row["startTime"])
        hour = start.hour + start.minute / 60
        found[pd.Timestamp(row["dateOfSleep"])] = {
            "sleep_minutes": row.get("minutesAsleep"),
            "time_in_bed": row.get("timeInBed"),
            "sleep_efficiency": row.get("efficiency"),
            "awake_in_bed_minutes": row.get("minutesAwake"),
            "bedtime_hour": hour - 24 if hour >= 12 else hour,
            "deep_sleep_minutes": (stages.get("deep") or {}).get("minutes"),
            "light_sleep_minutes": (stages.get("light") or {}).get("minutes"),
            "rem_sleep_minutes": (stages.get("rem") or {}).get("minutes"),
        }
    return pd.DataFrame.from_dict(found, orient="index").apply(pd.to_numeric, errors="coerce")


def _zones(path: Path) -> pd.Series:
    found = {}
    for row in _read(path):
        zones = (row.get("value") or {}).get("valuesInZones") or {}
        found[pd.to_datetime(row["dateTime"]).normalize()] = float(
            zones.get("IN_DEFAULT_ZONE_1", 0)
            + 2 * (zones.get("IN_DEFAULT_ZONE_2", 0) + zones.get("IN_DEFAULT_ZONE_3", 0))
        )
    return pd.Series(found, dtype=float)


def load_pmdata() -> dict[str, pd.DataFrame]:
    """All 16 participants, each with a `load` column of reported training (effort x minutes)."""
    people = {}
    for folder in sorted(p for p in PMDATA.glob("p[0-9]*") if p.is_dir()):
        fitbit = folder / "fitbit"
        sleep = _sleep(fitbit / "sleep.json")
        frame = pd.DataFrame(
            {
                "steps": _per_minute_sum(fitbit / "steps.json"),
                "calories": _per_minute_sum(fitbit / "calories.json"),
                "distance_km": _per_minute_sum(fitbit / "distance.json", 100_000),
                "resting_hr": _resting(fitbit / "resting_heart_rate.json"),
                "sedentary_minutes": _per_day(fitbit / "sedentary_minutes.json"),
                "lightly_active_minutes": _per_day(fitbit / "lightly_active_minutes.json"),
                "moderately_active_minutes": _per_day(fitbit / "moderately_active_minutes.json"),
                "very_active_minutes": _per_day(fitbit / "very_active_minutes.json"),
                "active_zone_minutes": _zones(fitbit / "time_in_heart_rate_zones.json"),
            }
        )
        frame = frame.join(sleep, how="outer") if not sleep.empty else frame
        frame["wear_minutes"] = np.where(
            frame["sedentary_minutes"].notna(), LOW_WEAR_NOT_RECORDED, np.nan
        )
        frame.index.name = "date"
        people[folder.name] = _daily(frame)
    return people


def training_load(person: str) -> pd.Series:
    """What a PMData participant reported training each day: effort x minutes, an outside check."""
    path = PMDATA / person / "pmsys" / "srpe.csv"
    if not path.exists():
        return pd.Series(dtype=float)
    rows = pd.read_csv(path)
    day = (
        pd.to_datetime(rows["end_date_time"], errors="coerce", utc=True)
        .dt.tz_localize(None)
        .dt.normalize()
    )
    return (rows["perceived_exertion"] * rows["duration_min"]).groupby(day).sum()
