"""Does the app's stress score follow how stressed people say they are? Costs nothing.

PMData's participants rated their stress most mornings and wore a Fitbit, whose minute data lets the
score be rebuilt with the app's own `still_minutes` and `stress_score`. Run from the repository root
of a checkout holding `data/eval/pmdata/x`:
`PYTHONPATH=backend:eval python eval/stress_check.py`. Prints and commits totals only.

A morning rating is about the day before, so the primary test pairs it with the previous day's
score; the same day is reported beside it. Which end of the 1 to 5 scale means stressed is not
stated in the sources we found, so it is read from the ratings of mood and fatigue. PMData has no
HRV and no minute activity levels: a minute with no steps outside sleep counts as still, and one
with 100 or more steps as exercise. Each of those differs from what the app reads from Google.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import real_data
from scipy import stats

from app.analysis.day import with_scores
from app.sync.daily import Level, still_minutes

STEPS_OF_EXERCISE = 100
MIN_PAIRS = 20
TEAM_FLOOR = 5
OUT = Path(__file__).parent / "results" / "stress_check_2026-11-10.json"
ZONES = {
    "BELOW_DEFAULT_ZONE_1": "hr_zone_light_minutes",
    "IN_DEFAULT_ZONE_1": "hr_zone_moderate_minutes",
    "IN_DEFAULT_ZONE_2": "hr_zone_vigorous_minutes",
    "IN_DEFAULT_ZONE_3": "hr_zone_peak_minutes",
}


def epoch_minute(stamps: pd.Series) -> np.ndarray:
    return (pd.to_datetime(stamps).astype("datetime64[s]").astype("int64") // 60).to_numpy()


def still_rows(folder: Path, resting: pd.Series) -> pd.DataFrame:
    fitbit = folder / "fitbit"
    steps = pd.DataFrame(json.loads((fitbit / "steps.json").read_text()))
    steps["minute"] = epoch_minute(steps["dateTime"])
    steps["value"] = pd.to_numeric(steps["value"], errors="coerce")
    steps["day"] = pd.to_datetime(steps["dateTime"]).dt.date
    asleep = set()
    for row in json.loads((fitbit / "sleep.json").read_text()):
        first = int(pd.Timestamp(row["startTime"]).timestamp() // 60)
        last = int(pd.Timestamp(row["endTime"]).timestamp() // 60)
        asleep.update(range(first, last + 1))
    levels = [
        Level(
            r.day,
            r.minute,
            r.minute + 1,
            still=r.value == 0 and r.minute not in asleep,
            exercise=r.value >= STEPS_OF_EXERCISE,
        )
        for r in steps.itertuples()
    ]
    beats = pd.DataFrame(json.loads((fitbit / "heart_rate.json").read_text()))
    beats["minute"] = epoch_minute(beats["dateTime"])
    beats["bpm"] = beats["value"].map(lambda v: v["bpm"])
    heart = beats.groupby("minute")["bpm"].mean().to_dict()
    rest = pd.Series(resting.dropna().to_numpy(), index=[d.date() for d in resting.dropna().index])
    found = still_minutes(levels, heart, rest)
    found.index = pd.to_datetime(found.index)
    return found


def zones(folder: Path) -> pd.DataFrame:
    rows = {}
    for row in json.loads((folder / "fitbit" / "time_in_heart_rate_zones.json").read_text()):
        minutes = (row.get("value") or {}).get("valuesInZones") or {}
        rows[pd.to_datetime(row["dateTime"]).normalize()] = {
            column: float(minutes.get(name, 0)) for name, column in ZONES.items()
        }
    return pd.DataFrame.from_dict(rows, orient="index")


def ratings(folder: Path) -> pd.DataFrame:
    table = pd.read_csv(folder / "pmsys" / "wellness.csv")
    stamp = pd.to_datetime(table["effective_time_frame"], utc=True, errors="coerce")
    table.index = stamp.dt.tz_convert("Europe/Oslo").dt.tz_localize(None).dt.normalize()
    columns = ["stress", "mood", "fatigue", "sleep_quality", "readiness", "sleep_duration_h"]
    return table[columns].apply(pd.to_numeric, errors="coerce").groupby(level=0).last()


def spearman(x: pd.Series, y: pd.Series) -> float | None:
    both = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(both) < MIN_PAIRS or both["x"].nunique() < 3 or both["y"].nunique() < 2:
        return None
    rho = stats.spearmanr(both["x"], both["y"]).statistic
    return None if pd.isna(rho) else float(rho)


def summary(values: list[float | None]) -> dict:
    known = [v for v in values if v is not None]
    if not known:
        return {"people": 0}
    positive = sum(v > 0 for v in known)
    return {
        "people": len(known),
        "median_rho": round(float(np.median(known)), 3),
        "positive": positive,
        "sign_test_p": round(float(stats.binomtest(positive, len(known), 0.5).pvalue), 4),
    }


def standard(series: pd.Series) -> pd.Series:
    spread = series.std()
    return (series - series.mean()) / spread if spread and spread > 0 else series * np.nan


def team_by_week(scores: dict[str, pd.Series], said: dict[str, pd.Series]) -> dict:
    """The feature's real use: one team, week by week, medians of each person against themselves."""

    def weekly(group: dict[str, pd.Series]) -> pd.Series:
        rows = pd.DataFrame(
            {n: standard(s.dropna()).resample("W-SUN").mean() for n, s in group.items()}
        )
        return rows.median(axis=1).where(rows.notna().sum(axis=1) >= TEAM_FLOOR)

    both = pd.DataFrame({"score": weekly(scores), "said": weekly(said)}).dropna()
    if len(both) < 6:
        return {"weeks": len(both)}
    result = stats.spearmanr(both["score"], both["said"])
    return {
        "weeks": len(both),
        "rho": round(float(result.statistic), 3),
        "p": round(float(result.pvalue), 4),
    }


