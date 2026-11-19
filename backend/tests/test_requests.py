"""Request interpretation contracts and answers checked against independent synthetic rows.

The scripted reader tests the boundary, not language generalization; that requires paid held-out
conversations. No test here calls a provider or reads personal data.
"""

import json
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from app.agent.ask import ask
from app.agent.context import Turn
from app.agent.listener import worth_listening
from app.agent.llm import ScriptedLLM
from app.agent.present import METRICS, format_level
from app.agent.requested import execute
from app.agent.requests import (
    Ambiguous,
    Part,
    Period,
    Reading,
    Request,
    ResolvedPart,
    interpret,
    period_window,
    resolve,
    strict_schema,
)
from app.agent.router import KeywordRouter
from app.agent.verifier import Claim, check_claim
from app.analysis.evidence import Window
from app.analysis.tools import coverage

TODAY = date(2026, 11, 18)
SPAN = Window(start=date(2026, 11, 3), end=date(2026, 11, 9))


def reader(**fields):
    return ScriptedLLM(request_turns=[ScriptedLLM.call("read_request", **fields)])


def state(*parts):
    return {"data": [p.model_dump(mode="json") for p in parts]}


def previous(**fields):
    return ResolvedPart(metrics=["steps"], operation="sum", windows=[SPAN], **fields)


@pytest.mark.parametrize("offset", [-366, -31, -7, -1, 0, 1, 366])
def test_relative_offsets_shift_both_bounds_without_using_assistant_numbers(offset):
    from datetime import timedelta

    reading = Reading(
        kind="data",
        parts=[Part(periods=[Period(kind="relative", anchor="previous", offset_days=offset)])],
    )
    resolved = resolve(reading, state(previous()), TODAY).parts[0]
    assert resolved.operation == "sum" and resolved.metrics == ["steps"]
    assert resolved.windows == [
        Window(start=SPAN.start + timedelta(days=offset), end=SPAN.end + timedelta(days=offset))
    ]


@pytest.mark.parametrize(
    "today,period,wanted",
    [
        (date(2024, 3, 1), Period(kind="relative", offset_days=-1), ("2024-02-29", "2024-02-29")),
        (
            date(2026, 1, 2),
            Period(kind="calendar", unit="month", offset_units=-1),
            ("2025-12-01", "2025-12-31"),
        ),
        (
            date(2024, 3, 10),
            Period(kind="calendar", unit="month", offset_units=-1),
            ("2024-02-01", "2024-02-29"),
        ),
        (
            TODAY,
            Period(kind="calendar", unit="week", offset_units=-1),
            ("2026-11-09", "2026-11-15"),
        ),
        (TODAY, Period(kind="calendar", unit="week"), ("2026-11-16", "2026-11-18")),
        (TODAY, Period(kind="rolling", days=7, offset_days=-1), ("2026-11-11", "2026-11-17")),
    ],
)
def test_code_computes_calendar_boundaries(today, period, wanted):
    assert period_window(period, None, today) == [Window(start=wanted[0], end=wanted[1])]


def test_new_period_preserves_operation_but_standalone_new_metric_uses_history():
    result = resolve(
        Reading(
            kind="data",
            parts=[
                Part(
                    periods=[
                        Period(kind="explicit", start=date(2026, 10, 1), end=date(2026, 10, 9))
                    ]
                )
            ],
        ),
        state(previous()),
        TODAY,
    )
    assert result.parts[0].operation == "sum" and result.parts[0].windows[0].start.month == 10
    result = resolve(
        Reading(kind="data", parts=[Part(metrics=["resting_hr"], operation="mean")]),
        state(previous()),
        TODAY,
    )
    assert result.parts[0].history and not result.parts[0].windows


def test_ambiguous_reference_does_not_pick_the_first_data_part():
    with pytest.raises(Ambiguous):
        resolve(
            Reading(
                kind="data", parts=[Part(operation="median", periods=[Period(kind="inherit")])]
            ),
            state(previous(), previous()),
            TODAY,
        )
    result = resolve(
        Reading(
            kind="data",
            parts=[Part(operation="median", reference=1, periods=[Period(kind="inherit")])],
        ),
        state(previous(), previous()),
        TODAY,
    )
    assert result.parts[0].operation == "median"


