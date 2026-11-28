"""How often the weekly team report says a metric changed, on real people: when nothing was
planted, when the days were shuffled so nothing can have changed, and when a known change was
planted. By team size. Free, no model.

Run from the repository root:
    PYTHONPATH=backend:eval python eval/report_power_real.py

The report's "changed" is `team.team_statistics(...).changed`: a one-sample t-test on each
member's standardized change from their own 28 days before, adjusted for the 9 metrics tested
(Benjamini-Hochberg at 0.05), from at least 5 people. This calls that function on the same days
the report reads (70 days before the week to its end), so what it measures is the report's own
decision, not a copy of it.

Fixed before the first run (2026-11-28), on the teams frozen by `eval/varied_teams.py` (hashes
checked first). Only teams of 5 or more can have a figure: LifeSnaps 5, 6, 9, 11 and 13, and
PMData 5 and 6; every week of the frozen spec.

- **Ordinary weeks**: the data as recorded. These weeks are not labelled (a holiday is a real
  change), so this is a firing rate, not a false-alarm rate.
- **Shuffled weeks, the null**: for each team-week and each of `SHUFFLES` seeds, each member's
  35 days (the week and the 28 before) are shuffled day by day, every metric of a day together,
  so the week cannot differ from the days before except by chance; days further back stay as
  they are. The report should then flag any metric in at most about 5% of team-weeks
  (Benjamini-Hochberg bounds the false discovery rate at 0.05, and with nothing true every
  discovery is false), and the pass mark is fixed at 7.5% so chance does not fail it.
- **Planted changes**: added to every member's existing values on every day of the week (a
  missing day stays missing): time asleep -30, -45, -60 and -90 min; -60 min in half the members
  (the first half of the sorted ids, rounded up); steps -1,500 and -3,000; resting heart rate
  +2 and +4 bpm. Found when the planted metric is in the report's changed list, moving the
  planted way. Counted over all weeks, and over weeks where that metric had a figure as
  recorded. Other metrics newly flagged beside a plant are counted too (recovery is partly
  computed from sleep and resting heart rate, so it may follow them).

Writes aggregates to `eval/results/report_power_real_<date>.json`; nothing per person.
Exits 1 if the null rate is above the pass mark.
"""

import json
import math
import random
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import varied_teams as vt

from app.analysis import team

HERE = Path(__file__).parent
SEED = 20261128
SHUFFLES = 5
NULL_PASS = 0.075
HISTORY = 70
PLANTS = {
    "sleep -30": ("sleep_minutes", -30, "all"),
    "sleep -45": ("sleep_minutes", -45, "all"),
    "sleep -60": ("sleep_minutes", -60, "all"),
    "sleep -90": ("sleep_minutes", -90, "all"),
    "sleep -60, half the team": ("sleep_minutes", -60, "half"),
    "steps -1500": ("steps", -1500, "all"),
    "steps -3000": ("steps", -3000, "all"),
    "resting HR +2": ("resting_hr", 2, "all"),
    "resting HR +4": ("resting_hr", 4, "all"),
}


def window(frame: pd.DataFrame, week) -> pd.DataFrame:
    lo = pd.Timestamp(week.start - timedelta(days=HISTORY))
    return frame.loc[lo : pd.Timestamp(week.end)]


def flagged(frames: list[pd.DataFrame], week) -> dict[str, float]:
    """The report's changed metrics, each with its median change."""
    stats = team.team_statistics(frames, week)
    return {e.metrics[0]: e.stats["median_change"] for e in stats.changed}


def sufficient(frames: list[pd.DataFrame], week) -> set[str]:
    stats = team.team_statistics(frames, week)
    return {e.metrics[0] for e in stats.changes if e.sufficient}


def shuffled(frame: pd.DataFrame, week, rng: random.Random) -> pd.DataFrame:
    lo = pd.Timestamp(week.start - timedelta(days=team.BASELINE_DAYS))
    hi = pd.Timestamp(week.end)
    out = frame.copy()
    days = list(out.loc[lo:hi].index)
    order = days[:]
    rng.shuffle(order)
    out.loc[days] = frame.loc[order].to_numpy()
    return out


