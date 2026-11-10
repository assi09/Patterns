"""The Monday check across every area: calibration over many made-up teams, power and privacy."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.analysis.team import (
    BASELINE_DAYS,
    MIN_MEMBERS,
    SCAN_WEEKS,
    TEAM_METRICS,
    team_participation,
    team_scan,
    week_of,
)

LAST = week_of(date(2026, 10, 19))
FIRST = LAST.start - timedelta(days=7 * (SCAN_WEEKS - 1))
START = FIRST - timedelta(days=BASELINE_DAYS)
DAYS = (LAST.end - START).days + 1
PLAIN = [m for m in TEAM_METRICS if m not in ("recovery_score", "strain", "stress_score")]


def member(rng, shifts: dict[str, tuple[float, int]] | None = None) -> pd.DataFrame:
    """A made-up person with their own level and spread and days that follow on from each other.
    `shifts` moves a metric by that many of the person's spreads over the last so many weeks."""
    index = pd.date_range(START, periods=DAYS, freq="D")
    columns = {}
    for metric in PLAIN:
        level, spread = rng.normal(100, 20), rng.uniform(5, 15)
        noise = np.empty(DAYS)
        noise[0] = rng.normal()
        for i in range(1, DAYS):
            noise[i] = 0.4 * noise[i - 1] + rng.normal() * np.sqrt(1 - 0.4**2)
        values = level + spread * noise
        if shifts and metric in shifts:
            size, weeks = shifts[metric]
            values[-7 * weeks :] += size * spread
        columns[metric] = values
    return pd.DataFrame(columns, index=index)


def team(seed: int, size: int, shifts=None) -> list[pd.DataFrame]:
    rng = np.random.default_rng(seed)
    return [member(rng, shifts) for _ in range(size)]


def test_a_team_where_nothing_changed_rarely_shows_a_lasting_change():
    alarms = [bool(team_scan(team(s, 8), LAST).lasting) for s in range(200)]
    assert sum(alarms) / len(alarms) < 0.08


def test_a_lasting_drop_in_sleep_is_found_and_said_to_be_lasting():
    found = 0
    for seed in range(60):
        hits = [
            e
            for e in team_scan(team(seed, 10, {"sleep_minutes": (-1.2, 3)}), LAST).lasting
            if e.metrics == ("sleep_minutes",)
        ]
        found += bool(hits) and hits[0].stats["direction"] == "down"
    assert found / 60 >= 0.8


def test_one_bad_week_is_new_and_not_lasting():
    scan = team_scan(team(4, 12, {"sleep_minutes": (-1.8, 1)}), LAST)
    sleep = next(e for e in scan.metrics if e.metrics == ("sleep_minutes",))
    assert sleep.stats["status"] == "new" and sleep.stats["weeks_running"] == 1


def test_changes_in_several_areas_are_found_together():
    shifts = {"sleep_minutes": (-1.4, 3), "resting_hr": (1.4, 3), "steps": (-1.4, 3)}
    moving = team_scan(team(7, 12, shifts), LAST).areas
    assert {"sleep", "recovery", "activity"} <= set(moving)
    assert "sleep_minutes" in moving["sleep"] and "resting_hr" in moving["recovery"]


def test_a_lasting_change_is_not_absorbed_by_its_own_baseline():
    scan = team_scan(team(9, 12, {"steps": (1.5, 4)}), LAST)
    steps = next(e for e in scan.metrics if e.metrics == ("steps",))
    assert steps.stats["weeks_running"] == SCAN_WEEKS


def test_nothing_is_built_from_fewer_than_the_floor_of_people():
    assert team_scan(team(1, MIN_MEMBERS - 1), LAST).metrics == []
    assert team_participation(team(1, MIN_MEMBERS - 1), LAST) is None


def test_a_week_with_too_few_people_carries_no_figures():
    frames = team(2, 6)
    for frame in frames[:2]:  # only four people have data in the latest week
        frame.loc[pd.Timestamp(LAST.start) :, "sleep_minutes"] = np.nan
    sleep = next(e for e in team_scan(frames, LAST).metrics if e.metrics == ("sleep_minutes",))
    latest = sleep.stats["weeks"][-1]
    assert latest == {
        "start": LAST.start.isoformat(),
        "end": LAST.end.isoformat(),
        "enough_people": False,
    }


def test_evidence_holds_only_aggregates():
    allowed = {
        "start",
        "end",
        "members",
        "median_change",
        "members_up",
        "members_down",
        "changed",
        "direction",
        "enough_people",
    }
    for evidence in team_scan(team(3, 8), LAST).metrics:
        for week in evidence.stats["weeks"]:
            assert set(week) <= allowed


def test_participation_is_only_a_count():
    frames = team(5, 6)
    frames[0].loc[pd.Timestamp(LAST.start) :, ["sleep_minutes"]] = np.nan
    evidence = team_participation(frames, LAST)
    assert evidence.stats == {"members": 6, "with_enough_data": 6}  # steps still count them
