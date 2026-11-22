"""The independent review of the third-audit fixes (Codex, 2026-11-19): its counterexamples,
kept as regression tests, with made-up values only."""

from datetime import date

import pandas as pd

from app.agent.agent import AgentResult
from app.agent.ask import no_false_success
from app.agent.requested import execute
from app.agent.requests import (
    Part,
    Period,
    Reading,
    Request,
    ResolvedPart,
    anchored_by_code,
    resolve,
)
from app.analysis.evidence import Window

TODAY = date(2026, 11, 19)


def test_calendar_override_keeps_other_parts_explicit_dates():
    reading = Reading(
        kind="data",
        parts=[
            Part(
                metrics=["steps"], operation="mean", periods=[Period(kind="calendar", unit="week")]
            ),
            Part(
                metrics=["sleep_minutes"],
                operation="value",
                periods=[Period(kind="explicit", start=date(2026, 11, 2), end=date(2026, 11, 2))],
            ),
        ],
    )
    fixed = anchored_by_code(
        reading, "Average steps this week, and sleep duration on November 2, 2026?", TODAY
    )
    assert fixed.parts[1].periods[0].start == date(2026, 11, 2)


def test_week_before_last_week_is_not_last_week():
    reading = Reading(
        kind="data",
        parts=[
            Part(
                metrics=["steps"],
                operation="mean",
                periods=[Period(kind="calendar", unit="week", offset_units=-2)],
            )
        ],
    )
    fixed = resolve(
        anchored_by_code(reading, "Average steps for the week before last week?", TODAY), {}, TODAY
    )
    assert fixed.parts[0].windows[0].start == date(2026, 11, 2)
    assert fixed.parts[0].windows[0].end == date(2026, 11, 8)


def test_explicit_correction_date_wins_even_with_redundant_previous_anchor():
    reading = Reading(
        kind="correction",
        log_day=Period(
            kind="explicit", start=date(2026, 11, 12), end=date(2026, 11, 12), anchor="previous"
        ),
    )
    fixed = anchored_by_code(reading, "Actually put that walk on November 12, 2026.", TODAY)
    assert fixed.log_day is not None and fixed.log_day.start == date(2026, 11, 12)


def test_five_metric_coverage_does_not_crash():
    metrics = ["steps", "sleep_minutes", "hrv_ms", "resting_hr", "calories"]
    frame = pd.DataFrame(
        {m: [float(i + 1) for i in range(10)] for m in metrics},
        index=pd.date_range("2026-11-01", periods=10),
    )
    window = Window(start=date(2026, 11, 1), end=date(2026, 11, 10))
    request = Request(
        kind="data", parts=[ResolvedPart(metrics=metrics, operation="coverage", windows=[window])]
    )
    answer = execute(request, frame, TODAY)
    assert "10 days" in answer.summary


def test_false_success_guard_handles_curly_apostrophe():
    result = AgentResult(run_id="r", stop_reason="submitted", summary="I’ve logged your walk.")
    assert no_false_success(result, after_draft=True).summary != "I’ve logged your walk."


def test_false_success_guard_does_not_rewrite_added_citations():
    text = "I have added the source citations below."
    result = AgentResult(run_id="r", stop_reason="looked_up", summary=text)
    assert no_false_success(result, after_draft=False).summary == text


def test_false_success_guard_does_not_rewrite_conditional_instructions():
    text = "When it's saved, you can undo it from the entry card."
    result = AgentResult(run_id="r", stop_reason="submitted", summary=text)
    assert no_false_success(result, after_draft=True).summary == text