def test_guidance_and_data_context_survive_intervening_turns():
    held = state(previous()) | {"guidance": ["glute bridge"]}
    history = [
        Turn("old question", "wrong numbers and dates", request_state=held),
        Turn("thanks", "welcome"),
    ]
    llm = reader(kind="data", parts=[{"operation": "median", "periods": [{"kind": "inherit"}]}])
    request, updated, _ = interpret(llm, "The midpoint for that interval please", history, TODAY)
    assert request.parts[0].windows == [SPAN]
    assert updated["guidance"] == ["glute bridge"]
    llm = reader(kind="guidance", guidance_reference=True, guidance_question="Where do my feet go?")
    request, _, _ = interpret(llm, "Where do my feet go during that movement?", history, TODAY)
    assert "glute bridge" in request.guidance_question
    quoted = json.loads(llm.requests[0]["messages"][1]["content"])
    assert "wrong numbers" not in json.dumps(quoted)


def test_two_guidance_topics_need_clarification_but_a_new_topic_wins():
    held = {"guidance": ["plank", "lunge"]}
    with pytest.raises(Ambiguous):
        resolve(Reading(kind="guidance", guidance_reference=True), held, TODAY)
    request = resolve(
        Reading(kind="guidance", topics=["squat"], guidance_question="Squat depth?"), held, TODAY
    )
    assert request.topics == ["squat"]


def test_a_named_resolved_guidance_topic_is_included_even_when_rewrite_keeps_a_pronoun():
    request = resolve(
        Reading(
            kind="guidance", topics=["lunge"], guidance_question="Where does my knee go during it?"
        ),
        {},
        TODAY,
    )
    assert "lunge" in request.guidance_question


def test_other_person_access_limit_precedes_reader_clarification():
    llm = reader(kind="clarify", subject="other")
    result = ask(
        llm,
        KeywordRouter(),
        pd.DataFrame(),
        "How did the person I share a flat with sleep?",
        today=TODAY,
    ).result
    assert "only see your own" in result.summary


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "data", "parts": [{"metrics": ["imaginary"], "operation": "mean"}]},
        {"kind": "data", "parts": [{"metrics": ["steps"], "operation": "count"}]},
        {"kind": "data", "parts": [{"metrics": ["steps"], "operation": "correlate"}]},
        {"kind": "data", "parts": [{"metrics": ["steps"], "operation": "compare"}]},
        {"kind": "data", "computed_mean": 42},
        {
            "kind": "data",
            "parts": [
                {
                    "metrics": ["steps"],
                    "operation": "mean",
                    "periods": [{"kind": "explicit", "start": "2026-02-30", "end": "2026-03-01"}],
                }
            ],
        },
    ],
)
def test_bad_reader_output_asks_instead_of_falling_back_to_all_history(fields):
    request, held, budget = interpret(reader(**fields), "check this", [], TODAY)
    assert request.kind == "clarify" and request.clarification
    assert not held and budget.calls == 1


@pytest.mark.parametrize("metric", list(METRICS))
def test_every_registered_metric_keeps_its_identity_dates_and_value(metric):
    # Duplicate values on different days ensure a lucky numeric match cannot prove date scope.
    values = [7, 13, 7, 29, np.nan, 41, 53]
    frame = pd.DataFrame({metric: values}, index=pd.date_range(SPAN.start, periods=7))
    llm = reader(
        kind="data",
        parts=[
            {
                "metrics": [metric],
                "operation": "median",
                "periods": [{"kind": "explicit", "start": str(SPAN.start), "end": str(SPAN.end)}],
            }
        ],
    )
    result = ask(
        llm, KeywordRouter(), frame, f"Median {metric} for this interval", today=TODAY
    ).result
    record = next(e for e in result.evidence.values() if e.tool == "observed_summary")
    assert record.metrics == (metric,) and record.windows == (SPAN,)
    assert record.stats["median"] == 21 and record.n == 6
    assert format_level(metric, 21) in result.summary
    assert "Missing days" in result.summary and "can't" not in result.summary
    assert result.budget.calls == 1 and not llm.turns


