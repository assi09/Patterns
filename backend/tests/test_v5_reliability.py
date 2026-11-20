"""Where a request the agent read correctly stopped controlling the answer (the independent audit
of 2026-11-20, docs/pr-195-v5-reliability-plan.md). Each failure sits beside its closest passing
control, and beside nearly identical words that need a different answer, so a fix for one wording
cannot pass by overreaching. Made-up dates, rows and entries only; no model is called.
"""

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from test_action_api import setup, sign_in  # noqa: F401 (the fixture)
from test_broad_questions import END, Router, planted, submit
from test_clauses import data, dates, earlier, read, said, windows
from test_investigate_and_memory import reading_llm

from app.agent.agent import NO_ANSWER, SUBMIT, AgentResult
from app.agent.ask import (
    COACHING_NO_ANSWER,
    MEDICAL_REFUSAL,
    ask,
    coverage_notes,
    described_days,
    one_coaching_conclusion,
    outside_data,
)
from app.agent.context import ChatState, Turn
from app.agent.llm import ScriptedLLM
from app.agent.requested import execute
from app.agent.requests import (
    Ambiguous,
    Period,
    Reading,
    Request,
    ResolvedPart,
    period_window,
    resolve,
    subjects,
)
from app.agent.tools import TOOLS
from app.agent.verifier import Claim
from app.agent.world import answer_world, supporting
from app.analysis.evidence import Evidence, ToolError, Window
from app.api import chat

TODAY = date(2026, 11, 19)


def part(start, end, metric="steps", operation="mean", **extra):
    return ResolvedPart(
        metrics=[metric], operation=operation, windows=[Window(start=start, end=end)], **extra
    )


def codes(request):
    return [c for a in request.attempts for c in a.get("codes", [])]


# ---- a block next to an earlier one, against a shift of it ----

ANCHORS = [date(2028, 2, 26), date(2026, 12, 29), date(2024, 2, 28), date(2026, 3, 1)]


@pytest.mark.parametrize("anchor", ANCHORS)
@pytest.mark.parametrize("before_length", [1, 3, 6])
@pytest.mark.parametrize("length", [1, 5, 6, 31])
def test_the_block_after_or_before_an_earlier_one_adjoins_it(anchor, before_length, length):
    """Over leap days, year ends and earlier periods of other lengths: the next N days start the
    day after the earlier last day, the previous N end the day before its first."""
    earlier_part = part(anchor, anchor + timedelta(days=before_length - 1))
    (after,) = period_window(
        Period(kind="after", anchor="previous", days=length), earlier_part, TODAY
    )
    (before,) = period_window(
        Period(kind="before", anchor="previous", days=length), earlier_part, TODAY
    )
    last, first = earlier_part.windows[0].end, earlier_part.windows[0].start
    assert (after.start, after.end) == (last + timedelta(days=1), last + timedelta(days=length))
    assert (before.start, before.end) == (first - timedelta(days=length), first - timedelta(1))
    assert after.days == before.days == length


TWO_PERIODS = [("2026-10-01", "2026-10-07"), ("2026-11-01", "2026-11-07")]


def compared(first, second):
    windows = [{"start": a, "end": b} for a, b in (first, second)]
    state = {"data": [{"metrics": ["steps"], "operation": "compare", "windows": windows}]}
    return Turn("Compare those two weeks.", "earlier answer", request_state=state)


@pytest.mark.parametrize("order", [TWO_PERIODS, TWO_PERIODS[::-1]])
def test_after_a_comparison_the_block_after_asks_which_period(order):
    """Reversing the two compared periods moved the answer from October to November: a block
    next to "that block" needs one earlier period, as a shift does (review of the local edits)."""
    words = "And the next three days after that block?"
    clause = data(words, ["steps"], "mean", {"kind": "after_earlier", "length": 3})
    request, _ = read(words, said(clause), said(clause), history=[compared(*order)])
    assert request.kind == "clarify" and not request.parts


FOLLOWING = "Recalculate that for the six days immediately following that block."
BLOCK = earlier("2026-10-13", "2026-10-18", "cardio_load", "max")


@pytest.mark.parametrize(
    "moved",
    [
        {"kind": "shift_earlier", "days": 1},
        # the form the v5 audit's reading took: six days ending the day after the block
        {"kind": "days_ending", "length": 6, "ending": "earlier_end", "offset": 1},
    ],
)
def test_the_six_days_following_a_block_are_the_next_block_not_the_block_moved_a_day(moved):
    moved_a_day = data(FOLLOWING, ["cardio_load"], "max", moved)
    next_block = data(FOLLOWING, ["cardio_load"], "max", {"kind": "after_earlier", "length": 6})
    request, calls = read(FOLLOWING, said(moved_a_day), said(next_block), history=[BLOCK])
    assert windows(request) == [(date(2026, 10, 19), date(2026, 10, 24))]
    assert "adjacent" in codes(request) and calls == 2


@pytest.mark.parametrize(
    "words",
    [
        "Move that range forward one day.",
        "Same thing, shifted one day later.",
    ],
)
def test_moving_the_range_a_day_is_a_shift_and_passes_first_time(words):
    """The minimal pair: these do mean the old block moved by one day."""
    shift = data(words, ["cardio_load"], "max", {"kind": "shift_earlier", "days": 1})
    request, calls = read(words, said(shift), history=[BLOCK])
    assert windows(request) == [(date(2026, 10, 14), date(2026, 10, 19))] and calls == 1


