"""Counts use the comparison the question states (the audit of 2026-11-18): "strictly above
11,243" counted with >= gave five days instead of four, and the inclusive answer then said no day
equalled 11,243 when one did."""

from datetime import date

import pandas as pd
import pytest

from app.agent.verifier import asked_comparison, comparison_problems
from app.analysis.evidence import ToolError, Window
from app.analysis.habits import goal_progress

WEEK = Window(start=date(2026, 11, 11), end=date(2026, 11, 17))
# Seven made-up days: four strictly above 11,243, exactly one equal to it.
STEPS = [12_000, 11_243, 9_000, 15_500, 11_244, 8_100, 13_000]


@pytest.fixture
def frame():
    days = pd.date_range("2026-11-11", periods=7, freq="D")
    return pd.DataFrame({"steps": STEPS}, index=days)


@pytest.mark.parametrize(
    "direction, met",
    [("above", 4), ("at_least", 5), ("exactly", 1), ("below", 2), ("at_most", 3)],
)
def test_each_comparison_counts_exactly(frame, direction, met):
    found = goal_progress(frame, "steps", 11_243, direction, WEEK)
    assert found.stats["days_met"] == met and found.stats["days_equal"] == 1


def test_an_unknown_comparison_is_refused(frame):
    with pytest.raises(ToolError):
        goal_progress(frame, "steps", 11_243, "around", WEEK)


@pytest.mark.parametrize(
    "question, wanted",
    [
        ("How many days were strictly above 11,243 steps, not counting equal days?", "above"),
        ("How many days had more than 10,000 steps?", "above"),
        ("How many days had at least 11,243 steps?", "at_least"),
        ("Days with 10,000 steps or more?", "at_least"),
        ("How many nights did I sleep less than 7 hours?", "below"),
        ("Nights with at most 6 hours?", "at_most"),
        ("How many days over 10k?", None),  # unclear: left to the model
    ],
)
def test_the_question_s_own_comparison_is_read(question, wanted):
    assert asked_comparison(question) == wanted


def test_a_count_with_the_wrong_comparison_is_sent_back(frame):
    inclusive = goal_progress(frame, "steps", 11_243, "at_least", WEEK)
    question = "How many days were strictly above 11,243 steps?"
    assert comparison_problems(question, "Five days.", [inclusive])
    strict = goal_progress(frame, "steps", 11_243, "above", WEEK)
    assert comparison_problems(question, "Four days.", [inclusive, strict]) == []


def test_saying_no_day_equalled_it_when_one_did_is_sent_back(frame):
    inclusive = goal_progress(frame, "steps", 11_243, "at_least", WEEK)
    summary = "Five days reached 11,243 steps; no day had exactly 11,243."
    assert comparison_problems("At least 11,243 steps?", summary, [inclusive])