@pytest.mark.parametrize("comparison,wanted", [(">", 2), (">=", 3), ("<", 2), ("<=", 3), ("==", 1)])
def test_comparison_equality_zero_and_missing_have_separate_meanings(comparison, wanted):
    frame = pd.DataFrame(
        {"steps": [0, 6, 12, 18, 24, np.nan]}, index=pd.date_range("2026-11-01", periods=6)
    )
    request = Request(
        kind="data",
        parts=[
            ResolvedPart(
                metrics=["steps"],
                operation="count",
                comparison=comparison,
                threshold=12,
                windows=[Window(start="2026-11-01", end="2026-11-06")],
            )
        ],
    )
    result = execute(request, frame, TODAY)
    record = next(iter(result.evidence.values()))
    assert record.stats["days_met"] == wanted and record.stats["days_equal"] == 1
    assert record.stats["days_counted"] == 5
    from app.agent.requested import SAID

    assert f"{wanted} of 5" in result.summary and f" {SAID[comparison]} " in result.summary


def test_multiple_operations_do_not_collapse_into_one_answer():
    frame = pd.DataFrame(
        {"steps": [3, 6, 21], "resting_hr": [51, 54, 57]},
        index=pd.date_range("2026-11-01", periods=3),
    )
    request = resolve(
        Reading(
            kind="data",
            parts=[
                Part(metrics=["steps"], operation="sum"),
                Part(metrics=["resting_hr"], operation="median"),
            ],
        ),
        {},
        TODAY,
    )
    result = execute(request, frame, TODAY)
    assert len(result.claims) == 2
    assert (
        "Total steps from Sun, Nov 1 to Tue, Nov 3: 30," in result.summary
        and "Median resting heart rate from Sun, Nov 1 to Tue, Nov 3: 54 bpm" in result.summary
    )


def test_missing_rem_does_not_substitute_total_sleep_and_rating_does_not_become_recovery():
    frame = pd.DataFrame(
        {"sleep_minutes": [420] * 4, "recovery_score": [82] * 4, "checkin_rating": [2] * 4},
        index=pd.date_range("2026-11-01", periods=4),
    )
    request = resolve(
        Reading(
            kind="data",
            parts=[Part(metrics=["rem_sleep_minutes", "checkin_rating"], operation="mean")],
        ),
        {},
        TODAY,
    )
    result = execute(request, frame, TODAY)
    assert "doesn't include" in result.summary and "another measure" in result.summary
    assert (
        "Daily average morning check-in rating" in result.summary
        and ": 2" in result.summary
        and "82" not in result.summary
        and "420" not in result.summary
    )


def test_food_uses_local_dates_confirmed_entries_and_preserves_missing_nutrients():
    frame = pd.DataFrame({"calories": [2200] * 3}, index=pd.date_range("2026-11-01", periods=3))
    request = Request(
        kind="data",
        parts=[
            ResolvedPart(
                metrics=["food_logs"],
                operation="food",
                windows=[Window(start="2026-11-17", end="2026-11-17")],
            )
        ],
    )
    entries = [
        {"consumedAt": "2026-11-17T09:00:00+00:00", "energyKcal": 430, "proteinG": 17},
        {"consumedAt": "2026-11-17T13:00:00+00:00", "energyKcal": 610},
        {"consumedAt": "2026-11-18T01:00:00+00:00", "energyKcal": 99},
    ]
    result = execute(request, frame, TODAY, food_logs=entries, zone=UTC)
    stats = next(iter(result.evidence.values())).stats
    assert stats["meals_logged"] == 2 and stats["totals"]["energyKcal"] == 1040
    assert stats["totals"]["proteinG"] == 17 and stats["totals"]["fatG"] is None
    assert stats["entries_with_values"]["proteinG"] == 1
    assert "1,040 kcal" in result.summary and "consumed" in result.summary
    assert "2200" not in result.summary


