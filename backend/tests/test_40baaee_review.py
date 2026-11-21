"""Codex's offline review of 40baaee: an explicit zero lag is an edit, an explicit statistic
wins over a look, a duration edit is judged against its own basis, the last answer is replayed
whole, retry fields stay on their own clause, options on days with no data are still answered,
and an explanation says only what its verified claims say. Each case is a reproduction from the
review with its contrasting control; made-up data only."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from test_689_reliability import LAGGED
from test_broad_questions import END, Router, planted, submit
from test_clauses import data, dates, read, redo, said, windows
from test_investigate_and_memory import reading_llm

from app.agent.agent import AgentResult
from app.agent.ask import NO_TESTED_FINDING, ask, said_by_claims
from app.agent.context import Turn
from app.agent.llm import ScriptedLLM
from app.agent.requests import Request, interpret, kept_fields
from app.agent.verifier import Claim
from app.analysis.evidence import Evidence, Window
from app.api import chat

TODAY = date(2026, 11, 19)

# ---- 1. an explicit zero lag is an edit ----


@pytest.mark.parametrize("lag, used", [(None, 1), (0, 0), (2, 2)])
def test_a_redos_lag_is_kept_unless_said_and_zero_is_said(lag, used):
    words = "Same dates and measures, the same-day association."
    request, _ = read(words, said(redo(words, max_lag=lag)), history=[LAGGED])
    assert request.parts[0].max_lag == used and request.parts[0].operation == "correlate"


def test_a_zero_lag_beside_guidance_is_not_read_as_a_data_edit():
    state = {**LAGGED.request_state, "guidance": ["plank"], "last": "guidance"}
    after = Turn("How do I do a plank?", "Hold it.", request_state=state)
    words = "Again, shorter."
    request, _ = read(words, said(redo(words, max_lag=0)), history=[after])
    assert request.kind == "guidance"


def test_same_day_then_lagged_then_same_day_follows_each_step():
    first = "Steps against HRV, Sep 22-Nov 20, same day."
    clause = data(first, ["steps", "hrv_ms"], "correlate", dates("2026-09-22", "2026-11-20"))
    turns, state = [], {}
    for words, step in [
        (first, clause | {"max_lag": 0}),
        ("And with a one-day lag?", redo("And with a one-day lag?", max_lag=1)),
        ("Back to the same day.", redo("Back to the same day.", max_lag=0)),
    ]:
        llm = ScriptedLLM(request_turns=[ScriptedLLM.call("read_request", **said(step))])
        request, state, _ = interpret(llm, words, turns, TODAY, read_back=False)
        turns.append(Turn(words, "x", request_state=state))
        assert request.parts[0].max_lag == step.get("max_lag")


# ---- 2. an explicit statistic wins over a look's description ----

LOOK = Turn(
    "What changed in my steps, Oct 1-14?",
    "They rose.",
    request_state={
        "data": [
            {
                "metrics": ["steps"],
                "operation": "describe",
                "windows": [{"start": "2026-10-01", "end": "2026-10-14"}],
            }
        ],
        "focus": "what_changed",
    },
)


def test_a_median_asked_for_after_a_look_is_the_median():
    """median_after_investigation: forced back to describe, it stayed an investigation."""
    words = "Keep those dates, but give only the median steps."
    request, _ = read(
        words, said(redo(words, operation="median", metrics=["steps"])), history=[LOOK]
    )
    assert request.kind == "data" and request.parts[0].operation == "median"
    assert windows(request) == [(date(2026, 10, 1), date(2026, 10, 14))]


def test_a_statistic_naming_no_measure_after_a_look_takes_the_looks_measure():
    words = "Just the mean for those days."
    request, _ = read(words, said(redo(words, operation="mean")), history=[LOOK])
    assert request.kind == "data" and request.parts[0].metrics == ["steps"]


def test_an_unchanged_redo_of_a_look_is_still_the_look():
    words = "Say that again."
    request, _ = read(words, said(redo(words)), history=[LOOK])
    assert request.kind == "investigate" and request.parts[0].operation == "describe"


def test_a_statistic_after_a_two_period_look_still_asks_which_period():
    two = Turn(
        "x",
        "y",
        request_state={
            "data": [
                {
                    "metrics": ["steps"],
                    "operation": "describe",
                    "windows": [
                        {"start": "2026-10-11", "end": "2026-10-24"},
                        {"start": "2026-08-17", "end": "2026-08-30"},
                    ],
                }
            ]
        },
    )
    words = "The median steps for those dates."
    request, _ = read(
        words, said(redo(words, operation="median", metrics=["steps"])), history=[two]
    )
    assert request.kind == "clarify"


# ---- 3. a duration edit is judged against its own basis ----

START = datetime(2026, 10, 21, 15, 0, tzinfo=ZoneInfo("UTC"))


def card():
    """31 minutes active, 9 paused, 40 in all."""
    return {
        "kind": "workout",
        "exerciseType": "WALKING",
        "startTime": START.isoformat(),
        "endTime": (START + timedelta(minutes=40)).isoformat(),
        "activeSeconds": 31 * 60,
    }


@pytest.mark.parametrize(
    "fields, pair",
    [
        ({"duration_minutes": 40, "duration_is": "active"}, (40, 49)),  # equal to the old elapsed
        ({"duration_minutes": 31, "duration_is": "elapsed"}, (22, 31)),  # equal to the old active
        ({"duration_minutes": 33, "duration_is": "active"}, (33, 42)),
        ({"duration_minutes": 40, "duration_is": "active", "paused_minutes": 5}, (40, 45)),
        ({"duration_minutes": 40}, (None, None)),  # no basis: the card's own elapsed, restated
        ({"duration_minutes": 31, "duration_is": "active"}, (None, None)),  # its own active
    ],
)
def test_a_duration_is_compared_only_with_the_duration_it_is(fields, pair):
    edit = chat.card_edit(card(), Request(kind="correction", **fields), ZoneInfo("UTC"))
    assert (edit.active_minutes, edit.elapsed_minutes) == pair and not edit.unclear


def test_a_date_only_edit_of_a_paused_card_still_keeps_both_durations():
    typed = Request(kind="correction", duration_minutes=40, card_day_offset=1)
    edit = chat.card_edit(card(), typed, ZoneInfo("UTC"))
    assert edit.active_minutes is None and edit.day == date(2026, 10, 22)


# ---- 4. the last answer is replayed whole ----


def turn(words, *clauses, history=(), pending=False):
    llm = ScriptedLLM(request_turns=[ScriptedLLM.call("read_request", **said(*clauses))])
    request, state, _ = interpret(
        llm, words, list(history), TODAY, read_back=False, pending_draft=pending
    )
    return request, Turn(words, "answer", request_state=state)


SLEEP = data("and that sleep average", ["sleep_minutes"], "mean", dates("2026-10-03", "2026-10-09"))
SLEEP_PART = {
    "metrics": ["sleep_minutes"],
    "operation": "mean",
    "windows": [{"start": "2026-10-01", "end": "2026-10-07"}],
}
RECALL = {"type": "memory", "said": "What preference is kept", "action": "recall", "recall": "kept"}


def again(history, words="Repeat both, briefly."):
    request, _ = turn(words, redo(words), history=history)
    return request


def test_a_recall_beside_a_figure_is_both_again():
    """mixed_memory_redo: the preference was dropped and only the sleep mean came back."""
    _, first = turn("What preference is kept and that sleep average?", RECALL, SLEEP)
    request = again([first])
    assert (request.kind, request.memory_action, request.recall) == ("memory", "recall", "kept")
    assert [p.metrics for p in request.reads] == [["sleep_minutes"]]


def test_a_status_alone_is_the_status_again():
    status = {"type": "status", "said": "Is it saved?", "about": "entry"}
    _, first = turn("Is it saved?", status, pending=True)
    request = again([first])
    assert request.kind == "status" and request.status and not request.reads


def test_guidance_with_a_side_read_is_both_again():
    guide = {"type": "guidance", "said": "How do I plank?", "topics": ["plank"], "question": "x"}
    _, first = turn(
        "How do I plank, and my steps on Oct 3?",
        guide,
        data("my steps on Oct 3", ["steps"], "value", dates("2026-10-03")),
    )
    request = again([first])
    assert request.kind == "guidance" and request.topics == ["plank"]
    assert [p.metrics for p in request.reads] == [["steps"]]


def test_a_memory_answer_after_data_replays_the_memory_not_the_older_data():
    _, data_turn = turn("Sleep average?", SLEEP)
    _, recall_turn = turn("What preference is kept?", RECALL, history=[data_turn])
    request = again([data_turn, recall_turn], "Again, please.")
    assert request.kind == "memory" and not request.reads and not request.parts


def test_a_forget_again_is_what_is_kept_now_never_another_forget():
    forget = {"type": "memory", "said": "Forget my walk preference", "action": "forget"}
    _, first = turn("Forget my walk preference.", forget)
    request = again([first], "Say that again.")
    assert (request.memory_action, request.recall) == ("recall", "kept")


def test_one_part_named_of_a_mixed_answer_is_only_that_part():
    _, first = turn("What preference is kept and that sleep average?", RECALL, SLEEP)
    words = "Just the sleep figure again."
    request, _ = turn(words, redo(words, earlier_result=0), history=[first])
    assert request.kind == "data" and [p.metrics for p in request.parts] == [["sleep_minutes"]]


# ---- 5. retry fields stay on their own clause ----

FOOD_WORDS = "what I ate that day"
STEPS_WORDS = "my steps on Oct 31"


def food(*periods, meal=None):
    return data(FOOD_WORDS, [], "food", *periods, source="food_log", meal_type=meal)


def steps():
    return data(STEPS_WORDS, ["steps"], "value", dates("2026-10-31"), source="tracker")


def test_reordered_retry_clauses_keep_their_own_sources():
    """reordered_retry: by position, food's source went onto steps and the steps read was lost."""
    first = said(food(), steps())
    second = said(steps() | {"meal_type": "SNACK"}, food(dates("2026-10-31"), meal="SNACK"))
    kept = kept_fields(second, first, ("source", "operation", "meal_type", "nutrients"))
    by_words = {c["said"]: c for c in kept["clauses"]}
    assert by_words[STEPS_WORDS]["source"] == "tracker"
    assert by_words[STEPS_WORDS]["operation"] == "value"
    assert by_words[FOOD_WORDS]["source"] == "food_log"
    assert by_words[FOOD_WORDS]["meal_type"] is None  # the first reading's: no meal filter
    assert by_words[FOOD_WORDS]["periods"] == [dates("2026-10-31")]


