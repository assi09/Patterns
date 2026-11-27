"""What followed a team change is named without a judgement (app.teams.outcome)."""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from app.analysis.screen import FDR
from app.teams import outcome, playbook

START, END = date(2026, 10, 5), date(2026, 10, 18)
WORDS = ("better", "worse", "worked", "improv", "returned", "back to", "normal")


def record(sufficient=True, median=12.0, p=0.01, members=6, up=5, down=1) -> dict:
    stats = {"members": members}
    if sufficient:
        stats |= {"median_change": median, "p_value": p, "members_up": up, "members_down": down}
    return {
        "id": "e1",
        "tool": "team_change",
        "metrics": ["sleep_minutes"],
        "windows": [
            {"start": "2026-10-05", "end": "2026-10-18"},
            {"start": "2026-09-07", "end": "2026-10-04"},
        ],
        "n": members,
        "sufficient": sufficient,
        "stats": stats,
    }


def change(metric="sleep_minutes"):
    return SimpleNamespace(metric=metric, starts_on=START, ends_on=END)


@pytest.mark.parametrize(
    "found, expected",
    [
        (record(median=30), "above"),
        (record(median=-30), "below"),
        (record(median=30, p=FDR), "no_clear_difference"),
        (record(median=0, p=0.001), "no_clear_difference"),
        (record(sufficient=False, members=3), "insufficient_data"),
    ],
)
def test_four_outcomes(found, expected):
    assert outcome.outcome_of(found) == expected
    described = outcome.describe(change(), found)
    assert described["outcome"] == expected and described["label"] == outcome.OUTCOMES[expected]
    assert all(word not in described["text"].lower() for word in WORDS)
    assert described["caveats"] == [outcome.CONTRIBUTION, outcome.REBOUND]


def test_a_lower_resting_heart_rate_is_below_not_better():
    found = record(median=-3, p=0.001)
    found["metrics"] = ["resting_hr"]
    described = outcome.describe(change("resting_hr"), found)
    assert described["outcome"] == "below" and "below the reference level" in described["text"]


def test_the_reference_dates_are_the_records_own():
    described = outcome.describe(change(), record())
    assert described["reference"] == {
        "kind": "before_the_change",
        "label": "the 28 days before the change started",
        "start": "2026-09-07",
        "end": "2026-10-04",
    }
    assert "Sep 7, 2026 to Oct 4, 2026" in described["text"]
    assert described["difference"] == "+12 min" and described["contributors"] == 6


def test_insufficient_data_gives_no_figure():
    described = outcome.describe(change(), record(sufficient=False, members=4))
    assert "difference" not in described and "higher" not in described
    assert described["text"] == "Time asleep: insufficient data (4 people with data; 5 needed)."


@pytest.mark.parametrize("metric", ["sleep_minutes", "steps", "resting_hr", "meeting_minutes"])
def test_a_stored_result_keeps_its_meaning(metric):
    """Every earlier verdict maps to the same finding under the new words: the same comparison and
    the same test, so nothing stored changes meaning, only how it is said."""
    rng = np.random.default_rng(7)
    moved = {"above", "below"}
    same = {"better": moved, "worse": moved, "changed": moved}
    same |= {"no_change": {"no_clear_difference"}, "unclear": {"insufficient_data"}}
    for _ in range(400):
        found = record(
            sufficient=bool(rng.random() > 0.15),
            median=float(rng.choice([0.0, rng.normal(0, 40)])),
            p=float(rng.uniform(0, 0.2)),
        )
        found["metrics"] = [metric]
        old = playbook.verdict(change(metric), _evidence(found))["verdict"]
        assert outcome.outcome_of(found) in same[old]


def _evidence(found: dict):
    from app.analysis.evidence import Evidence

    return Evidence.model_validate(found)