def test_no_link_requires_relationship_evidence_not_coverage():
    frame = pd.DataFrame({"steps": [1, 2, 3]}, index=pd.date_range(SPAN.start, periods=3))
    record = coverage(frame, SPAN)
    claim = Claim(
        text="No relationship between your steps and sleep was found.",
        kind="no_change",
        metric="steps",
        evidence_ids=[record.id],
    )
    assert any("test" in problem for problem in check_claim(claim, {record.id: record}))


def test_food_readback_filters_meals_and_answers_with_the_confirmed_food_names():
    entries = [
        {
            "consumedAt": "2026-11-17T09:00:00+00:00",
            "foodName": "Example oats",
            "mealType": "BREAKFAST",
            "energyKcal": 310,
        },
        {
            "consumedAt": "2026-11-17T13:00:00+00:00",
            "foodName": "Example lunch",
            "mealType": "LUNCH",
            "energyKcal": 640,
        },
    ]
    request = Request(
        kind="data",
        parts=[
            ResolvedPart(
                metrics=["food_logs"],
                operation="food",
                meal_type="BREAKFAST",
                windows=[Window(start="2026-11-17", end="2026-11-17")],
            )
        ],
    )
    result = execute(request, pd.DataFrame(), TODAY, food_logs=entries, zone=UTC)
    assert "Example oats" in result.summary and "Example lunch" not in result.summary
    assert "310 kcal" in result.summary and "640" not in result.summary


@pytest.mark.parametrize("mode", ["positive", "negative", "constant", "missing"])
def test_causality_follows_observed_association_state(mode):
    a = np.arange(35, dtype=float)
    b = a if mode == "positive" else -a if mode == "negative" else np.ones(35)
    if mode == "missing":
        b[:] = np.nan
    frame = pd.DataFrame({"steps": a, "hrv_ms": b}, index=pd.date_range("2026-10-01", periods=35))
    request = Request(
        kind="causality",
        parts=[ResolvedPart(metrics=["steps", "hrv_ms"], operation="correlate", history=True)],
    )
    result = execute(request, frame, TODAY)
    assert ("tended to move together" in result.summary) == (mode == "positive")
    assert ("opposite directions" in result.summary) == (mode == "negative")
    # The cause line follows a link that was tested, never a result that showed none (the
    # audit of 2026-11-19); the reason no link could be tested is said as it is.
    tested = mode in ("positive", "negative")
    assert ("can't establish or rule out a cause" in result.summary) == tested
    # A question about a cause is answered about the cause either way (Codex's review).
    assert tested or "can't say whether one affects the other" in result.summary
    if mode == "constant":
        assert "didn't change at all" in result.summary
    if mode == "missing":
        assert "never recorded on the same days" in result.summary


@pytest.mark.parametrize(
    "text",
    [
        "I work late but don't save this",
        "Do not remember that I run on Mondays",
        "Off the record, I prefer a short answer",
        "I work nights; no storing this please",
    ],
)
def test_do_not_save_suppresses_the_listener_before_any_model_call(text):
    assert not worth_listening(text)


def test_tomorrow_logging_day_is_not_moved_into_the_past():
    request = resolve(
        Reading(kind="logging", log_day=Period(kind="relative", offset_days=1)), {}, TODAY
    )
    assert request.log_day == date(2026, 11, 19)


def test_threshold_unit_conversion_uses_code_and_rejects_incompatible_units():
    request = resolve(
        Reading(
            kind="data",
            parts=[
                Part(
                    metrics=["sleep_minutes"],
                    operation="count",
                    comparison="<=",
                    threshold=6,
                    threshold_unit="hours",
                )
            ],
        ),
        {},
        TODAY,
    )
    assert request.parts[0].threshold == 360
    with pytest.raises(Ambiguous):
        resolve(
            Reading(
                kind="data",
                parts=[
                    Part(
                        metrics=["steps"],
                        operation="count",
                        comparison="<=",
                        threshold=6,
                        threshold_unit="hours",
                    )
                ],
            ),
            {},
            TODAY,
        )