def test_the_whole_reordered_retry_resolves_to_both_reads():
    words = f"{FOOD_WORDS}, and {STEPS_WORDS}"
    llm = ScriptedLLM(
        request_turns=[
            ScriptedLLM.call("read_request", **said(food(), steps())),
            ScriptedLLM.call(
                "read_request", **said(steps(), food(dates("2026-10-31"), meal="SNACK"))
            ),
        ]
    )
    request, _, _ = interpret(llm, words, [], TODAY, read_back=False)
    assert request.kind == "data"
    assert sorted((p.operation, p.meal_type) for p in request.parts) == [
        ("food", None),
        ("value", None),
    ]


def test_clauses_with_the_same_words_get_nothing_moved_between_them():
    first = said(food(), food(dates("2026-10-30")))
    second = said(food(dates("2026-10-31"), meal="SNACK"), food(dates("2026-10-30")))
    kept = kept_fields(second, first, ("meal_type",))
    assert kept["clauses"][0]["meal_type"] == "SNACK"  # no unique match: left as the retry gave


# ---- 6. options asked for on days with no data are still answered ----


def passage(text):
    stats = {"passage_id": "p1", "text": text, "source": "CDC", "title": "Tip"}
    return Evidence(tool="knowledge", metrics=(), windows=(), n=0, sufficient=True, stats=stats)