@pytest.mark.parametrize(
    "words",
    [FOLLOWING, "Now give me the next six days after that.", "And the 6 days right after those?"],
)
def test_a_next_block_said_any_way_passes_first_time(words):
    clause = data(words, ["cardio_load"], "max", {"kind": "after_earlier", "length": 6})
    request, calls = read(words, said(clause), history=[BLOCK])
    assert windows(request) == [(date(2026, 10, 19), date(2026, 10, 24))] and calls == 1


def test_the_block_before_an_earlier_one_ends_the_day_before_it():
    words = "What about the 5 days before that block?"
    clause = data(words, ["cardio_load"], "max", {"kind": "before_earlier", "length": 5})
    request, calls = read(words, said(clause), history=[BLOCK])
    assert windows(request) == [(date(2026, 10, 8), date(2026, 10, 12))] and calls == 1


# ---- "that day" as an endpoint, against "that day" as the days ----

LEAP = earlier("2028-03-02", "2028-03-02")
LAST_OF_FIVE = (
    "Take that day as the last of five consecutive days. How many steps per day on average?"
)


def test_that_day_as_the_last_of_five_keeps_five_days_across_a_leap_day():
    """The checker sent the right reading back under same_days, and the retry gave one day."""
    five = data(
        LAST_OF_FIVE,
        ["steps"],
        "mean",
        {"kind": "days_ending", "length": 5, "ending": "earlier_end", "offset": 0},
        earlier_result=0,
    )
    request, calls = read(LAST_OF_FIVE, said(five), history=[LEAP], today=date(2028, 3, 5))
    assert windows(request) == [(date(2028, 2, 27), date(2028, 3, 2))] and calls == 1


def test_that_day_alone_for_the_last_of_five_is_sent_back_for_its_length():
    one_day = data(LAST_OF_FIVE, ["steps"], "mean", {"kind": "same_as_earlier"}, earlier_result=0)
    five = data(
        LAST_OF_FIVE,
        ["steps"],
        "mean",
        {"kind": "days_ending", "length": 5, "ending": "earlier_end", "offset": 0},
        earlier_result=0,
    )
    request, _ = read(
        LAST_OF_FIVE, said(one_day), said(five), history=[LEAP], today=date(2028, 3, 5)
    )
    assert windows(request) == [(date(2028, 2, 27), date(2028, 3, 2))]
    assert "length" in codes(request)


def test_that_same_day_still_keeps_the_day():
    words = "What was my resting heart rate on that same day?"
    clause = data(words, ["resting_hr"], "value", {"kind": "same_as_earlier"}, earlier_result=0)
    request, calls = read(words, said(clause), history=[LEAP], today=date(2028, 3, 5))
    assert windows(request) == [(date(2028, 3, 2), date(2028, 3, 2))] and calls == 1


# ---- a threshold edit keeps the dates ----

COUNTED = Turn(
    "How many days from Nov 11 through Nov 19 finished with 7,100 steps or fewer?",
    "5 of 9 days; 2 days exactly at 7,100.",
    request_state={
        "data": [
            {
                "metrics": ["steps"],
                "operation": "count",
                "windows": [{"start": "2026-11-11", "end": "2026-11-19"}],
                "comparison": "<=",
                "threshold": 7100,
            }
        ]
    },
)
EXCLUDE = "Exclude the days right on the boundary and count again."


def test_excluding_the_boundary_makes_the_comparison_strict_and_keeps_the_dates():
    trimmed = data(
        EXCLUDE,
        ["steps"],
        "count",
        dates("2026-11-12", "2026-11-18"),
        comparison="<=",
        threshold=7100,
        earlier_result=0,
    )
    strict = data(
        EXCLUDE, ["steps"], "count", {"kind": "same_as_earlier"}, comparison="<", earlier_result=0
    )
    request, _ = read(EXCLUDE, said(trimmed), said(strict), history=[COUNTED])
    (counted,) = request.parts
    assert windows(request) == [(date(2026, 11, 11), date(2026, 11, 19))]
    assert (counted.comparison, counted.threshold) == ("<", 7100)
    assert {"strict", "kept_days"} & set(codes(request))


def test_a_new_threshold_on_the_same_days_passes():
    words = "Count again, but for at least 9000 steps."
    clause = data(
        words,
        ["steps"],
        "count",
        {"kind": "same_as_earlier"},
        comparison=">=",
        threshold=9000,
        earlier_result=0,
    )
    request, calls = read(words, said(clause), history=[COUNTED])
    assert request.parts[0].comparison == ">=" and calls == 1


# ---- a named month is that month ----

JANUARY = "Now look into my sleep during January 2027 instead."


def investigate(words, *periods, metrics=("sleep_minutes",), **extra):
    return {
        "type": "investigate",
        "said": words,
        "focus": "overview",
        "metrics": list(metrics),
        "periods": list(periods),
        **extra,
    }


def test_a_named_future_month_is_that_month_not_this_one():
    this_month = investigate(JANUARY, {"kind": "calendar", "unit": "month", "offset": 0})
    january = investigate(JANUARY, {"kind": "month", "year": 2027, "month": 1})
    request, _ = read(JANUARY, said(this_month), said(january), history=[LEAP])
    assert windows(request) == [(date(2027, 1, 1), date(2027, 1, 31))]
    assert "named_month" in codes(request)