def test_current_explicit_dates_cannot_be_replaced_by_old_valid_dates():
    held = [Turn("old question", "old answer", request_state=state(previous()))]
    llm = reader(kind="data", parts=[{"operation": "median", "periods": [{"kind": "inherit"}]}])
    request, _, _ = interpret(llm, "Use 2026-11-14 through 2026-11-16 instead", held, TODAY)
    assert request.kind == "clarify" and "dates" in request.clarification


def test_multiple_requested_tests_share_the_same_adjustment_family():
    frame = pd.DataFrame(
        {"steps": np.arange(40), "hrv_ms": np.arange(40) * 2},
        index=pd.date_range("2026-10-01", periods=40),
    )
    request = resolve(
        Reading(kind="data", parts=[Part(metrics=["steps", "hrv_ms"], operation="trend")]),
        {},
        TODAY,
    )
    result = execute(request, frame, TODAY)
    assert len(result.evidence) == 2
    assert all(e.stats["tests_in_run"] == 2 for e in result.evidence.values())
    assert result.budget.tool_calls == 2 and len(result.trace) == 2


def test_reader_failure_preserves_prior_state_and_is_charged_when_billed():
    history = [Turn("earlier", "answer", request_state=state(previous()))]
    llm = ScriptedLLM(request_turns=[ScriptedLLM.say("not structured", cost_usd=0.001)])
    request, held, budget = interpret(llm, "And then?", history, TODAY)
    assert request.kind == "clarify" and held == history[0].request_state
    assert budget.cost_usd == 0.001


def test_strict_reader_schema_constrains_every_nested_object_without_changing_nullable_types():
    schema = strict_schema(Reading.model_json_schema())

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            assert "default" not in node
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for item in node.values():
                walk(item)

    walk(schema)
    assert {v["type"] for v in schema["properties"]["duration_minutes"]["anyOf"]} == {
        "number",
        "null",
    }


def test_non_additive_metric_cannot_sneak_into_a_multipart_total():
    llm = ScriptedLLM(
        request_turns=[
            ScriptedLLM.call(
                "read_request",
                kind="data",
                parts=[
                    {"metrics": ["steps", "resting_hr"], "operation": "sum"},
                    {"metrics": ["resting_hr"], "operation": "mean"},
                ],
            ),
            ScriptedLLM.call(
                "read_request",
                kind="data",
                parts=[
                    {"metrics": ["steps"], "operation": "sum"},
                    {"metrics": ["resting_hr"], "operation": "mean"},
                ],
            ),
        ]
    )
    request, _, budget = interpret(llm, "Total steps and average resting HR", [], TODAY)
    assert [p.metrics for p in request.parts] == [["steps"], ["resting_hr"]]
    assert budget.calls == 2
    assert "additive" in llm.requests[1]["messages"][-1]["content"]


def test_confirmation_without_a_server_draft_is_reinterpreted_as_food_readback():
    llm = ScriptedLLM(
        request_turns=[
            ScriptedLLM.call("read_request", kind="confirmation"),
            ScriptedLLM.call(
                "read_request", kind="data", parts=[{"metrics": ["food_logs"], "operation": "food"}]
            ),
        ]
    )
    request, _, budget = interpret(llm, "Read my already confirmed food", [], TODAY)
    assert request.kind == "data" and request.parts[0].operation == "food"
    assert budget.calls == 2
    assert "no pending draft" in llm.requests[1]["messages"][-1]["content"]


def test_a_real_pending_draft_allows_a_confirmation_but_never_executes_a_write():
    llm = reader(kind="confirmation")
    request, _, budget = interpret(llm, "Looks right", [], TODAY, pending_draft=True)
    assert request.kind == "confirmation" and budget.calls == 1
    assert llm.requests[0]["tools"] == ["read_request"]


def test_reader_repair_is_bounded_and_does_not_fall_back_to_an_unrelated_scope():
    llm = ScriptedLLM(request_turns=[ScriptedLLM.call("read_request", kind="confirmation")] * 3)
    request, _, budget = interpret(llm, "What is recorded?", [], TODAY)
    assert request.kind == "clarify" and not request.parts and budget.calls == 2
    assert len(llm.request_turns) == 1