def coaching_on_missing_days(metrics, monkeypatch):
    found = [passage("Keep a regular wake time, even at weekends, to anchor your sleep.")]
    monkeypatch.setattr("app.agent.ask.more_passages", lambda query, llm, count: (found, 0.0))
    days = {"kind": "explicit", "start": "2025-10-11", "end": "2025-10-24"}  # before the data
    llm = reading_llm(
        submit(),
        kind="investigate",
        focus="coaching",
        parts=[{"metrics": metrics, "periods": [days]}],
        points=3,
    )
    return ask(llm, Router("lookup"), planted(), "Three options for those days?", today=END)


def test_options_on_days_with_no_data_say_the_limit_and_give_labelled_general_points(
    monkeypatch,
):
    """out_of_range_options: only the data limit came back, with no option or shortfall."""
    reply = coaching_on_missing_days(["sleep_minutes"], monkeypatch)
    shown = reply.result.summary
    assert shown.startswith("Your data has no days") and "- General (CDC): Keep a regular" in shown
    notes = " ".join(reply.result.notes)
    assert "none of these is personal" in notes and "asked for 3" in notes
    assert not [c for c in reply.result.claims if c.kind == "suggestion"]


def test_options_on_days_with_no_data_and_no_measure_say_why_there_are_none(monkeypatch):
    reply = coaching_on_missing_days([], monkeypatch)
    assert "haven't given any options" in " ".join(reply.result.notes)
    assert "General" not in reply.result.summary


