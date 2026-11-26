"""Team statistics (docs/teams.md): calibration over many made-up teams, power, privacy floor."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.analysis import team
from app.analysis.team import (
    BASELINE_DAYS,
    MIN_MEMBERS,
    member_change,
    member_levels,
    team_change,
    team_statistics,
    week_of,
)
from app.synthetic import Step, generate

WEEK = week_of(date(2026, 10, 19))  # Monday 19 to Sunday 25 October
START = WEEK.start - timedelta(days=BASELINE_DAYS)
DAYS = BASELINE_DAYS + 7


def member(rng, shift_sd: float = 0.0, metric: str = "sleep_minutes") -> pd.DataFrame:
    """A made-up person: their own level and spread, days that follow on from each other (AR(1)),
    and the week moved by `shift_sd` of their own spread."""
    level, spread = rng.normal(420, 40), rng.uniform(15, 60)
    noise = np.empty(DAYS)
    noise[0] = rng.normal()
    for i in range(1, DAYS):
        noise[i] = 0.4 * noise[i - 1] + rng.normal() * np.sqrt(1 - 0.4**2)
    values = level + spread * noise
    values[-7:] += shift_sd * spread
    index = pd.date_range(START, periods=DAYS, freq="D")
    return pd.DataFrame({metric: values}, index=index)


def p_value(rng, members: int, shift_sd: float = 0.0) -> float:
    changes = [member_change(member(rng, shift_sd), "sleep_minutes", WEEK) for _ in range(members)]
    return team_change(changes, "sleep_minutes", WEEK).stats["p_value"]


def test_week_runs_monday_to_sunday():
    assert (WEEK.start.weekday(), WEEK.days) == (0, 7)
    assert week_of(date(2026, 10, 25)) == WEEK  # a Sunday belongs to the week before it


@pytest.mark.parametrize("members", [5, 8, 20])
def test_false_alarms_stay_near_alpha_when_nothing_changed(members):
    rng = np.random.default_rng(members)
    rate = np.mean([p_value(rng, members) < 0.05 for _ in range(600)])
    assert 0.02 <= rate <= 0.08, rate


def test_a_team_wide_shift_is_found_even_in_a_small_team():
    rng = np.random.default_rng(1)
    power_5 = np.mean([p_value(rng, 5, shift_sd=1.5) < 0.05 for _ in range(300)])
    power_10 = np.mean([p_value(rng, 10, shift_sd=1.0) < 0.05 for _ in range(300)])
    assert power_5 > 0.7 and power_10 > 0.8, (power_5, power_10)


def test_one_persons_scale_does_not_decide_the_team():
    # Four people unchanged and one person with a huge spread and a large raw change: in raw units
    # they would dominate a mean, in their own units they are one of five.
    rng = np.random.default_rng(3)
    changes = [member_change(member(rng), "sleep_minutes", WEEK) for _ in range(4)]
    changes.append(team.MemberChange(change=500.0, standardized=1.0))
    found = team_change(changes, "sleep_minutes", WEEK)
    assert found.stats["p_value"] > 0.05


def test_fewer_than_five_people_give_no_figures_at_all():
    rng = np.random.default_rng(4)
    changes = [
        member_change(member(rng, 2.0), "sleep_minutes", WEEK) for _ in range(MIN_MEMBERS - 1)
    ]
    found = team_change(changes, "sleep_minutes", WEEK)
    assert not found.sufficient
    assert set(found.stats) == {"members", "minimum_members"}  # no median, no counts
    frames = [member(rng) for _ in range(MIN_MEMBERS - 1)]
    assert team_statistics(frames, WEEK).changes == []


def test_a_member_with_too_little_data_is_left_out_not_guessed():
    rng = np.random.default_rng(5)
    frame = member(rng)
    sparse = frame.copy()
    sparse.iloc[-7:-3] = np.nan  # only three days of the week
    assert member_change(sparse, "sleep_minutes", WEEK) is None
    short = frame.iloc[-20:]  # thirteen days before the week
    assert member_change(short, "sleep_minutes", WEEK) is None
    assert member_change(frame, "steps", WEEK) is None  # no such column


def synthetic_team(size: int, effects=()) -> list[pd.DataFrame]:
    start = WEEK.start - timedelta(days=70)
    return [generate(start, 77, effects, seed=seed).frame for seed in range(size)]


def test_a_planted_team_change_is_reported_and_nothing_names_anyone():
    later_bedtimes = (Step("sleep_minutes", WEEK.start, -60),)
    result = team_statistics(synthetic_team(8, later_bedtimes), WEEK)
    assert result.members == 8 and len(result.changes) == len(team.TEAM_METRICS)
    sleep = next(e for e in result.changes if e.metrics == ("sleep_minutes",))
    assert sleep in result.changed
    assert sleep.stats["members_down"] >= 7 and sleep.stats["median_change"] < -30
    assert sleep.stats["metrics_tested"] == sum(e.sufficient for e in result.changes)
    for evidence in [*result.changes, *result.weekdays]:
        assert not any("member" in key and "id" in key for key in evidence.stats)
    weekday = result.weekdays[0]
    assert weekday.stats["descriptive"] is True and weekday.n >= MIN_MEMBERS


def test_levels_compare_a_week_with_the_persons_own_weeks_before():
    start = WEEK.start - timedelta(days=70)
    frame = generate(start, 77, (Step("sleep_minutes", WEEK.start, 120),), seed=9).frame
    levels = member_levels(frame, WEEK)
    assert set(levels) == set(team.LEVEL_METRICS)
    assert levels["sleep_minutes"].level == "above"
    assert levels["sleep_minutes"].mean > 0
    new = generate(WEEK.start - timedelta(days=10), 17, seed=9).frame
    assert member_levels(new, WEEK)["sleep_minutes"].level is None  # no earlier weeks yet


# A hand-calculated fixture for the exact 4-to-5 boundary, metric by metric (C9 evaluation audit,
# 2026-11-26). Each person's 28 days before alternate between two values, so the mean and spread
# are known; each week is a constant, so each person's change is known; the team figure is the
# median of those changes.


def _fixed(before: tuple[float, float], week: float, metric: str) -> pd.Series:
    days = [before[i % 2] for i in range(BASELINE_DAYS)] + [week] * 7
    return pd.Series(days, index=pd.date_range(START, periods=DAYS, freq="D"), name=metric)


def test_a_metric_is_reported_at_five_people_and_withheld_at_four_on_its_own():
    # Five people with steps; only four of them with sleep (the fifth's nights are missing).
    step_changes = [1000.0, 1500.0, 2000.0, 2500.0, 3000.0]  # median 2000
    frames = []
    for i, change in enumerate(step_changes):
        steps = _fixed((7000.0, 9000.0), 8000.0 + change, "steps")  # usual mean 8000
        sleep = _fixed((400.0, 440.0), 420.0 - 30.0, "sleep_minutes")  # every one 30 min less
        if i == 4:
            sleep[:] = np.nan  # missing, not zero: this person adds nothing to sleep
        frames.append(pd.concat([steps, sleep], axis=1))
    found = {e.metrics[0]: e for e in team_statistics(frames, WEEK).changes}
    assert found["steps"].sufficient and found["steps"].n == 5
    assert found["steps"].stats["median_change"] == 2000.0
    assert found["steps"].stats["members_up"] == 5
    assert not found["sleep_minutes"].sufficient and found["sleep_minutes"].n == 4
    assert set(found["sleep_minutes"].stats) == {"members", "minimum_members"}
    # A fifth sleeper makes sleep reportable, with the hand-calculated figure.
    frames[4]["sleep_minutes"] = _fixed((400.0, 440.0), 390.0, "sleep_minutes")
    found = {e.metrics[0]: e for e in team_statistics(frames, WEEK).changes}
    assert found["sleep_minutes"].sufficient and found["sleep_minutes"].n == 5
    assert found["sleep_minutes"].stats["median_change"] == -30.0
    assert found["sleep_minutes"].stats["members_down"] == 5