def test_threshold_comparison_cannot_be_misinterpreted_as_two_identical_windows():
    bad = {
        "metrics": ["steps"],
        "operation": "compare",
        "comparison": "==",
        "threshold": 6000,
        "periods": [{"kind": "explicit", "start": "2026-11-01", "end": "2026-11-07"}] * 2,
    }
    good = bad | {"operation": "count", "periods": bad["periods"][:1]}
    llm = ScriptedLLM(
        request_turns=[
            ScriptedLLM.call("read_request", kind="data", parts=[bad]),
            ScriptedLLM.call("read_request", kind="data", parts=[good]),
        ]
    )
    request, _, budget = interpret(llm, "How many days exactly on the boundary?", [], TODAY)
    assert request.parts[0].operation == "count" and len(request.parts[0].windows) == 1
    assert budget.calls == 2


def test_food_readback_cannot_attach_calories_burned_to_energy_consumed():
    llm = ScriptedLLM(
        request_turns=[
            ScriptedLLM.call(
                "read_request",
                kind="data",
                parts=[{"metrics": ["food_logs", "calories"], "operation": "food"}],
            ),
            ScriptedLLM.call(
                "read_request", kind="data", parts=[{"metrics": ["food_logs"], "operation": "food"}]
            ),
        ]
    )
    request, _, budget = interpret(llm, "Read confirmed breakfast and its energy", [], TODAY)
    assert request.parts[0].metrics == ["food_logs"] and budget.calls == 2


def test_food_readback_is_not_bounded_by_the_wearable_history_start():
    llm = reader(
        kind="data",
        parts=[
            {
                "metrics": ["food_logs"],
                "operation": "food",
                "periods": [{"kind": "explicit", "start": "2026-10-17", "end": "2026-10-17"}],
            }
        ],
    )
    wearable = pd.DataFrame(
        {"steps": [900, 1200, 1500]}, index=pd.date_range("2026-11-01", periods=3)
    )
    entries = [
        {
            "foodName": "Example oats",
            "mealType": "BREAKFAST",
            "energyKcal": 310,
            "consumedAt": "2026-10-17T08:00:00+00:00",
        }
    ]
    result = ask(
        llm,
        KeywordRouter(),
        wearable,
        "Read my confirmed food on 2026-10-17",
        today=TODAY,
        now=datetime(2026, 11, 18, tzinfo=UTC),
        food_logs=entries,
    ).result
    assert "Example oats" in result.summary and "310 kcal" in result.summary


@pytest.mark.parametrize(
    "question, anchor",
    [
        ("What was the total steps last 7 days", "today"),
        ("What is my mean deep sleep minutes yesterday?", "today"),
        ("How many days did I sleep under 7 hours in the past 14 days?", "today"),
        ("And the day before that?", "previous"),  # points at the earlier request
        ("Same measure, 24 hours earlier than that day", "previous"),
    ],
)
def test_a_period_counted_from_today_is_anchored_to_today_by_code(question, anchor):
    """The reader anchored "yesterday" and "last 7 days" to a previous request that did not
    exist, and asked which one was meant on 30 of 50 PHIA questions (2026-11-18)."""
    from app.agent.requests import Part, Period, Reading, anchored_by_code

    period = Period(kind="relative", anchor="previous", offset_days=-1)
    reading = Reading(
        kind="data", parts=[Part(metrics=["steps"], operation="sum", periods=[period])]
    )
    fixed = anchored_by_code(reading, question)
    assert fixed.parts[0].periods[0].anchor == anchor


@pytest.mark.parametrize(
    "question, offset",
    [
        ("What was my average steps last 7 days?", 0),
        ("Total REM sleep over the past 14 days", 0),
        ("Average steps over the 7 complete days ending yesterday", -1),
    ],
)
def test_last_n_days_ends_today_as_everywhere_else_in_the_app(question, offset):
    from app.agent.requests import Part, Period, Reading, anchored_by_code

    period = Period(kind="rolling", anchor="today", offset_days=-1, days=7)
    reading = Reading(
        kind="data", parts=[Part(metrics=["steps"], operation="mean", periods=[period])]
    )
    assert anchored_by_code(reading, question).parts[0].periods[0].offset_days == offset