# ---- 7. an explanation says only what its verified claims say ----


def result_with(summary, *texts, stop="submitted"):
    window = Window(start=date(2026, 10, 11), end=date(2026, 10, 24))
    record = Evidence(
        tool="compare", metrics=("steps",), windows=(window,), n=14, sufficient=True, stats={}
    )
    result = AgentResult(run_id="r", stop_reason=stop, summary=summary)
    result.evidence[record.id] = record
    result.claims = [Claim(text=t, kind="change", evidence_ids=[record.id]) for t in texts]
    return result


def test_an_explanations_unchecked_prose_is_not_what_is_said():
    """old_unsupported_run_down: valid claims, and prose about feeling "more run down"."""
    result = result_with(
        "Your activity jumped and your sleep fell, which could explain feeling more run down.",
        "Steps went up: 12,780 against 7,184.",
        "Time asleep fell: 6 h against 7 h 2 min.",
    )
    said_by_claims(result)
    # Its records are stated by code, never its words (tests/test_462f700_review.py); this
    # stand-in record holds no statistic, so nothing of the model's is said in its place.
    assert "run down" not in result.summary and result.summary == NO_TESTED_FINDING


@pytest.mark.parametrize(
    "result",
    [
        result_with("No claims could be checked."),  # nothing verified: left as it is
        result_with("Fixed reply.", "A claim.", stop="limits"),  # code's own reply
    ],
)
def test_a_reply_with_no_verified_claim_or_from_code_is_left_alone(result):
    before = result.summary
    said_by_claims(result)
    assert result.summary == before


@pytest.mark.parametrize(
    "state, claimed, kind, reads",
    [
        ({"last": "status"}, (), "status", 0),
        # The kept sleep mean is no part of a recall or a guidance answer that named no metric
        # (the review of 462f700: plank guidance came back with an old resting heart rate)...
        ({"last": "memory", "data": [SLEEP_PART]}, (), "memory", 0),
        ({"last": "guidance", "guidance": ["plank"], "data": [SLEEP_PART]}, (), "guidance", 0),
        ({"last": "status", "data": [SLEEP_PART]}, (), "status", 0),
        # ...and is one when the answer's own verified claims name its metric.
        ({"last": "memory", "data": [SLEEP_PART]}, ("sleep_minutes",), "memory", 1),
        (
            {"last": "guidance", "guidance": ["plank"], "data": [SLEEP_PART]},
            ("sleep_minutes",),
            "guidance",
            1,
        ),
    ],
)
def test_a_state_saved_before_whole_answers_were_kept_replays_only_what_it_shows(
    state, claimed, kind, reads
):
    words = "Again, briefly."
    claims = tuple({"text": "x", "metric": m, "evidence_ids": ["e"]} for m in claimed)
    history = [Turn("x", "y", claims=claims, request_state=state)]
    request, _ = read(words, said(redo(words)), history=history)
    assert request.kind == kind and len(request.reads) == reads
