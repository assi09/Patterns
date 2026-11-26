"""Could the check-in rule find more without firing more? Candidate rules against `checkin-v1`.

Run from the repository root: `PYTHONPATH=backend:eval python eval/checkin_variants.py`.
Free, no model; prints counts and writes eval/results/checkin_variants_<date>.json. Production is
not changed: a candidate becomes a rule only by decision, under a new name, with its own tests.

Fixed before the first run:

- **Weeks** are those of `eval/checkin_real.py`: every 7 days from 35 days after a person's first
  day, the data cut as a sync would leave it, eligible as there.
- **Tuning set**: PMData (16) and the 30 LifeSnaps people of the evaluation. **Held out**: the
  other 21 LifeSnaps people, looked at once, after a candidate is chosen on the tuning set.
- **Budget**: a candidate is admissible when it fires on at most 1 in 200 eligible ordinary weeks
  of the tuning set (0.5%). The weeks are unlabelled, so a firing is counted, not called false.
- **Choice**: among admissible candidates, the one finding the most planted changes of
  90 minutes less sleep and 8 more resting beats in observable weeks of the tuning set; ties go to
  the fewer firings. Then 120/10 and the smaller sizes are reported, and "sleep alone" (120 min
  less sleep, nothing else) must stay at or near zero: one signal must not be enough.
- **Families** (from the literature: personal rolling baselines, persistence over days, more than
  one signal, resting heart rate the strongest single signal):
  A. today's rule with a smaller margin (`far` widths of the usual range), fewer days (`days`),
     and recovery counted or not as its own signal (it is partly computed from sleep);
  B. a week-level test per signal: the mean of the week's worn days against the person's 28 days
     before, in units of their day-to-day spread over the square root of the days observed (`z`),
     and at least the existing floor in size (45 min of sleep, 5 beats, 8 ms HRV, 15 stress
     points), on at least 4 observed worn days; 2 signals needed.
"""

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import real_data
from app.analysis.day import with_scores
from app.teams import checkin
from checkin_real import FIRST_CHECK, SIZES, SLEEP_ONLY, eligible, observable, planted

HERE = __import__("pathlib").Path(__file__).parent
BUDGET = 1 / 200
# "Sleep alone must stay at or near zero" (above), as a number. The first run stated the
# requirement here but did not apply it when choosing; its pick, which counts recovery (partly
# computed from sleep) as a second signal, fired on sleep alone in 48 of 332 weeks and was
# rejected. Applied from the second run on.
SLEEP_ALONE_MAX = 1 / 100
CHOOSE_AT = "90min_8bpm"
MIN_OBSERVED = 4


def _windows(today: date):
    days = pd.date_range(today - timedelta(days=checkin.WINDOW_DAYS - 1), today)
    start = days[0] - pd.Timedelta(days=checkin.BASELINE_DAYS)
    return days, start, days[0] - pd.Timedelta(days=1)


def days_far(far: float, need: int, recovery: bool):
    """Family A: today's rule with its margin, days and signal list as parameters."""

    def rule(frame: pd.DataFrame, today: date) -> bool:
        days, start, end = _windows(today)
        worn = checkin._worn(frame, days)
        if int(worn.sum()) < checkin.MIN_WORN:
            return False
        found = 0
        for metric, (direction, floor) in checkin.SIGNALS.items():
            if metric not in frame or (metric == "recovery_score" and not recovery):
                continue
            before = frame[metric].loc[start:end].dropna()
            if len(before) < checkin.MIN_BASELINE:
                continue
            low, high = float(before.quantile(0.25)), float(before.quantile(0.75))
            margin = max(far * (high - low), floor)
            values = frame[metric].reindex(days)[worn]
            hit = (
                values <= low - margin
                if direction == "down"
                else values >= high + margin
            )
            found += int(hit.sum()) >= need
        return found >= checkin.MIN_SIGNALS

    return rule


def week_z(z: float, recovery: bool):
    """Family B: the week's mean against the person's own 28 days, per signal."""

    def rule(frame: pd.DataFrame, today: date) -> bool:
        days, start, end = _windows(today)
        worn = checkin._worn(frame, days)
        if int(worn.sum()) < checkin.MIN_WORN:
            return False
        found = 0
        for metric, (direction, floor) in checkin.SIGNALS.items():
            if metric not in frame or (metric == "recovery_score" and not recovery):
                continue
            before = frame[metric].loc[start:end].dropna()
            values = frame[metric].reindex(days)[worn].dropna()
            if len(before) < checkin.MIN_BASELINE or len(values) < MIN_OBSERVED:
                continue
            spread = float(before.std(ddof=1))
            if not np.isfinite(spread) or spread == 0:
                continue
            gap = float(values.mean() - before.mean())
            worse = -gap if direction == "down" else gap
            found += worse >= floor and worse / (spread / np.sqrt(len(values))) >= z
        return found >= checkin.MIN_SIGNALS

    return rule