@pytest.mark.parametrize(
    "words, periods, operation",
    [
        (
            "What was my daily average step count from January 2026 through March 2026?",
            [dates("2026-01-01", "2026-03-31")],
            "mean",
        ),
        (
            "Compare January with March 2026 for steps.",
            [
                {"kind": "month", "year": 2026, "month": 1},
                {"kind": "month", "year": 2026, "month": 3},
            ],
            "compare",
        ),
        ("My average steps in October?", [{"kind": "month", "year": 2026, "month": 10}], "mean"),
        (
            "Steps this month so far, November?",
            [{"kind": "calendar", "unit": "month", "offset": 0}],
            "mean",
        ),
    ],
)
def test_a_month_range_and_two_months_are_checked_differently(words, periods, operation):
    """A range from one month through another is one period; "compare January with March" is two
    (review of the local edits: the range was asked "Do you mean January 2026?")."""
    request, calls = read(words, said(data(words, ["steps"], operation, *periods)))
    assert request.kind == "data" and calls == 1


def test_compare_two_months_read_as_one_range_is_sent_back():
    words = "Compare January with March 2026 for steps."
    one = data(words, ["steps"], "mean", dates("2026-01-01", "2026-03-31"))
    request, _ = read(words, said(one), said(one))
    assert request.kind == "clarify" and "named_month" in codes(request)


# ---- what an investigation's days have, said per metric and period ----


def frame_until(last: date, metrics=("steps", "sleep_minutes")):
    index = pd.date_range(last - timedelta(days=59), last, freq="D")
    return pd.DataFrame({m: 7000.0 for m in metrics}, index=index)


def investigation(*windows_, metrics=("sleep_minutes",)):
    return Request(
        kind="investigate",
        focus="overview",
        parts=[
            ResolvedPart(
                metrics=list(metrics),
                operation="describe",
                windows=[Window(start=a, end=b) for a, b in windows_],
            )
        ],
    )


def test_a_future_month_is_said_not_to_have_happened():
    gap = outside_data(investigation(("2027-01-01", "2027-01-31")), frame_until(TODAY), TODAY)
    assert gap and "haven't happened yet" in gap


def test_days_the_data_reaches_without_the_asked_metric_are_still_missing():
    frame = frame_until(TODAY)
    frame.loc["2026-11-01":, "sleep_minutes"] = float("nan")
    gap = outside_data(investigation(("2026-11-02", "2026-11-08")), frame, TODAY)
    assert gap and "no time asleep" in gap
    assert (
        outside_data(investigation(("2026-11-02", "2026-11-08"), metrics=("steps",)), frame, TODAY)
        is None
    )


def test_one_metric_missing_beside_another_is_said_and_pairs_are_counted():
    """Two days of steps hid zero HRV readings when days were counted for any metric."""
    frame = frame_until(TODAY, ("steps", "hrv_ms"))
    frame["hrv_ms"] = float("nan")
    both = investigation(("2026-11-18", "2026-11-19"), metrics=("steps", "hrv_ms"))
    assert outside_data(both, frame, TODAY) is None  # steps are there to look at
    notes = coverage_notes(both, frame, TODAY)
    assert any("no heart rate variability" in n and "only steps" in n for n in notes)
    frame.loc["2026-11-18", "hrv_ms"] = 40.0
    frame.loc["2026-11-18", "steps"] = float("nan")
    notes = coverage_notes(both, frame, TODAY)
    assert any("recorded together on 0 of the 2 days" in n for n in notes)
    assert outside_data(
        investigation(("2026-11-18", "2026-11-19"), metrics=("hrv_ms",)),
        frame_until(TODAY, ("steps", "hrv_ms")).assign(hrv_ms=float("nan")),
        TODAY,
    )


def test_fully_recorded_metrics_get_no_notes():
    frame = frame_until(TODAY, ("steps", "hrv_ms"))
    both = investigation(("2026-11-10", "2026-11-19"), metrics=("steps", "hrv_ms"))
    assert coverage_notes(both, frame, TODAY) == []


def test_a_missing_baseline_and_a_partly_covered_period_are_noted():
    frame = frame_until(TODAY)
    notes = coverage_notes(
        investigation(("2026-11-15", "2026-11-25"), ("2026-01-01", "2026-01-07")), frame, TODAY
    )
    assert any("to compare with" in n for n in notes)
    assert any("5 of the 11 days" in n for n in notes)


def test_an_investigation_with_no_verified_answer_describes_its_own_days():
    frame = frame_until(TODAY)
    result = AgentResult(run_id="x", stop_reason="no_submission", summary=NO_ANSWER)
    typed = investigation(("2026-10-09", "2026-10-10"), metrics=("sleep_minutes", "steps"))
    described_days(result, typed, frame, TODAY, (), None)
    assert result.summary != NO_ANSWER and len(result.claims) == 2
    assert all(e.windows[0].start == date(2026, 10, 9) for e in result.cited_evidence.values())


# ---- a count is of days past a threshold, a step count is a value ----

PARTNER = "My doubles partner is curious about my own steps on Nov 5. What is the count?"


def test_the_count_of_one_day_is_its_value_not_a_threshold_question():
    count = data(PARTNER, ["steps"], "count", dates("2026-11-05"))
    value = data(PARTNER, ["steps"], "value", dates("2026-11-05"))
    request, calls = read(PARTNER, said(count), said(value))
    assert request.parts[0].operation == "value" and calls == 2


def test_counting_days_without_a_threshold_still_asks_for_one():
    words = "How many days last week did I hit my steps?"
    count = data(words, ["steps"], "count", {"kind": "calendar", "unit": "week", "offset": -1})
    request, _ = read(words, said(count))
    assert request.kind == "clarify" and "threshold" in request.clarification


# ---- confirmed food is one source ----