def main() -> None:
    people = real_data.load_pmdata()
    built, said, mood_links, fatigue_links, usable = {}, {}, [], [], 0
    ratings_of = {}
    frames = {}
    for name, frame in sorted(people.items()):
        folder = real_data.PMDATA / name
        try:
            still = still_rows(folder, frame["resting_hr"])
        except (KeyError, ValueError, OSError) as error:
            print("skipped", name, type(error).__name__)
            continue
        full = frame.join(still).join(zones(folder))
        scored = with_scores(full)
        rated = ratings(folder)
        usable += int(scored["stress_score"].notna().sum() >= MIN_PAIRS)
        built[name], said[name], frames[name] = scored["stress_score"], rated["stress"], scored
        ratings_of[name] = rated
        mood_links.append(spearman(rated["stress"], rated["mood"]))
        fatigue_links.append(spearman(rated["stress"], rated["fatigue"]))
    moods = summary(mood_links)
    # On a scale where 5 is good, stress rises with mood: flip it so higher means more stressed.
    flip = -1 if moods.get("median_rho", 0) > 0 else 1
    stressed = {n: flip * s for n, s in said.items()}

    def rating_link(metric: str, sign: int, rating: str, flipped: int) -> dict:
        """A night's measure against the same morning's rating, higher meaning better on both."""
        return summary(
            [
                spearman(sign * frames[n][metric], flipped * ratings_of[n][rating])
                for n in frames
                if metric in frames[n]
            ]
        )

    def against(metric: str, sign: int, lag: int) -> dict:
        return summary(
            [spearman(sign * frames[n][metric].shift(lag), stressed[n]) for n in frames]
        )

    report = {
        "people_loaded": len(frames),
        "people_with_enough_stress_scores": usable,
        "stress_score_days": int(sum(s.notna().sum() for s in built.values())),
        "scale": {
            "stress_with_mood": moods,
            "stress_with_fatigue": summary(fatigue_links),
            "read_as": "5 is relaxed" if flip == -1 else "5 is stressed",
        },
        "primary_previous_day_score_vs_morning_rating": against("stress_score", 1, 1),
        "same_day": against("stress_score", 1, 0),
        "simpler_signals_previous_day": {
            "resting_hr": against("resting_hr", 1, 1),
            "sleep_minutes_negated": against("sleep_minutes", -1, 1),
            "still_hr_above_resting": against("still_hr_above_resting", 1, 1),
            "strain": against("strain", 1, 1),
            "recovery_score_negated": against("recovery_score", -1, 1),
        },
        "other_areas_same_morning": {
            "sleep_minutes_vs_reported_hours": rating_link("sleep_minutes", 1, "sleep_duration_h", 1),
            "sleep_minutes_vs_sleep_quality": rating_link("sleep_minutes", 1, "sleep_quality", 1),
            "recovery_score_vs_readiness": rating_link("recovery_score", 1, "readiness", 1),
            "recovery_score_vs_fatigue_5_is_good": rating_link("recovery_score", 1, "fatigue", 1),
            "strain_day_before_vs_fatigue_5_is_good": summary(
                [spearman(-frames[n]["strain"].shift(1), ratings_of[n]["fatigue"]) for n in frames]
            ),
        },
        "one_team_week_by_week": team_by_week(
            {n: frames[n]["stress_score"].shift(1) for n in frames}, stressed
        ),
    }
    OUT.write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
