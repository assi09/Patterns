"""A follow-up keeps the days and metric it refers back to, and only when it refers back.

The cases are the independent audit's own (2026-11-18), on made-up data: "the daily average for
exactly those dates" after a seven-day total was answered over the whole history, and "that same
night" became today.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from test_broad_questions import Router, submit

from app.agent.ask import ask
from app.agent.context import Turn
from app.agent.followup import with_period
from app.agent.llm import ScriptedLLM
from app.agent.periods import asks_over_days
from app.agent.scope import Scope, resolve, with_scope
from app.analysis.day import with_scores
from app.synthetic import generate

TODAY = date(2026, 11, 18)
NOV = lambda day: date(2026, 11, day)  # noqa: E731


def walk(questions):
    """Each question's resolution, in a conversation of them."""
    history, out = [], []
    for question in questions:
        out.append(with_scope(question, history, TODAY))
        history.append(Turn(question, "-"))
    return out


def test_those_dates_keep_the_seven_days_and_the_metric():
    got = walk(
        [
            "Give my total steps from 2026-11-11 through 2026-11-17, inclusive.",
            "What was the daily average for exactly those dates?",
            "And the median, rather than the average?",
            "How many of those days were strictly above 10,000 steps?",
            "Which of those days had the highest steps, and how many?",
        ]
    )
    for resolved in got:
        assert (resolved.scope.start, resolved.scope.end) == (NOV(11), NOV(17))
        assert resolved.scope.metrics == ("steps",)
    assert [r.inherited for r in got] == [False, True, True, True, True]


def test_that_same_day_follows_the_day_the_conversation_is_on():
    got = walk(
        [
            "How many steps did I take yesterday?",
            "And the day before that?",
            "How long did I sleep on that same day? Give hours and minutes.",
            "Actually I meant yesterday. How much sleep was it?",
            "And how much deep sleep did I get that same night?",
        ]
    )
    days = [r.scope.start for r in got]
    assert days == [NOV(17), NOV(16), NOV(16), NOV(17), NOV(17)]
    assert got[2].scope.metrics == ()  # "sleep" is its own subject, not steps carried over


def test_a_question_that_stands_on_its_own_does_not_inherit():
    """The guardrail: what is kept is reused only when the question refers back."""
    got = walk(["What were my total steps from Nov 11 to Nov 17?", "What is my average HRV?"])
    assert not got[1].inherited and got[1].scope.start is None
    assert got[1].scope.metrics == ("hrv_ms",)


def test_a_different_metric_over_those_dates_takes_the_dates_not_the_metric():
    got = walk(["Total steps from 2026-11-11 to 2026-11-17?", "My average HRV over those dates?"])
    assert got[1].scope == Scope(("hrv_ms",), NOV(11), NOV(17))


def test_a_period_named_in_the_follow_up_wins():
    got = walk(["Total steps from 2026-11-11 to 2026-11-17?", "And the average last month?"])
    assert (got[1].scope.start, got[1].scope.end) == (
        NOV(1) - timedelta(days=31),
        NOV(1) - timedelta(days=1),
    )
    assert got[1].scope.metrics == ("steps",)  # "and the average" is still about steps


def test_the_same_thing_over_other_days_keeps_the_metric():
    got = walk(
        ["Total steps last week?", "Now use the seven complete days ending yesterday instead."]
    )
    assert got[1].scope == Scope(("steps",), NOV(11), NOV(17))


def test_all_the_history_carries_over():
    got = walk(
        [
            "What are my total REM sleep minutes across all available history?",
            "For that same history, give the average REM minutes per recorded night instead.",
        ]
    )
    assert got[1].scope.all_data and got[1].inherited


def test_a_turn_about_something_else_leaves_the_days_in_place():
    got = walk(
        ["Total steps from 2026-11-11 to 2026-11-17?", "How do I do a plank?", "And the median?"]
    )
    assert got[2].scope == Scope(("steps",), NOV(11), NOV(17))


@pytest.mark.parametrize(
    "questions, asks",
    [
        (["What were those dates again?"], "Which dates"),  # nothing gave any dates
        (["How do I do a plank?", "And that same day?"], "Which day"),
        (["What was my average steps last week?", "And that same night?"], "Which day"),
    ],
)
def test_a_reference_that_cannot_be_resolved_is_asked_about(questions, asks):
    assert walk(questions)[-1].ask.startswith(asks)


def test_the_day_before_counts_from_the_day_in_question_not_today():
    earlier = Scope(("steps",), NOV(10), NOV(10))
    assert resolve("and the day before that?", earlier, TODAY).scope.start == NOV(9)
    assert resolve("and the day after that?", earlier, TODAY).scope.start == NOV(11)


def test_a_range_of_dates_is_a_span_not_one_day():
    assert asks_over_days("average steps from 2026-11-11 to 2026-11-17")
    assert asks_over_days("my average steps Nov 11 through 17")
    assert not asks_over_days("my steps on 2026-11-11")


def test_a_short_question_naming_its_own_metric_keeps_no_earlier_period():
    month = [Turn("What was my average sleep this month?", "-")]
    assert with_period("what is my average HRV?", month) == "what is my average HRV?"
    assert with_period("what was my best night?", month) == "what was my best night this month?"


# ---- through ask(): the agent is told the days, and the coincidence test ----


@pytest.fixture(scope="module")
def made_up():
    return with_scores(generate(date(2026, 5, 23), 180, (), seed=11).frame)


def history_of(questions):
    at = datetime(2026, 11, 18, 19, tzinfo=UTC)
    return [Turn(q, "Done.", answered_by="activity", at=at) for q in questions]


def test_the_agent_is_told_the_days_those_dates_mean(made_up):
    llm = ScriptedLLM([submit()])
    history = history_of(["Give my total steps from 2026-11-11 through 2026-11-17, inclusive."])
    ask(
        llm,
        Router("lookup"),
        made_up,
        "What was the daily average for exactly those dates?",
        today=TODAY,
        history=history,
    )
    task = llm.requests[-1]["messages"][1]["content"]
    assert "2026-11-11 to 2026-11-17" in task
    assert "all the data" not in task  # not the whole-history default


def test_the_same_night_reaches_the_agent_as_that_date_even_when_today_has_the_same_value(made_up):
    """A grader checking only the number would pass a wrong day whose value is the same: the date
    itself is what must reach the agent."""
    frame = made_up.copy()
    frame.loc[str(NOV(18)), "deep_sleep_minutes"] = frame.loc[str(NOV(16)), "deep_sleep_minutes"]
    llm = ScriptedLLM([submit()])
    history = history_of(["How many steps did I take on Nov 16?"])
    ask(
        llm,
        Router("day"),
        frame,
        "How much deep sleep did I get that same night?",
        today=TODAY,
        history=history,
    )
    task = llm.requests[-1]["messages"][1]["content"]
    assert "2026-11-16" in task and "2026-11-18" not in task.split("(From this conversation")[1]


def test_an_unresolvable_reference_asks_and_costs_nothing(made_up):
    llm = ScriptedLLM([])
    reply = ask(
        llm, Router("lookup"), made_up, "What was my average over those dates?", today=TODAY
    )
    assert reply.result.summary.startswith("Which dates") and llm.requests == []