BREAKFAST = "Read back my November 17 breakfast energy in kcal."
PROTEIN = "And how much protein was in everything I logged eating on that date combined?"


def logged(meal, day, kcal, protein):
    return {
        "kind": "food",
        "foodName": f"Example {meal.lower()}",
        "mealType": meal,
        "consumedAt": f"{day}T08:30:00+00:00",
        "energyKcal": kcal,
        "proteinG": protein,
    }


FOOD = [
    logged("BREAKFAST", "2026-11-17", 410, 22),
    logged("LUNCH", "2026-11-17", 600, 35),
    logged("BREAKFAST", "2026-11-18", 999, 99),
]


def test_a_named_nutrient_reads_the_confirmed_meal_and_its_follow_up_keeps_the_day():
    energy = data(BREAKFAST, ["energy_kcal"], "food", dates("2026-11-17"), meal_type="BREAKFAST")
    first, calls = read(BREAKFAST, said(energy))
    assert first.parts[0].metrics == ["food_logs"] and calls == 1
    state = {"data": [p.model_dump(mode="json") for p in first.parts]}
    protein = data(PROTEIN, ["protein"], "sum", {"kind": "same_as_earlier"}, earlier_result=0)
    second, _ = read(PROTEIN, said(protein), history=[Turn(BREAKFAST, "", request_state=state)])
    (food,) = second.parts
    assert (food.metrics, food.operation, food.meal_type) == (["food_logs"], "food", None)
    assert windows(second) == [(date(2026, 11, 17), date(2026, 11, 17))]
    text = execute(second, frame_until(TODAY), TODAY, food_logs=FOOD).summary
    assert "2 entries" in text and "Protein: 57 g" in text


def test_steps_and_protein_in_one_clause_are_split_and_both_answered():
    """The steps were silently dropped when one clause named both (review of the local edits)."""
    words = "What were my total steps and protein on Nov 17?"
    both = data(words, ["steps", "protein"], "sum", dates("2026-11-17"))
    split = said(
        data("my total steps", ["steps"], "sum", dates("2026-11-17")),
        data("protein on Nov 17", ["food_logs"], "food", dates("2026-11-17")),
    )
    request, _ = read(words, said(both), split)
    assert [p.metrics for p in request.parts] == [["steps"], ["food_logs"]]
    text = execute(request, frame_until(TODAY), TODAY, food_logs=FOOD).summary
    assert "Total steps" in text and "Protein: 57 g" in text


def test_calories_alone_stay_energy_burned():
    words = "My total calories burned on Nov 17?"
    request, _ = read(words, said(data(words, ["calories"], "sum", dates("2026-11-17"))))
    assert request.parts[0].metrics == ["calories"]


# ---- the boundary, and the words beside it ----


def test_an_explicit_diagnosis_request_gets_the_boundary_and_no_data():
    llm = reading_llm(submit(), kind="investigate", focus="why", parts=[])
    reply = ask(llm, Router("why"), planted(), "Diagnose me from that number.", today=END)
    assert reply.result.summary == MEDICAL_REFUSAL and reply.route.action == "refuse"
    assert not reply.result.evidence


def test_an_ordinary_what_changed_is_still_investigated():
    llm = reading_llm(submit(), kind="investigate", focus="what_changed", parts=[])
    reply = ask(llm, Router("change"), planted(), "What changed in my steps lately?", today=END)
    assert reply.result.summary != MEDICAL_REFUSAL and reply.route.action != "refuse"


def test_whether_a_preference_is_still_saved_is_answered_from_memory():
    words = "What outdoor preference is still saved?"
    status = {"type": "status", "said": words, "about": "memory"}
    request, _ = read(words, said(status))
    assert (request.kind, request.memory_action, request.recall) == ("memory", "recall", "kept")
    chat_state = ChatState(kept=("Likes hiking",))
    llm = reading_llm(kind="status", status=True)
    reply = ask(llm, Router("lookup"), planted(), words, today=END, chat=chat_state)
    assert "Likes hiking" in reply.result.summary


def test_whether_the_workout_is_saved_is_still_the_tracker():
    llm = reading_llm(kind="status", status=True)
    reply = ask(
        llm,
        Router("lookup"),
        planted(),
        "Is that walk saved to my tracker yet?",
        today=END,
        action_states=["draft"],
    )
    assert reply.result.summary.startswith("Not yet")


# ---- coaching ends on one conclusion ----


def habits(supported: bool) -> Evidence:
    lever = {"habit": "being in bed by 23:00", "supported": supported}
    return Evidence(
        tool="habit_options",
        metrics=["sleep_minutes"],
        windows=[Window(start="2026-11-01", end="2026-11-14")],
        stats={"levers": [lever]},
        n=14,
        sufficient=True,
    )


def observation() -> Claim:
    return Claim(
        text="Time asleep fell.", kind="change", evidence_ids=["e1"], metric="sleep_minutes"
    )