def planted(frame: pd.DataFrame, week, metric: str, delta: float) -> pd.DataFrame:
    out = frame.copy()
    if metric not in out:
        return out
    lo, hi = pd.Timestamp(week.start), pd.Timestamp(week.end)
    values = out.loc[lo:hi, metric] + delta
    out.loc[lo:hi, metric] = values.clip(lower=1) if metric == "sleep_minutes" else values
    return out


def main() -> None:
    data = vt.people()
    spec, teams = vt._check_frozen(data)
    rng = random.Random(SEED)
    ordinary: dict[str, Counter] = defaultdict(Counter)
    null: dict[str, Counter] = defaultdict(Counter)
    found: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    spill: dict[str, Counter] = defaultdict(Counter)
    for name, ids in sorted(teams.items()):
        if len(ids) < team.MIN_MEMBERS:
            continue
        dataset = name.split("-")[0]
        size = f"{len(ids)} ({dataset})"
        frames = [data[dataset][p] for p in sorted(ids)]
        for start in spec["weeks"][dataset]:
            week = team.week_of(date.fromisoformat(start))
            base = [window(f, week) for f in frames]
            as_is = flagged(base, week)
            ready = sufficient(base, week)
            ordinary[size]["team_weeks"] += 1
            ordinary[size]["any_flag"] += bool(as_is)
            for metric in as_is:
                ordinary[size][metric] += 1
            for _ in range(SHUFFLES):
                got = flagged([shuffled(f, week, rng) for f in base], week)
                null[size]["runs"] += 1
                null[size]["any_flag"] += bool(got)
                for metric in got:
                    null[size][metric] += 1
            for label, (metric, delta, who) in PLANTS.items():
                half = math.ceil(len(base) / 2)
                changed = [
                    planted(f, week, metric, delta) if who == "all" or i < half else f
                    for i, f in enumerate(base)
                ]
                got = flagged(changed, week)
                hit = metric in got and (got[metric] > 0) == (delta > 0)
                tally = found[label][size]
                tally["weeks"] += 1
                tally["found"] += hit
                if metric in ready:
                    tally["observable"] += 1
                    tally["found_observable"] += hit
                for other in set(got) - set(as_is) - {metric}:
                    spill[label][other] += 1
        print(f"{name}: {len(spec['weeks'][dataset])} weeks", flush=True)

    def rate(a: int, b: int) -> str:
        return f"{a}/{b} ({100 * a / b:.1f}%)" if b else "0/0"

    null_runs = sum(c["runs"] for c in null.values())
    null_any = sum(c["any_flag"] for c in null.values())
    out = {
        "spec_sha256": vt._hash(spec),
        "shuffles_per_team_week": SHUFFLES,
        "ordinary": {
            s: {"any_flag": rate(c["any_flag"], c["team_weeks"])}
            | {m: c[m] for m in team.TEAM_METRICS if c[m]}
            for s, c in ordinary.items()
        },
        "null": {
            s: {"any_flag": rate(c["any_flag"], c["runs"])}
            | {m: c[m] for m in team.TEAM_METRICS if c[m]}
            for s, c in null.items()
        },
        "null_overall": rate(null_any, null_runs),
        "null_pass_mark": NULL_PASS,
        "null_passed": null_any / null_runs <= NULL_PASS,
        "planted": {
            label: {
                s: {
                    "all_weeks": rate(c["found"], c["weeks"]),
                    "observable_weeks": rate(c["found_observable"], c["observable"]),
                }
                for s, c in by_size.items()
            }
            for label, by_size in found.items()
        },
        "also_flagged_beside_a_plant": {k: dict(v) for k, v in spill.items()},
        "commit": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], check=False, capture_output=True, text=True
        ).stdout.strip(),
    }
    path = HERE / "results" / f"report_power_real_{date.today().isoformat()}.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({"null_overall": out["null_overall"], "null_passed": out["null_passed"]}))
    print("written", path)
    sys.exit(0 if out["null_passed"] else 1)


if __name__ == "__main__":
    main()
