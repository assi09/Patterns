"""Code checks the reader against what the question's words fix, and never rewrites it.

The audit of 2026-11-19 found follow-ups whose state held the right days while the reader's
reading replaced them. Code then rewrote readings from phrases, and broke correct ones ("24 hours
earlier than that day" lost its shift to "that day", Codex's live review). Now a contradiction
goes back to the reader once, stating it, and if the reader keeps it the person is asked. A
correct reading passes on the first call, however the reader expressed it. Made-up dates only.
"""

from datetime import date

import pytest
from test_clauses import with_last_accepted

from app.agent.context import Turn
from app.agent.llm import ScriptedLLM
from app.agent.requests import interpret

TODAY = date(2026, 11, 19)


def held(start, end, operation="value", metric="resting_hr", **extra):
    window = {"start": start, "end": end}
    part = {"metrics": [metric], "operation": operation, "windows": [window], **extra}
    return [Turn("earlier question", "earlier answer", request_state={"data": [part]})]


def part(period, operation="value", metrics=("resting_hr",), **extra):
    return {"metrics": list(metrics), "operation": operation, "periods": [period], **extra}


def ask_reader(question, *parts_each_call, history=(), kind="data"):
    """The reader returns each reading in turn; the result, its windows and the calls made."""
    llm = ScriptedLLM(
        request_turns=[
            ScriptedLLM.call("read_request", kind=kind, parts=parts) for parts in parts_each_call
        ]
    )
    with_last_accepted(llm, len(parts_each_call))
    request, _, budget = interpret(llm, question, list(history), TODAY, read_back=True)
    windows = [(w.start, w.end) for p in request.parts for w in p.windows]
    return request, windows, sum(r["tools"] == ["read_request"] for r in llm.requests)


EXPLICIT = lambda day: {"kind": "explicit", "start": day, "end": day}  # noqa: E731
INHERIT = {"kind": "inherit"}


# ---- a wrong reading is sent back once, then put right ----


def test_keep_that_same_date_keeps_the_latest_date_not_an_older_one():
    """Oct 19 and Oct 20 have the same value here: only the date shows the difference."""
    question = "Keep that same date, and say the date explicitly even if the value was unchanged."
    history = held("2026-10-20", "2026-10-20")
    wrong, right = [part(EXPLICIT("2026-10-19"))], [part(INHERIT)]
    _, windows, calls = ask_reader(question, wrong, right, history=history)
    assert windows == [(date(2026, 10, 20), date(2026, 10, 20))] and calls == 2


def test_two_days_forward_across_a_leap_day():
    question = "Move forward two days from the date you just answered."
    history = held("2024-02-28", "2024-02-28", metric="sleep_minutes")
    wrong = [part(EXPLICIT("2024-03-02"), metrics=("sleep_minutes",))]
    shifted = [
        part(
            {"kind": "relative", "anchor": "previous", "offset_days": 2}, metrics=("sleep_minutes",)
        )
    ]
    _, windows, _ = ask_reader(question, wrong, shifted, history=history)
    assert windows == [(date(2024, 3, 1), date(2024, 3, 1))]


def test_for_that_interval_keeps_the_whole_interval():
    question = "For that interval, what was the smallest daily count?"
    history = held("2026-12-31", "2027-01-03", operation="mean", metric="steps")
    wrong = [part(EXPLICIT("2027-01-03"), operation="min", metrics=("steps",))]
    right = [part(INHERIT, operation="min", metrics=("steps",))]
    _, windows, _ = ask_reader(question, wrong, right, history=history)
    assert windows == [(date(2026, 12, 31), date(2027, 1, 3))]


def test_moving_a_stretch_shifts_both_ends():
    question = "Move that entire stretch two days earlier and give its middle value again."
    history = held("2026-11-09", "2026-11-16", operation="median", metric="recovery_score")
    wrong = [part(INHERIT, operation="median", metrics=("recovery_score",))]
    moved = {"kind": "relative", "anchor": "previous", "offset_days": -2}
    right = [part(moved, operation="median", metrics=("recovery_score",))]
    _, windows, _ = ask_reader(question, wrong, right, history=history)
    assert windows == [(date(2026, 11, 7), date(2026, 11, 14))]


# ---- a correct reading passes on the first call, however it is expressed ----