@pytest.mark.parametrize(
    "summary",
    [
        "You could try a small change to your bedtime so you spend more time in bed.",
        "An earlier bedtime is the best move for you.",  # no advice word (review of 1e29f3a)
        "Go to bed earlier.",
        COACHING_NO_ANSWER,
        "Your sleep dipped mid-month.",
    ],
)
@pytest.mark.parametrize("supported", [True, False, None])
def test_coaching_says_one_thing_whatever_the_prose_said(summary, supported):
    """The v5 audit: a bedtime suggestion then "none was supported", and "I don't see anything"
    then a supported bedtime. With no suggestion claim of its own, the prose goes, however it is
    worded; the reply as the API assembles it is the observations and code's one conclusion."""
    result = AgentResult(
        run_id="x", stop_reason="submitted", summary=summary, claims=[observation()]
    )
    one_coaching_conclusion(result, [] if supported is None else [habits(supported)])
    shown = chat.answer_text(result.summary, [c.text for c in result.claims], result.notes)
    assert summary not in shown
    assert shown.startswith("Time asleep fell.")
    assert ("One option your own days support" in shown) == (supported is True)
    assert ("None of the everyday habits" in shown) == (supported is False)
    assert ("isn't enough" in shown) == (supported is None)
    if supported is not None:
        outcome = result.claims[-1]
        assert outcome.kind == ("suggestion" if supported else "no_change")
        assert outcome.evidence_ids[0] in result.evidence


def test_too_little_data_is_said_with_no_claim():
    result = AgentResult(run_id="x", stop_reason="submitted", summary=COACHING_NO_ANSWER)
    one_coaching_conclusion(result, [])
    assert "isn't enough" in result.summary and not result.claims


def test_unsupported_advice_claims_go_with_the_prose():
    advice = Claim(text="Try an earlier bedtime.", kind="guidance", evidence_ids=["p1"])
    result = AgentResult(
        run_id="x", stop_reason="submitted", summary="x", claims=[observation(), advice]
    )
    one_coaching_conclusion(result, [habits(False)])
    assert [c.kind for c in result.claims] == ["change", "no_change"]


def test_a_part_of_a_whole_cannot_explain_the_whole():
    frame = frame_until(TODAY, ("sleep_minutes", "time_in_bed", "steps"))
    run = TOOLS["correlate"]
    args = run.arguments(
        driver="time_in_bed", target="sleep_minutes", start="2026-10-01", end="2026-11-19"
    )
    with pytest.raises(ToolError):
        run.run(frame, args)


# ---- guidance keeps its movement ----


def test_a_qualifier_is_part_of_the_movement_and_its_follow_up_resolves():
    asked = Reading(
        kind="guidance",
        topics=["basic floor pushup", "no equipment"],
        guidance_question="How do I set up?",
    )
    first = resolve(asked, {}, TODAY)
    assert first.topics == ["basic floor pushup (no equipment)"]
    follow = Reading(
        kind="guidance",
        guidance_reference=True,
        guidance_question="How do I lower myself in that version?",
    )
    second = resolve(follow, {"guidance": first.topics}, TODAY)
    assert second.topics == first.topics and "basic floor pushup" in second.guidance_question


def test_two_movements_are_asked_about_by_name():
    follow = Reading(kind="guidance", guidance_reference=True, guidance_question="And lowering?")
    with pytest.raises(Ambiguous, match="plank or pushup"):
        resolve(follow, {"guidance": subjects(["plank", "pushup"])}, TODAY)


SUPERMAN = "exercises-27d5233ddd89"


def says(text):
    from app.agent.llm import Completion, Usage

    return Completion(text, (), "scripted", Usage(), 0.0, 0.0)


def test_a_known_topic_with_its_passages_reads_them_before_choosing_a_source():
    """The Superman follow-up went to the web and was refused, its passage never read."""
    llm = ScriptedLLM(
        [says("Lift your arms and legs off the floor together.")], embeddings_fail=True
    )
    outside = SimpleNamespace(web=lambda *args: pytest.fail("the web was asked"))
    result = answer_world(
        llm, "What does the source say I should lift?", outside, topic="Superman", active=[SUPERMAN]
    )
    assert result.stop_reason == "looked_up" and len(llm.requests) == 1
    assert any(s.get("active_topic") for s in result.trace)


def test_without_earlier_passages_the_source_is_still_chosen():
    llm = ScriptedLLM([says("no")], embeddings_fail=True)
    result = answer_world(llm, "Which supplement should I take?", None, topic="Superman")
    assert result.stop_reason == "lookup_declined"


def test_only_passages_behind_the_reply_are_cited():
    def passage(text):
        return Evidence(
            tool="knowledge",
            metrics=[],
            windows=[],
            n=1,
            sufficient=True,
            stats={"text": text, "passage_id": uuid.uuid4().hex},
        )

    basic = passage("Lie face down, hands under your shoulders, lower your chest to the floor.")
    other = passage("Place your feet on a bench and hold dumbbells overhead.")
    reply = "Lie face down with your hands under your shoulders, then lower your chest."
    assert supporting(reply, [basic, other]) == [basic]


# ---- every requested outcome reaches the reply, the store and the reopened chat ----


def local(day: date, hour: int, minute: int = 0) -> datetime:
    from zoneinfo import ZoneInfo

    from app.config import settings

    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(settings.timezone))


DAY = date(2026, 7, 20)  # inside the fixture's synthetic history


def reader_said(*clauses, store_nothing=False):
    return ScriptedLLM.call("read_request", **said(*clauses, store_nothing=store_nothing))


def walk(start: datetime, minutes: int, active: int | None = None) -> dict:
    return {
        "kind": "workout",
        "exerciseType": "WALKING",
        "startTime": start.isoformat(),
        "endTime": (start + timedelta(minutes=minutes)).isoformat(),
        "activeSeconds": (active or minutes) * 60,
    }


