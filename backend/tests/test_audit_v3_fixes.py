"""The straightforward failures of the third audit (2026-11-19), on made-up data.

- "Yes, go ahead and save that" was answered "Saved." while the card stayed a draft;
- "this week" and "last week" both became Nov 6-12 on Thursday Nov 19;
- "make its duration 37 minutes" was asked "which earlier date?";
- "stress score" was read as the check-in rating;
- "how many HRV days were recorded?" was asked for a threshold;
- a recovery score's usual range was worked out with another formula than the day's own score;
- a constant driver was said to have "too few paired days", and the cause line followed results
  that showed no link at all.
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest
from test_broad_questions import END, Router, planted

from app.agent.agent import AgentResult
from app.agent.ask import CONFIRM_ON_CARD, NOTHING_WAITING, ask, no_false_success
from app.agent.llm import ScriptedLLM
from app.agent.requested import execute
from app.agent.requests import Part, Period, Reading, Request, ResolvedPart, anchored_by_code
from app.analysis.day import usual_before, with_scores
from app.analysis.evidence import Window
from app.analysis.tools import correlate

THURSDAY = date(2026, 11, 19)


# ---- no claim of having saved anything ----


@pytest.mark.parametrize(
    "summary", ["Saved.", "I've logged your walk.", "It's saved now.", "Done! I've saved it."]
)
def test_a_reply_saying_it_logged_something_is_replaced(summary):
    result = AgentResult(run_id="r", stop_reason="submitted", summary=summary)
    assert no_false_success(result, after_draft=True).summary == CONFIRM_ON_CARD
    result = AgentResult(run_id="r", stop_reason="submitted", summary=summary)
    assert no_false_success(result, after_draft=False).summary == NOTHING_WAITING


@pytest.mark.parametrize(
    "summary", ["You logged 3 entries on Tue, Nov 17.", "Ready to log: walk, 34 min."]
)
def test_their_own_logging_or_a_draft_is_not_a_false_success(summary):
    result = AgentResult(run_id="r", stop_reason="submitted", summary=summary)
    assert no_false_success(result, after_draft=True).summary == summary


def test_a_confirmation_with_a_card_waiting_points_to_the_card():
    llm = ScriptedLLM(request_turns=[ScriptedLLM.call("read_request", kind="confirmation")] * 2)
    answer = ask(
        llm, Router("chat"), planted(), "Yes, go ahead and save that.", today=END, after_draft=True
    )
    assert answer.result.summary == CONFIRM_ON_CARD


def test_a_confirmation_with_nothing_waiting_never_says_saved():
    """With no card the reader re-reads and asks what is meant: never a success."""
    from app.agent.ask import FALSE_SUCCESS

    llm = ScriptedLLM(request_turns=[ScriptedLLM.call("read_request", kind="confirmation")] * 2)
    answer = ask(llm, Router("chat"), planted(), "Yes, go ahead and save that.", today=END)
    assert not FALSE_SUCCESS.search(answer.result.summary)


# ---- code's own reading of periods, days and metrics ----


def one_part(*periods, metrics=("steps",), operation="sum"):
    return Reading(
        kind="data", parts=[Part(metrics=list(metrics), operation=operation, periods=list(periods))]
    )


# "this week" and "last week" are checked, not rewritten: test_follow_up_scope.py.


def test_a_correction_naming_no_day_keeps_the_card_s_day():
    reading = Reading(
        kind="correction",
        duration_minutes=37,
        log_day=Period(kind="relative", anchor="previous", offset_days=0),
    )
    assert anchored_by_code(reading, "Correction: make its duration 37 minutes.").log_day is None


def test_tomorrow_on_a_correction_counts_from_today():
    reading = Reading(
        kind="correction", log_day=Period(kind="relative", anchor="previous", offset_days=1)
    )
    fixed = anchored_by_code(reading, "Actually put it on tomorrow instead.")
    assert fixed.log_day.anchor == "today" and fixed.log_day.offset_days == 1


# ---- counted days with data ----


@pytest.fixture
def gappy():
    days = pd.date_range("2026-11-01", periods=10, freq="D")
    hrv = [50.0, None, 52.0, None, None, 49.0, 51.0, None, 48.0, 50.0]
    steps = [None, 8000, 9000, None, 7000, 6500, None, 7200, 7300, None]
    return pd.DataFrame({"hrv_ms": hrv, "steps": steps}, index=days)


def coverage_request(*metrics):
    window = Window(start=date(2026, 11, 1), end=date(2026, 11, 10))
    part = ResolvedPart(metrics=list(metrics), operation="coverage", windows=[window])
    return Request(kind="data", parts=[part])


def test_how_many_days_were_recorded_is_counted(gappy):
    result = execute(coverage_request("hrv_ms"), gappy, date(2026, 11, 10))
    assert (
        "recorded on 6 of 10 days" in result.summary and "4 days have no reading" in result.summary
    )


def test_days_with_both_recorded_are_counted(gappy):
    result = execute(coverage_request("hrv_ms", "steps"), gappy, date(2026, 11, 10))
    assert "3 days had both" in result.summary  # Nov 3, 6 and 9


# ---- a score keeps its definition when one expert sees part of the data ----


def test_a_score_s_usual_range_does_not_change_with_the_columns_an_expert_sees():
    full = with_scores(planted(seed=4))
    day = full.index[-1].date()
    recovery_only = full.drop(columns=[c for c in ("strain", "sleep_minutes") if c in full])
    assert usual_before(recovery_only, "recovery_score", day) == usual_before(
        full, "recovery_score", day
    )


# ---- why there is no correlation, and when the cause line belongs ----


def test_a_constant_driver_is_named_as_the_reason_not_too_few_days():
    days = pd.date_range("2026-07-01", periods=140, freq="D")
    frame = pd.DataFrame({"steps": [8000.0] * 140, "hrv_ms": np.linspace(40, 60, 140)}, index=days)
    window = Window(start=days[0].date(), end=days[-1].date())
    record = correlate(frame, "steps", "hrv_ms", window)
    assert record.stats["paired_days"] == 140 and not record.stats["both_vary"]
    part = ResolvedPart(metrics=["steps", "hrv_ms"], operation="correlate", windows=[window])
    result = execute(Request(kind="data", parts=[part]), frame, days[-1].date())
    # Named, and cited with what shows it (the 689fa7c audit found it uncited).
    assert "steps stayed the same on every day" in result.summary and result.claims
    assert "too few" not in result.summary and "goes together;" not in result.summary
    assert "can't establish or rule out" not in result.summary  # no link was tested


def test_metrics_never_on_the_same_days_are_said_so():
    days = pd.date_range("2026-07-01", periods=40, freq="D")
    steps = [8000.0 + i if i % 2 else None for i in range(40)]
    hrv = [None if i % 2 else 50.0 + i for i in range(40)]
    frame = pd.DataFrame({"steps": steps, "hrv_ms": hrv}, index=days)
    window = Window(start=days[0].date(), end=days[-1].date())
    part = ResolvedPart(metrics=["steps", "hrv_ms"], operation="correlate", windows=[window])
    result = execute(Request(kind="data", parts=[part]), frame, days[-1].date())
    assert "never recorded on the same days" in result.summary


@pytest.mark.parametrize(
    "question, operation",
    [
        ("How many HRV days were actually recorded?", "coverage"),
        ("How many nights are missing in October?", "coverage"),
        ("check this", "count"),  # not about recording: left for the reader to ask
    ],
)
def test_a_count_of_recorded_days_is_a_coverage_count(question, operation):
    reading = one_part(Period(kind="history"), metrics=("hrv_ms",), operation="count")
    assert anchored_by_code(reading, question).parts[0].operation == operation


# ---- a message that logs something and asks about the data gets both ----


def test_the_question_beside_a_logging_request_is_answered_by_code():
    """The mixed probe prepared the walk and answered only that steps were usual."""
    from test_broad_questions import submit

    frame = planted()
    day = frame.index[-1].date().isoformat()
    steps_that_day = {"kind": "explicit", "start": day, "end": day}
    llm = ScriptedLLM(
        [submit()],
        request_turns=[
            ScriptedLLM.call(
                "read_request",
                kind="logging",
                parts=[{"metrics": ["steps"], "operation": "value", "periods": [steps_that_day]}],
            )
        ]
        * 2,
    )
    said = f"Log a 28 minute walk, and how many steps did I take on {day}?"
    answer = ask(llm, Router("lookup"), frame, said, today=END)
    count = f"{frame['steps'].iloc[-1]:,.0f}"
    assert any(count in note for note in answer.result.notes)
    assert any(e.tool != "public_guidance" for e in answer.result.evidence.values())
