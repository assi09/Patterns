"""Independent offline counterexamples. Synthetic dates and rows only."""

from datetime import date

import pytest
from test_broad_questions import END, Router, planted
from test_investigate_and_memory import reading_llm

from app.agent.ask import MEMORY_WHICH, ask, recalled
from app.agent.context import ChatState
from app.agent.llm import Budget, ScriptedLLM
from app.agent.requests import (
    Part,
    Period,
    Reading,
    Request,
    ResolvedPart,
    anchored_by_code,
    resolve,
)
from app.agent.strategy import overview_evidence
from app.analysis.evidence import Window

TODAY = date(2026, 11, 19)


def prior(meal=None):
    return {
        "data": [
            ResolvedPart(
                metrics=["food_logs"] if meal else ["steps"],
                operation="food" if meal else "mean",
                windows=[Window(start="2026-10-20", end="2026-10-20")],
                meal_type=meal,
            ).model_dump(mode="json")
        ]
    }


def test_correct_hour_offset_survives_same_day_reference():
    r = Reading(
        kind="data",
        parts=[
            Part(
                metrics=["steps"],
                operation="value",
                periods=[Period(kind="relative", anchor="previous", offset_days=-1)],
            )
        ],
    )
    got = resolve(
        anchored_by_code(r, "Same measure, 24 hours earlier than that day", TODAY), prior(), TODAY
    )
    assert got.parts[0].windows == [Window(start="2026-10-19", end="2026-10-19")]


def test_today_offset_does_not_use_previous_date():
    r = Reading(
        kind="data",
        parts=[
            Part(
                metrics=["steps"],
                operation="value",
                periods=[Period(kind="relative", anchor="today", offset_days=-2)],
            )
        ],
    )
    got = resolve(
        anchored_by_code(r, "What were my steps two days before today?", TODAY), prior(), TODAY
    )
    assert got.parts[0].windows == [Window(start="2026-11-17", end="2026-11-17")]


def test_one_parts_shift_does_not_overwrite_another_parts_today():
    r = Reading(
        kind="data",
        parts=[
            Part(
                metrics=["steps"],
                operation="value",
                reference=0,
                periods=[Period(kind="relative", anchor="previous", offset_days=-2)],
            ),
            Part(
                metrics=["resting_hr"],
                operation="value",
                periods=[Period(kind="relative", anchor="today", offset_days=-1)],
            ),
        ],
    )
    got = resolve(
        anchored_by_code(
            r, "Shift steps two days earlier, and give my resting heart rate yesterday.", TODAY
        ),
        prior(),
        TODAY,
    )
    assert got.parts[1].windows == [Window(start="2026-11-18", end="2026-11-18")]


def test_cleared_meal_filter_does_not_return_during_resolution():
    r = Reading(
        kind="data",
        parts=[
            Part(
                metrics=["food_logs"],
                operation="food",
                reference=0,
                periods=[Period(kind="inherit")],
                meal_type=None,
            )
        ],
    )
    got = resolve(
        anchored_by_code(r, "What is my total protein for that same day across all meals?", TODAY),
        prior("SNACK"),
        TODAY,
    )
    assert got.parts[0].meal_type is None


def test_investigation_inherits_metric_with_its_referenced_period():
    r = Reading(
        kind="investigate", focus="why", parts=[Part(reference=0, periods=[Period(kind="inherit")])]
    )
    got = resolve(r, prior(), TODAY)
    assert got.parts[0].metrics == ["steps"]


def test_investigation_can_select_the_second_prior_part():
    s = prior()
    s["data"].append(
        ResolvedPart(
            metrics=["sleep_minutes"],
            operation="mean",
            windows=[Window(start="2026-09-01", end="2026-09-30")],
        ).model_dump(mode="json")
    )
    r = Reading(
        kind="investigate", focus="why", parts=[Part(reference=1, periods=[Period(kind="inherit")])]
    )
    got = resolve(r, s, TODAY)
    assert got.parts[0].metrics == ["sleep_minutes"]


def test_forget_reaches_deletion_path_instead_of_generic_question():
    llm = reading_llm(kind="memory", memory_action="forget")
    reply = ask(llm, Router("chat"), planted(), "Please forget my old running goal.", today=END)
    assert reply.result.summary != MEMORY_WHICH


def test_polite_remember_reaches_memory_path():
    llm = reading_llm(kind="memory", memory_action="remember")
    reply = ask(
        llm, Router("chat"), planted(), "Could you remember that I prefer walking?", today=END
    )
    assert reply.result.summary != MEMORY_WHICH


def test_inferred_interest_is_not_claimed_as_user_approved_fact():
    text = recalled([], ChatState(profile=("Often looks at: steps",)), [])
    assert not ("you approved these" in text and "Often looks at:" in text)


def test_memory_early_return_accounts_for_request_reader_cost():
    request = Request(kind="memory", memory_action="remember")
    budget = Budget(calls=1, cost_usd=0.001)
    reply = ask(
        ScriptedLLM([]),
        Router("chat"),
        planted(),
        "Remember that I prefer walking.",
        today=END,
        request_bundle=(request, {}, budget),
    )
    assert reply.result.budget.cost_usd >= 0.001
    assert any(s.get("type") == "request" for s in reply.result.trace)


@pytest.mark.parametrize("start,end", [("2026-12-01", "2026-12-14"), ("2026-09-01", "2026-09-03")])
def test_explicit_investigation_window_never_replaced_by_latest_data(start, end):
    frame = planted()
    records, _ = overview_evidence(
        frame, "What changed over the requested period?", END, Window(start=start, end=end)
    )
    assert not records or all(
        e.windows[0].start == date.fromisoformat(start)
        and e.windows[0].end <= date.fromisoformat(end)
        for e in records
    )


def test_coaching_evidence_uses_named_month_instead_of_latest_days():
    from test_broad_questions import submit

    llm = reading_llm(
        submit(),
        kind="investigate",
        focus="coaching",
        parts=[
            {
                "metrics": ["sleep_minutes"],
                "operation": "describe",
                "periods": [{"kind": "explicit", "start": "2026-09-01", "end": "2026-09-30"}],
            }
        ],
    )
    reply = ask(
        llm,
        Router("lookup"),
        planted(),
        "What could I try for my short sleep in September?",
        today=END,
    )
    personal = [
        e
        for e in reply.result.evidence.values()
        if e.windows and e.tool != "public_guidance" and "sleep_minutes" in e.metrics
    ]
    assert personal and any(
        w.start == date(2026, 9, 1) and w.end == date(2026, 9, 30)
        for e in personal
        for w in e.windows
    )