def test_a_read_and_a_log_in_one_message_both_happen(setup):  # noqa: F811
    client, _, agent = setup
    headers = sign_in(setup)
    words = "Read my July 20 steps and draft a 12-minute walk that started that day at 10:00."
    agent.llm.request_turns = [
        reader_said(
            data("Read my July 20 steps", ["steps"], "value", dates(DAY.isoformat())),
            {
                "type": "log",
                "said": "draft a 12-minute walk that started that day at 10:00",
                "entry": "workout",
                "duration_minutes": 12,
                "on_date": DAY.isoformat(),
                "days_from_today": None,
            },
        )
    ]
    agent.llm.turns = [
        ScriptedLLM.call("propose_workout_log", **walk(local(DAY, 10), 12)),
        ScriptedLLM.call(SUBMIT, summary="Draft ready.", claims=[]),
    ]
    reply = client.post("/chat", headers=headers, json={"text": words}).json()[-1]
    assert len(reply["actionIds"]) == 1 and "Ready to log" in reply["text"]
    assert "Steps on" in reply["text"] and reply["evidenceIds"]
    reopened = client.get("/chat", headers=headers).json()[-1]
    assert reopened["evidenceIds"] == reply["evidenceIds"]
    for evidence_id in reply["evidenceIds"]:
        assert client.get(f"/evidence/{evidence_id}", headers=headers).status_code == 200


def log_first(client, headers, agent, payload, words):
    agent.llm.request_turns = [
        reader_said(
            {
                "type": "log",
                "said": words,
                "entry": "workout",
                "duration_minutes": None,
                "on_date": None,
                "days_from_today": None,
            }
        )
    ]
    agent.llm.turns = [
        ScriptedLLM.call("propose_workout_log", **payload),
        ScriptedLLM.call(SUBMIT, summary="Draft ready.", claims=[]),
    ]
    first = client.post("/chat", headers=headers, json={"text": words}).json()[-1]
    assert first["actionIds"]
    return first


def test_a_status_beside_a_read_keeps_the_reads_evidence_after_reopening(setup):  # noqa: F811
    client, _, agent = setup
    headers = sign_in(setup)
    start = datetime.now(UTC) - timedelta(hours=3)
    first = log_first(client, headers, agent, walk(start, 19), "Log my 19 minute walk.")
    words = "How many steps did I take on July 20, and is that draft already on my tracker?"
    agent.llm.request_turns = [
        reader_said(
            data(
                "How many steps did I take on July 20", ["steps"], "value", dates(DAY.isoformat())
            ),
            {"type": "status", "said": "is that draft already on my tracker?", "about": "entry"},
        )
    ]
    reply = client.post(
        "/chat", headers=headers, json={"text": words, "conversationId": first["conversationId"]}
    ).json()[-1]
    assert reply["text"].startswith("Not yet") and "Steps on" in reply["text"]
    assert reply["evidenceIds"]
    reopened = client.get(
        "/chat", headers=headers, params={"conversation": first["conversationId"]}
    ).json()[-1]
    assert reopened["evidenceIds"] == reply["evidenceIds"]
    assert client.get(f"/evidence/{reply['evidenceIds'][0]}", headers=headers).status_code == 200
    other = sign_in(setup, "other@example.com")
    assert client.get(f"/evidence/{reply['evidenceIds'][0]}", headers=other).status_code == 404


CORRECTION = "The duration on the draft should be eight minutes instead. Leave the start alone."


def correct(client, headers, agent, first, summary=NO_ANSWER):
    agent.llm.request_turns = [
        reader_said(
            {
                "type": "correct",
                "said": CORRECTION,
                "duration_minutes": 8,
                "on_date": None,
                "days_from_today": None,
            }
        )
    ]
    agent.llm.turns = [ScriptedLLM.call(SUBMIT, summary=summary, claims=[])]
    return client.post(
        "/chat",
        headers=headers,
        json={"text": CORRECTION, "conversationId": first["conversationId"]},
    ).json()[-1]


@pytest.mark.parametrize("kind", ["WALKING", "RUNNING"])
def test_a_duration_correction_the_model_did_not_make_is_made_by_code(setup, kind):  # noqa: F811
    """The run's correction asked to rephrase and kept the old duration (the v5 audit)."""
    client, _, agent = setup
    headers = sign_in(setup)
    start = datetime.now(UTC) - timedelta(hours=3)
    payload = walk(start, 32) | {"exerciseType": kind}
    first = log_first(client, headers, agent, payload, "Log my 32 minute workout.")
    second = correct(client, headers, agent, first)
    assert second["actionIds"] and second["actionIds"] != first["actionIds"]
    assert "Ready to log" in second["text"] and "8 min" in second["text"]
    entries = {e["id"]: e for e in client.get("/actions", headers=headers).json()}
    old, new = entries[first["actionIds"][0]], entries[second["actionIds"][0]]
    assert old["status"] == "cancelled" and new["status"] == "draft"
    assert new["log"]["activeSeconds"] == 480 and new["log"]["exerciseType"] == kind
    assert datetime.fromisoformat(new["log"]["startTime"]) == start
    assert datetime.fromisoformat(new["log"]["endTime"]) == start + timedelta(minutes=8)


def test_a_correction_that_cannot_be_made_keeps_the_old_card_and_says_so(setup):  # noqa: F811
    """A paused workout: "the duration" could be active or elapsed time, so code makes nothing."""
    client, _, agent = setup
    headers = sign_in(setup)
    start = datetime.now(UTC) - timedelta(hours=3)
    words = "Log my walk: 30 minutes of walking, with a 10 minute pause, 40 minutes in all."
    first = log_first(client, headers, agent, walk(start, 40, active=30), words)
    second = correct(client, headers, agent, first)
    assert not second.get("actionIds") and "still waiting as it was" in second["text"]
    entries = {e["id"]: e for e in client.get("/actions", headers=headers).json()}
    assert entries[first["actionIds"][0]]["status"] == "draft"
    assert entries[first["actionIds"][0]]["log"]["activeSeconds"] == 1800