CANDIDATES = {"checkin-v1 (today)": checkin.detect}
for far in (1.0, 0.75, 0.5):
    for need in (5, 4):
        for recovery in (True, False):
            name = f"A far={far} days={need} recovery={'yes' if recovery else 'no'}"
            CANDIDATES[name] = days_far(far, need, recovery)
for z in (3.0, 4.0, 5.0, 6.0):
    for recovery in (True, False):
        CANDIDATES[f"B z={z} recovery={'yes' if recovery else 'no'}"] = week_z(
            z, recovery
        )

PLANTS = [f"{s}min_{r}bpm" for s, r in SIZES] + [f"sleep_only_{SLEEP_ONLY}min"]


def run(people: dict[str, pd.DataFrame]) -> dict:
    """Per candidate: firings on ordinary weeks, and planted changes found in observable weeks."""
    tally = {
        name: {"weeks": 0, "fired": 0} | {p: [0, 0] for p in PLANTS}
        for name in CANDIDATES
    }
    for raw in people.values():
        scored = with_scores(raw)
        today = raw.index.min().date() + timedelta(days=FIRST_CHECK)
        last = raw.index.max().date()
        while today <= last:
            cut = scored.loc[: pd.Timestamp(today)]
            if eligible(cut, today):
                raw_cut = raw.loc[: pd.Timestamp(today)]
                ordinary = {
                    name: bool(rule(cut, today)) for name, rule in CANDIDATES.items()
                }
                visible = observable(cut, today)
                plants = {}
                if visible:
                    for s, r in SIZES:
                        plants[f"{s}min_{r}bpm"] = planted(raw_cut, today, s, r)
                    plants[f"sleep_only_{SLEEP_ONLY}min"] = planted(
                        raw_cut, today, SLEEP_ONLY, 0
                    )
                for name, rule in CANDIDATES.items():
                    t = tally[name]
                    t["weeks"] += 1
                    t["fired"] += ordinary[name]
                    if ordinary[name]:
                        continue  # a week that already fired cannot show a planted change
                    for key, frame in plants.items():
                        t[key][0] += bool(rule(frame, today))
                        t[key][1] += 1
            today += timedelta(days=7)
    return tally


def merged(*tallies: dict) -> dict:
    out = {}
    for name in CANDIDATES:
        out[name] = {"weeks": 0, "fired": 0} | {p: [0, 0] for p in PLANTS}
        for t in tallies:
            out[name]["weeks"] += t[name]["weeks"]
            out[name]["fired"] += t[name]["fired"]
            for p in PLANTS:
                out[name][p][0] += t[name][p][0]
                out[name][p][1] += t[name][p][1]
    return out


def rate(pair) -> float:
    return pair[0] / pair[1] if pair[1] else 0.0


def main() -> None:
    lifesnaps = real_data.load_lifesnaps()
    chosen = real_data.choose_lifesnaps(lifesnaps)
    held = {k: v for k, v in lifesnaps.items() if k not in chosen}
    tuning = merged(run(real_data.load_pmdata()), run(chosen))
    sleep_alone = f"sleep_only_{SLEEP_ONLY}min"
    admissible = [
        n
        for n, t in tuning.items()
        if t["fired"] <= BUDGET * t["weeks"] and rate(t[sleep_alone]) <= SLEEP_ALONE_MAX
    ]
    pick = max(
        admissible, key=lambda n: (rate(tuning[n][CHOOSE_AT]), -tuning[n]["fired"])
    )
    held_out = run(held)
    show = lambda t: {
        "fired": f"{t['fired']}/{t['weeks']}",
        **{p: f"{t[p][0]}/{t[p][1]}" for p in PLANTS},
    }
    out = {
        "ran": date.today().isoformat(),
        "budget": "at most 1 firing per 200 eligible ordinary weeks of the tuning set",
        "sleep_alone_max": "at most 1 in 100 observable tuning weeks fire on sleep alone",
        "chosen_on_tuning": pick,
        "tuning": {name: show(t) for name, t in tuning.items()},
        "admissible": admissible,
        "held_out": {
            name: show(held_out[name]) for name in ("checkin-v1 (today)", pick)
        },
    }
    (HERE / "results" / f"checkin_variants_{date.today().isoformat()}.json").write_text(
        json.dumps(out, indent=2) + "\n"
    )
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
