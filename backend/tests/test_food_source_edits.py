"""Food follow-ups change the records, nutrient or meal they say, against the same opening.

The audit of 910da27 (pr-195-followup-issues.md item 4): after a breakfast-energy answer, "remove
the meal restriction and total recorded protein" was refused as an unknown measure (protein named
as a tracker metric), and "same date, switch to energy burned from the tracker" was sent back
twice (a redo could not say which records it reads).
"""

from datetime import date

import pytest
from test_clauses import SAME, data, read, redo, said

from app.agent.context import Turn

TODAY = date(2026, 11, 2)
DAY = (date(2026, 10, 31), date(2026, 10, 31))
BREAKFAST = Turn(
    "Read confirmed breakfast energy for October 31, 2026.",
    "Energy consumed: 327 kcal.",
    request_state={
        "last": "data",
        "data": [
            {
                "metrics": ["food_logs"],
                "operation": "food",
                "windows": [{"start": "2026-10-31", "end": "2026-10-31"}],
                "meal_type": "BREAKFAST",
                "nutrients": ["energy"],
            }
        ],
        "answer": {"kind": "data", "parts": 1, "reads": 0},
    },
)


def part_of(words, clause):
    request, _ = read(words, said(clause), history=[BREAKFAST], today=TODAY)
    assert request.kind == "data", request.clarification
    (part,) = request.parts
    return part, [(w.start, w.end) for w in part.windows]


@pytest.mark.parametrize("source", ["tracker", "food_log"])
def test_whole_day_protein_is_read_from_the_food_log_however_the_source_was_said(source):
    words = "For the identical date, remove the meal restriction and total recorded protein."
    clause = data(words, ["protein"], "sum", SAME, earlier_result=0, source=source)
    part, days = part_of(words, clause)
    assert (part.operation, part.nutrients, part.meal_type, days) == (
        "food",
        ["protein"],
        None,
        [DAY],
    )


def test_the_same_edit_said_as_a_redo_is_read_the_same():
    words = "Same day, but protein for every meal."
    part, days = part_of(words, redo(words, SAME, metrics=["protein"]))
    assert (part.operation, part.nutrients, part.meal_type, days) == (
        "food",
        ["protein"],
        None,
        [DAY],
    )


def test_a_redo_can_switch_to_energy_burned_from_the_tracker():
    words = "Same date, switch to energy burned from the tracker."
    part, days = part_of(words, redo(words, SAME, metrics=["calories"], source="tracker"))
    assert (part.metrics, part.operation, days) == (["calories"], "value", [DAY])


def test_a_redo_that_says_no_source_keeps_the_food_log():
    words = "Same thing again, please."
    part, days = part_of(words, redo(words, SAME))
    assert part.operation == "food" and days == [DAY]


def test_calories_named_for_the_tracker_are_the_trackers_not_food():
    """Calories is a tracker measure too, so it is never taken as food on its own."""
    words = "And calories burned that day?"
    part, _ = part_of(words, data(words, ["calories"], "inherit", SAME, earlier_result=0))
    assert part.metrics == ["calories"] and part.operation != "food"


def test_food_and_tracker_measures_in_one_clause_are_still_split():
    words = "Protein and steps for that day."
    clause = data(words, ["protein", "steps"], "sum", SAME, earlier_result=0, source="tracker")
    request, _ = read(words, said(clause), history=[BREAKFAST], today=TODAY)
    assert request.kind == "clarify"  # one clause per source; never protein from the tracker
