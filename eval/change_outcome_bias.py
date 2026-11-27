"""Does a team change's outcome call recovery from a dip "better"? (step 0, docs/change-memory.md)

A supervisor usually starts a change right after a report shows a drop. If the drop was temporary,
the team recovers on its own, and a measure that compares the change's days with the 28 days just
before it (which hold the drop) can call the change "better" when it did nothing. This simulation
counts how often that happens, for the measure in use (`playbook.verdict` on `challenge_result`) and
for one alternative: the 28 days before the drop was first flagged.

Synthetic data only (app.synthetic), so the truth is known; no research data, no paid API, $0.
Run: PYTHONPATH=backend python eval/change_outcome_bias.py [teams per cell]
"""

import json
import sys
from collections import Counter
from datetime import date, timedelta
from functools import cache
from types import SimpleNamespace

import numpy as np
from app.analysis.evidence import Window
from app.analysis.screen import FDR
from app.analysis.team import member_change, prepare, team_change
from app.synthetic import BASELINES, generate
from app.teams.playbook import verdict

START = date(2026, 1, 5)  # a Monday
WEEKS = 20
DAYS = WEEKS * 7
CHANGE_DAYS = 14  # a playbook change's usual length
BAD = {"sleep_minutes": "down", "steps": "down"}
NOISES = ("independent", "personal_drift", "shared_weeks")
SCENARIOS = (
    (
        "random_start",
        None,
        0.0,
    ),  # no drop, no effect: the measure's own false "better" rate
    (
        "after_chance_drop",
        None,
        0.0,
    ),  # started after a flagged drop that was only noise
    ("after_2_week_dip", 2, 0.0),  # a real two-week team dip that ends on its own
    ("after_3_week_dip", 3, 0.0),
    (
        "after_2_week_dip_real_effect",
        2,
        0.5,
    ),  # and a change that truly helps, by 0.5 SD
)
DIP_SD = 0.9  # the dip's size, in the metric's daily SDs
EFFECT_SD_LABEL = "0.5 daily SD"


def week(i: int) -> Window:
    start = START + timedelta(days=7 * i)
    return Window(start=start, end=start + timedelta(days=6))


@cache
def member(seed: int):
    return prepare(generate(START, DAYS, seed=seed).frame)


def team(
    rng: np.random.Generator, size: int, metric: str, noise: str, seed: int
) -> list:
    """Prepared frames for a team, with the noise model added to `metric`."""
    sd = BASELINES[metric].sd
    shared = (
        np.repeat(rng.normal(0, 0.3 * sd, WEEKS), 7) if noise == "shared_weeks" else 0.0
    )
    frames = []
    for k in range(size):
        frame = member(seed * 100 + k).copy()  # the same people in every cell
        extra = np.zeros(DAYS)
        if (
            noise == "personal_drift"
        ):  # a slow personal wander: AR(1), phi 0.9, stationary 0.5 SD
            level = rng.normal(0, 0.5 * sd)
            for t in range(DAYS):
                level = 0.9 * level + rng.normal(0, 0.5 * sd * np.sqrt(1 - 0.81))
                extra[t] = level
        frame[metric] = frame[metric] + extra + shared
        frames.append(frame)
    return frames


def shift(frames: list, metric: str, start: date, days: int, by: float) -> None:
    for frame in frames:
        span = (frame.index >= np.datetime64(start)) & (
            frame.index <= np.datetime64(start + timedelta(days=days - 1))
        )
        frame.loc[span, metric] = frame.loc[span, metric] + by


def measured(frames: list, metric: str, window: Window, baseline: Window | None = None):
    changes = [member_change(f, metric, window, baseline) for f in frames]
    return team_change([c for c in changes if c is not None], metric, window)


def flagged(frames: list, metric: str, i: int) -> bool:
    e = measured(frames, metric, week(i))
    if not e.sufficient or e.stats["p_value"] >= FDR:
        return False
    return (e.stats["median_change"] < 0) == (BAD[metric] == "down")