def test_no_reply_claims_a_draft_the_store_does_not_have(setup):  # noqa: F811
    client, _, agent = setup
    headers = sign_in(setup)
    words = "Okay, submit that one."
    chatty = replace(agent, router=Router("chat"))  # answered in the model's own words
    client.app.dependency_overrides[chat.get_agent] = lambda: chatty
    agent.llm.request_turns = [reader_said({"type": "other", "said": words})]
    agent.llm.turns = [says("Done, I've got that walk drafted for you.")] * 3
    reply = client.post("/chat", headers=headers, json={"text": words}).json()[-1]
    assert "drafted" not in reply["text"] and "nothing waiting" in reply["text"].lower()
    assert all(e["status"] != "succeeded" for e in client.get("/actions", headers=headers).json())


# ---- memory: what is stored, what is only said, what is only read ----

KAYAK = "Just here in this chat, I like kayaking on weekends. Keep that out of my saved profile."


def test_keeping_a_chat_statement_out_of_memory_is_not_a_forget(setup):  # noqa: F811
    client, _, agent = setup
    headers = sign_in(setup)
    forget = {
        "type": "memory",
        "said": KAYAK,
        "action": "forget",
        "recall": None,
        "states_new_fact": False,
    }
    agent.llm.request_turns = [reader_said(forget, store_nothing=True)]
    reply = client.post("/chat", headers=headers, json={"text": KAYAK}).json()[-1]
    assert reply["text"].startswith("Okay, I won't keep anything") and "forget" not in reply["text"]
    kept = client.get("/memory", headers=headers).json()
    assert kept["waiting"] == [] and kept["kept"] == []


@pytest.mark.parametrize(
    "clause, listened",
    [
        (
            {
                "type": "memory",
                "said": "Remind me what I said here about weekends.",
                "action": "recall",
                "recall": "this_chat",
                "states_new_fact": False,
            },
            False,
        ),
        (
            data(
                "How many steps did I take on July 20?", ["steps"], "value", dates(DAY.isoformat())
            ),
            True,
        ),
    ],
)
def test_a_readback_is_never_listened_to_for_new_facts(setup, monkeypatch, clause, listened):  # noqa: F811
    client, _, agent = setup
    headers = sign_in(setup)
    heard = []
    monkeypatch.setattr(chat, "listen_to", lambda *args, **kw: heard.append(args) or [])
    monkeypatch.setattr(chat, "update_summary", lambda *args: None)
    monkeypatch.setattr(chat, "_pool", Synchronous(chat._pool))
    listening = replace(agent, background=True)
    client.app.dependency_overrides[chat.get_agent] = lambda: listening
    words = clause["said"]
    agent.llm.request_turns = [reader_said(clause)]
    client.post("/chat", headers=headers, json={"text": words})
    assert bool(heard) == listened


class Synchronous:
    """The chat pool, with background work run at once so a test can see it."""

    def __init__(self, pool):
        self.pool = pool

    def submit(self, fn, *args, **kwargs):
        if fn is chat._answer:
            return self.pool.submit(fn, *args, **kwargs)
        fn(*args, **kwargs)


# ---- a corrected day keeps the local clock time, across daylight saving ----

BEIRUT = "Asia/Beirut"  # leaves summer time on Sunday, Oct 25, 2026


@pytest.mark.parametrize("moved_to", [date(2026, 10, 27), date(2026, 10, 20), date(2026, 3, 30)])
def test_a_workout_moved_to_another_day_keeps_its_local_clock_time(moved_to):
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(BEIRUT)
    start = datetime(2026, 10, 23, 12, 0, tzinfo=zone)
    prior = walk(start.astimezone(UTC), 30)
    moved = chat.corrected_payload(prior, None, moved_to, zone)
    new_start = datetime.fromisoformat(moved["startTime"]).astimezone(zone)
    new_end = datetime.fromisoformat(moved["endTime"])
    assert (new_start.date(), new_start.hour, new_start.minute) == (moved_to, 12, 0)
    assert new_end - datetime.fromisoformat(moved["startTime"]) == timedelta(minutes=30)
    assert moved["activeSeconds"] == 1800


def test_a_meal_moved_to_another_day_keeps_its_local_clock_time():
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(BEIRUT)
    eaten = datetime(2026, 10, 23, 8, 30, tzinfo=zone).astimezone(UTC)
    prior = logged("BREAKFAST", "2026-10-23", 400, 20) | {"consumedAt": eaten.isoformat()}
    moved = chat.corrected_payload(prior, None, date(2026, 10, 27), zone)
    local = datetime.fromisoformat(moved["consumedAt"]).astimezone(zone)
    assert (local.date(), local.hour, local.minute) == (date(2026, 10, 27), 8, 30)


def test_a_new_duration_keeps_the_start_instant():
    from zoneinfo import ZoneInfo

    start = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
    moved = chat.corrected_payload(walk(start, 30), 8, None, ZoneInfo(BEIRUT))
    assert datetime.fromisoformat(moved["startTime"]) == start
    assert datetime.fromisoformat(moved["endTime"]) == start + timedelta(minutes=8)


# ---- a workout that itself spans a clock change keeps its real elapsed time ----

NEW_YORK = "America/New_York"