def test_a_correct_shift_written_as_an_explicit_date_is_not_sent_back():
    question = "Move forward two days from the date you just answered."
    history = held("2024-02-28", "2024-02-28", metric="sleep_minutes")
    right = [part(EXPLICIT("2024-03-01"), metrics=("sleep_minutes",))]
    _, windows, calls = ask_reader(question, right, history=history)
    assert windows == [(date(2024, 3, 1), date(2024, 3, 1))] and calls == 1


def test_24_hours_earlier_than_that_day_keeps_its_shift():
    question = "Same measure, 24 hours earlier than that day"
    history = held("2026-10-20", "2026-10-20", metric="steps")
    right = [
        part({"kind": "relative", "anchor": "previous", "offset_days": -1}, metrics=("steps",))
    ]
    _, windows, calls = ask_reader(question, right, history=history)
    assert windows == [(date(2026, 10, 19), date(2026, 10, 19))] and calls == 1


def test_one_part_s_shift_leaves_another_part_s_yesterday_alone():
    question = "Shift steps two days earlier, and give my resting heart rate yesterday."
    history = held("2026-10-20", "2026-10-20", metric="steps")
    right = [
        part(
            {"kind": "relative", "anchor": "previous", "offset_days": -2},
            metrics=("steps",),
            reference=0,
        ),
        part({"kind": "relative", "anchor": "today", "offset_days": -1}),
    ]
    _, windows, calls = ask_reader(question, right, history=history)
    assert windows == [(date(2026, 10, 18),) * 2, (date(2026, 11, 18),) * 2] and calls == 1


def test_two_days_before_today_is_not_a_shift_of_the_earlier_days():
    question = "What were my steps two days before today?"
    history = held("2026-10-20", "2026-10-20", metric="steps")
    right = [part({"kind": "relative", "anchor": "today", "offset_days": -2}, metrics=("steps",))]
    _, windows, calls = ask_reader(question, right, history=history)
    assert windows == [(date(2026, 11, 17),) * 2] and calls == 1


def test_a_written_date_is_read_as_written_and_checked():
    question = "Same measure on 2026-10-05, that same metric."
    history = held("2026-10-20", "2026-10-20")
    right = [part(EXPLICIT("2026-10-05"))]
    _, windows, calls = ask_reader(question, right, history=history)
    assert windows == [(date(2026, 10, 5),) * 2] and calls == 1
    _, windows, calls = ask_reader(question, [part(INHERIT)], right, history=history)
    assert windows == [(date(2026, 10, 5),) * 2] and calls == 2


def test_another_part_s_written_date_is_kept_beside_this_week():
    question = "Average steps this week, and sleep duration on November 2, 2026?"
    right = [
        part({"kind": "calendar", "unit": "week"}, operation="mean", metrics=("steps",)),
        part(EXPLICIT("2026-11-02"), metrics=("sleep_minutes",)),
    ]
    _, windows, calls = ask_reader(question, right)
    assert windows == [(date(2026, 11, 16), TODAY), (date(2026, 11, 2),) * 2] and calls == 1


# ---- periods counted from today ----


def test_this_week_and_last_week_are_the_calendar_weeks():
    """Both became Nov 6-12 on Thursday Nov 19 (the audit of 2026-11-19)."""
    seven = {"kind": "rolling", "anchor": "today", "offset_days": -7, "days": 7}
    last = {"kind": "calendar", "unit": "week", "offset_units": -1}
    question = "My total steps last week?"
    _, windows, calls = ask_reader(
        question, [part(seven, "sum", ("steps",))], [part(last, "sum", ("steps",))]
    )
    assert windows == [(date(2026, 11, 9), date(2026, 11, 15))] and calls == 2
    _, windows, calls = ask_reader(question, [part(last, "sum", ("steps",))])
    assert calls == 1


def test_the_week_before_last_week_is_not_checked_against_last_week():
    two_back = {"kind": "calendar", "unit": "week", "offset_units": -2}
    question = "Average steps for the week before last week?"
    _, windows, calls = ask_reader(question, [part(two_back, "mean", ("steps",))])
    assert windows == [(date(2026, 11, 2), date(2026, 11, 8))] and calls == 1