def trigger(frames: list, metric: str, first: int, last: int) -> tuple[int, int] | None:
    """The first two flagged weeks running (a "Sustained change"): (first flagged, second)."""
    previous = False
    for i in range(first, last + 1):
        now = flagged(frames, metric, i)
        if now and previous:
            return i - 1, i
        previous = now
    return None


def one(
    metric: str, noise: str, scenario: str, dip: int | None, effect: float, seed: int
):
    rng = np.random.default_rng(seed)
    sd = BASELINES[metric].sd
    frames = team(rng, int(rng.choice([5, 6, 8])), metric, noise, seed)
    action = SimpleNamespace(metric=metric)
    if scenario == "random_start":
        start = week(int(rng.integers(5, WEEKS - 3))).start
        window = Window(start=start, end=start + timedelta(days=CHANGE_DAYS - 1))
        return {"current": verdict(action, measured(frames, metric, window))["verdict"]}
    if dip is not None:
        onset = int(rng.integers(6, 11))
        shift(frames, metric, week(onset).start, 7 * dip, -DIP_SD * sd)
        found = trigger(frames, metric, onset, onset + dip + 1)
    else:
        found = trigger(frames, metric, 5, WEEKS - 4)
    if found is None:
        return None  # nothing flagged: no supervisor would have started a change
    first, second = found
    start = week(second).end + timedelta(days=1)  # the Monday the report shows it
    if effect:
        shift(frames, metric, start, CHANGE_DAYS, effect * sd)
    window = Window(start=start, end=start + timedelta(days=CHANGE_DAYS - 1))
    before_drop = Window(
        start=week(first).start - timedelta(days=28),
        end=week(first).start - timedelta(1),
    )
    return {
        "current": verdict(action, measured(frames, metric, window))["verdict"],
        "before_drop": verdict(action, measured(frames, metric, window, before_drop))[
            "verdict"
        ],
    }


def main(teams: int) -> dict:
    cells = []
    for metric in BAD:
        for noise in NOISES:
            for scenario, dip, effect in SCENARIOS:
                counts = {"current": Counter(), "before_drop": Counter()}
                started = 0
                for seed in range(teams):
                    out = one(metric, noise, scenario, dip, effect, seed)
                    if out is None:
                        continue
                    started += 1
                    for measure, word in out.items():
                        counts[measure][word] += 1
                cell = {
                    "metric": metric,
                    "noise": noise,
                    "scenario": scenario,
                    "teams_simulated": teams,
                    "changes_started": started,
                }
                for measure, c in counts.items():
                    if c:
                        cell[measure] = {
                            w: round(n / started, 3) for w, n in sorted(c.items())
                        }
                cells.append(cell)
                print(json.dumps(cell))
    return {
        "question": "How often does a change's outcome say 'better' when the change did nothing?",
        "measures": {
            "current": "the change's days against the 28 days just before it (in use)",
            "before_drop": "the change's days against the 28 days before the drop was first flagged",
        },
        "trigger": "two flagged weeks running (p < FDR, median in the bad direction); the change "
        f"starts the Monday after, for {CHANGE_DAYS} days",
        "dip": f"every member {DIP_SD} daily SD lower for the dip's weeks, then back",
        "real_effect": f"every member {EFFECT_SD_LABEL} higher during the change",
        "noise": {
            "independent": "independent days (app.synthetic)",
            "personal_drift": "plus a slow personal wander (AR(1), phi 0.9, 0.5 SD)",
            "shared_weeks": "plus a team-wide weekly shift (SD 0.3), like deadlines and holidays",
        },
        "team_sizes": [5, 6, 8],
        "cells": cells,
    }


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    result = main(n)
    out = "eval/results/change_outcome_bias_2026-11-27.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=1)
    print("written", out)