@pytest.mark.parametrize(
    "day, clock, label_",
    [
        (date(2026, 11, 1), (0, 30), "fall back: 01:00-02:00 happens twice"),
        (date(2026, 3, 8), (1, 30), "spring forward: 02:00-03:00 never happens"),
    ],
)
@pytest.mark.parametrize("active_minutes", [120, 90])  # 90: a paused workout
def test_a_workout_moved_onto_a_clock_change_keeps_its_elapsed_and_active_time(
    day, clock, label_, active_minutes
):
    """Review of d7692d5: a two-hour workout moved to 00:30 on Nov 1 in New York became three
    elapsed hours while two stayed active. The start keeps its local clock time on the new day;
    the end is that instant plus the real elapsed time."""
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(NEW_YORK)
    before = datetime(2026, 10, 20, *clock, tzinfo=zone).astimezone(UTC)
    prior = walk(before, 120, active=active_minutes)
    moved = chat.corrected_payload(prior, None, day, zone)
    start = datetime.fromisoformat(moved["startTime"])
    end = datetime.fromisoformat(moved["endTime"])
    assert end - start == timedelta(hours=2), label_
    assert start.astimezone(zone).replace(tzinfo=None) == datetime(
        day.year, day.month, day.day, *clock
    )
    assert moved["activeSeconds"] == active_minutes * 60
    assert start.utcoffset() != end.utcoffset()  # the card shows both local offsets


def test_a_new_duration_on_a_clock_change_day_is_real_minutes():
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(NEW_YORK)
    start = datetime(2026, 11, 1, 0, 30, tzinfo=zone).astimezone(UTC)
    moved = chat.corrected_payload(walk(start, 30), 120, None, zone)
    elapsed = datetime.fromisoformat(moved["endTime"]) - datetime.fromisoformat(moved["startTime"])
    assert elapsed == timedelta(hours=2) and moved["activeSeconds"] == 7200


# ---- every overview finding is cited, after the chat is reopened ----


@pytest.fixture(scope="module")
def two_changes():
    from test_broad_questions import ON

    from app.synthetic import Step

    return planted(Step("steps", ON, -5000.0), Step("sleep_minutes", ON, -90.0))


def overview(frame):
    from app.agent.strategy import overview_evidence

    records, _ = overview_evidence(frame, "How have I been?", END)
    return {r.metrics[0]: r for r in records}


def test_each_named_finding_gets_its_own_evidence(two_changes):
    from app.agent.findings import cite_findings

    records = overview(two_changes)
    result = AgentResult(
        run_id="x",
        stop_reason="submitted",
        summary="Your steps dropped and your time asleep fell. "
        "Your resting heart rate held steady.",
    )
    cite_findings(result, list(records.values()))
    cited = {c.metric: c.evidence_ids for c in result.claims}
    assert cited["steps"] == [records["steps"].id]
    assert cited["sleep_minutes"] == [records["sleep_minutes"].id]
    assert cited["resting_hr"] == [records["resting_hr"].id]
    assert all(i in result.evidence for ids in cited.values() for i in ids)


def test_a_finding_its_evidence_contradicts_is_left_out(two_changes):
    from app.agent.findings import cite_findings

    records = overview(two_changes)
    result = AgentResult(
        run_id="x",
        stop_reason="submitted",
        summary="Your steps dropped. Your resting heart rate shot up and climbed higher.",
    )
    cite_findings(result, list(records.values()))
    assert result.summary == "Your steps dropped."
    assert [c.metric for c in result.claims] == ["steps"]


def test_with_nothing_supported_the_overview_speaks_for_itself(two_changes):
    from app.agent.findings import cite_findings

    records = overview(two_changes)
    result = AgentResult(run_id="x", stop_reason="submitted", summary="Your steps went up a lot.")
    cite_findings(result, list(records.values()))
    assert result.summary.startswith("The clear changes:") and "Steps went down" in result.summary
    assert {c.metric for c in result.claims} >= {"steps", "sleep_minutes"}
    assert all(c.evidence_ids[0] in result.evidence for c in result.claims)


def test_an_overview_s_findings_are_inspectable_after_reopening(setup, two_changes):  # noqa: F811
    """broad-01/t1: findings shown without their evidence. Two findings, each its own record."""
    from app.api.store import analyze, get_data
    from app.ingest.takeout import DailyData

    client, _, agent = setup
    headers = sign_in(setup)
    client.app.dependency_overrides[get_data] = lambda: analyze(
        DailyData(frame=two_changes), datetime.now(UTC)
    )
    words = "Give me the big picture across my tracked measures. Which shifts are supported?"
    agent.llm.request_turns = [
        reader_said(
            {
                "type": "investigate",
                "said": words,
                "focus": "overview",
                "metrics": [],
                "periods": [],
                "earlier_result": None,
                "every_metric": True,
            }
        )
    ]
    agent.llm.turns = [
        submit("Your steps dropped clearly, and your time asleep fell too.", claims=[])
    ] * 3
    reply = client.post("/chat", headers=headers, json={"text": words}).json()[-1]
    assert "steps" in reply["text"].lower() and "time asleep" in reply["text"].lower()
    reopened = client.get("/chat", headers=headers).json()[-1]
    assert reopened["evidenceIds"] == reply["evidenceIds"]
    shown = {}
    for evidence_id in reopened["evidenceIds"]:
        found = client.get(f"/evidence/{evidence_id}", headers=headers)
        assert found.status_code == 200
        shown.setdefault(found.json()["metrics"][0], []).append(found.json())
    for metric in ("steps", "sleep_minutes"):
        (record,) = [r for r in shown[metric] if r["tool"] == "compare_windows"]
        assert record["stats"]["difference"] < 0  # the evidence says what the text says