def test_yesterday_after_an_earlier_request_is_sent_back_when_anchored_to_it():
    question = "What were my steps yesterday?"
    history = held("2026-10-20", "2026-10-20", metric="steps")
    wrong = [
        part({"kind": "relative", "anchor": "previous", "offset_days": -1}, "value", ("steps",))
    ]
    right = [part({"kind": "relative", "anchor": "today", "offset_days": -1}, "value", ("steps",))]
    _, windows, calls = ask_reader(question, wrong, right, history=history)
    assert windows == [(date(2026, 11, 18),) * 2] and calls == 2


@pytest.mark.parametrize(
    "question, offset, calls",
    [
        ("What was my average steps last 7 days?", -1, 2),
        ("What was my average steps last 7 days?", 0, 1),
        ("Average steps over the 7 complete days ending yesterday", -1, 1),
    ],
)
def test_last_n_days_ends_today_as_everywhere_else_in_the_app(question, offset, calls):
    period = {"kind": "rolling", "anchor": "today", "offset_days": offset, "days": 7}
    fixed = {"kind": "rolling", "anchor": "today", "offset_days": 0, "days": 7}
    readings = [[part(period, "mean", ("steps",))], [part(fixed, "mean", ("steps",))]]
    assert ask_reader(question, *readings[: 2 if calls == 2 else 1])[2] == calls


# ---- meals, metric names and stated comparisons ----


def food(meal=None, period=INHERIT):
    return part(period, "food", ("food_logs",), meal_type=meal)


def test_a_meal_filter_is_kept_only_when_a_meal_is_named():
    history = held("2026-10-20", "2026-10-20", "food", "food_logs", meal_type="SNACK")
    question = "What is my total protein for that same day across all meals?"
    _, _, calls = ask_reader(question, [food("SNACK")], [food()], history=history)
    request, _, calls_right = ask_reader(question, [food()], history=history)
    assert calls == 2 and calls_right == 1 and request.parts[0].meal_type is None
    request, _, calls = ask_reader("And just the snack?", [food("SNACK")], history=history)
    assert calls == 1 and request.parts[0].meal_type == "SNACK"
    request, _, calls = ask_reader("Same meal the day before?", [food("SNACK")], history=history)
    assert calls == 1


def test_above_is_checked_as_strictly_above():
    question = "How many days did I walk above 8,000 steps last month?"
    month = {"kind": "calendar", "unit": "month", "offset_units": -1}
    wrong = [part(month, "count", ("steps",), comparison=">=", threshold=8000)]
    right = [part(month, "count", ("steps",), comparison=">", threshold=8000)]
    request, _, calls = ask_reader(question, wrong, right)
    assert request.parts[0].comparison == ">" and calls == 2
    assert ask_reader(question, right)[2] == 1


def test_over_a_number_of_days_is_not_a_threshold():
    question = "How many days were above 9000 steps over 10 days?"
    period = {"kind": "rolling", "anchor": "today", "days": 10}
    right = [part(period, "count", ("steps",), comparison=">", threshold=9000)]
    assert ask_reader(question, right)[2] == 1


# ---- what happened to each reading is kept, without the person's words ----


def test_each_reading_s_fate_is_recorded_without_words_or_values():
    question = "Keep that same date, and say the date explicitly."
    history = held("2026-10-20", "2026-10-20")
    request, _, _ = ask_reader(
        question, [part(EXPLICIT("2026-10-19"))], [part(INHERIT)], history=history
    )
    first, second = request.attempts
    assert (first["outcome"], first["stage"], first["codes"]) == (
        "sent_back",
        "check",
        ["read_back"],
    )
    assert second["outcome"] == "resolved" and second["read"]["parts"][0]["periods"] == [
        "inherit/today"
    ]
    kept = str(request.attempts)
    assert "same date" not in kept and "2026-10-19" not in kept and "resting_hr" not in kept


def test_a_reading_that_cannot_resolve_says_why():
    llm = ScriptedLLM(
        request_turns=[
            ScriptedLLM.call(
                "read_request",
                kind="data",
                parts=[{"operation": "value", "periods": [{"kind": "inherit"}]}],
            )
        ]
    )
    request, _, _ = interpret(llm, "And that one?", [], TODAY)
    # Nothing was computed earlier, so the reading itself is wrong in form: it goes back to the
    # reader, saying so, before anyone is asked.
    [only] = request.attempts
    assert only["outcome"] == "sent_back" and only["stage"] == "resolve"
    assert only["codes"] == ["RetryReading"]
