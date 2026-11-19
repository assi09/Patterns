"""A follow-up keeps or shifts the active query's days as the words say, read by code (the audit of
2026-11-19: the state held the right days and the model's reading replaced them). Made-up data."""

from datetime import date

import pytest

from app.agent.requests import Part, Period, Reading, anchored_by_code, resolve, shift_said

TODAY = date(2026, 11, 19)

AWAITING = pytest.mark.xfail(
    reason="phrase overrides removed; awaiting validate-and-retry (Codex review, 2026-11-19)",
    strict=True,
)


def state(start, end, operation="value", metric="resting_hr"):
    window = {"start": start, "end": end}
    return {"data": [{"metrics": [metric], "operation": operation, "windows": [window]}]}


def read(question, period, operation="value", metrics=("resting_hr",), held=None):
    reading = Reading(
        kind="data",
        parts=[Part(metrics=list(metrics), operation=operation, periods=[period])],
    )
    request = resolve(anchored_by_code(reading, question, TODAY), held or {}, TODAY)
    window = request.parts[0].windows[0]
    return window.start, window.end


WRONG = Period(kind="explicit", start=date(2026, 10, 19), end=date(2026, 10, 19))


@AWAITING
def test_keep_that_same_date_keeps_the_latest_date_not_an_older_one():
    """Oct 19 and Oct 20 have the same value here: only the date shows the difference."""
    held = state("2026-10-20", "2026-10-20")
    question = "Keep that same date, and say the date explicitly even if the value was unchanged."
    assert read(question, WRONG, held=held) == (date(2026, 10, 20), date(2026, 10, 20))


@AWAITING
def test_two_days_forward_across_a_leap_day():
    held = state("2024-02-28", "2024-02-28", metric="sleep_minutes")
    wrong = Period(kind="explicit", start=date(2024, 3, 2), end=date(2024, 3, 2))
    got = read(
        "Move forward two days from the date you just answered.",
        wrong,
        metrics=("sleep_minutes",),
        held=held,
    )
    # A written-out date is read as written; this question has none, so code shifts the state.
    assert got == (date(2024, 3, 1), date(2024, 3, 1))


@AWAITING
def test_for_that_interval_keeps_the_whole_interval():
    held = state("2026-12-31", "2027-01-03", operation="mean", metric="steps")
    wrong = Period(kind="explicit", start=date(2027, 1, 3), end=date(2027, 1, 3))
    got = read(
        "For that interval, what was the smallest daily count?",
        wrong,
        operation="min",
        metrics=("steps",),
        held=held,
    )
    assert got == (date(2026, 12, 31), date(2027, 1, 3))


@AWAITING
def test_moving_a_stretch_shifts_both_ends():
    held = state("2026-11-09", "2026-11-16", operation="median", metric="recovery_score")
    unchanged = Period(kind="inherit")
    got = read(
        "Move that entire stretch two days earlier and give its middle value again.",
        unchanged,
        operation="median",
        metrics=("recovery_score",),
        held=held,
    )
    assert got == (date(2026, 11, 7), date(2026, 11, 14))


@pytest.mark.parametrize(
    "question, days",
    [
        ("Move that entire stretch two days earlier", -2),
        ("Move forward two days from the date you just answered", 2),
        ("go back 3 days", -3),
        ("and one day later?", 1),
        ("What about last week?", None),
    ],
)
def test_the_shift_is_read_from_the_words(question, days):
    assert shift_said(question) == days


def test_a_written_date_is_never_overridden():
    held = state("2026-10-20", "2026-10-20")
    period = Period(kind="explicit", start=date(2026, 10, 5), end=date(2026, 10, 5))
    got = read("Same measure on 2026-10-05, that same metric.", period, held=held)
    assert got == (date(2026, 10, 5), date(2026, 10, 5))


def test_a_meal_filter_stays_only_when_a_meal_is_named():
    food = Part(
        metrics=["food_logs"], operation="food", periods=[Period(kind="history")], meal_type="SNACK"
    )
    reading = Reading(kind="data", parts=[food])
    total = anchored_by_code(reading, "What is my protein total for that same day now?")
    assert total.parts[0].meal_type is None
    snack = anchored_by_code(reading, "And just the snack?")
    assert snack.parts[0].meal_type == "SNACK"


@pytest.mark.parametrize(
    "question, metric",
    [
        ("What was my time in the cardio heart-rate zone yesterday?", "hr_zone_vigorous_minutes"),
        ("What was my time in the light heart-rate zone yesterday?", "hr_zone_light_minutes"),
        ("My time still while awake yesterday?", "still_minutes"),
        ("And my average stress score?", "stress_score"),
    ],
)
def test_a_metric_called_by_its_catalog_name_is_that_metric(question, metric):
    reading = Reading(
        kind="data",
        parts=[Part(metrics=["unknown_zone"], operation="value", periods=[Period(kind="history")])],
    )
    assert anchored_by_code(reading, question).parts[0].metrics == [metric]
