"""The independent audit of 689fa7c: a repeated answer says the request it repeats, so a query
edit survives; each placed day of a date edit names what it is; naming no metric keeps the
earlier one; every parameter and older result stays addressable; validated facts bind actions;
memory acts on the current message's own words; options come from the resolved topic; and
replies say what the data and sources actually hold. Each case is a reproduction from the audit,
with its contrasting control; made-up data only."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from test_action_api import setup, sign_in  # noqa: F401 (the fixture)
from test_clauses import SAME, data, dates, earlier, read, redo, said, windows
from test_v5_reliability import log_first, reader_said, walk

from app.agent.agent import SUBMIT, AgentResult
from app.agent.ask import (
    NO_FABRICATION,
    _fill_points,
    coaching_query,
    one_source,
    recalled,
    status_reply,
)
from app.agent.clauses import Said, from_this_message, reading_from
from app.agent.context import ChatState, Turn
from app.agent.llm import ScriptedLLM
from app.agent.requested import execute
from app.agent.requests import Request, ResolvedPart, earlier_results, interpret, kept_fields
from app.agent.verifier import Claim
from app.analysis.evidence import Evidence, Window
from app.api import chat
from app.config import settings

TODAY = date(2026, 11, 19)
SIX = earlier("2026-09-23", "2026-09-28", "still_hr_above_resting", "mean")  # six days


def placed(first=None, last=None, length=None):
    """A from_earlier period with its first day, last day or both placed."""
    day = lambda edge: {"counted_from": edge[0], "days_after": edge[1]}  # noqa: E731
    return {
        "kind": "from_earlier",
        "new_first_day": day(first) if first else None,
        "new_last_day": day(last) if last else None,
        "length": length,
    }


# ---- 1. a redo says the request it repeats: an edit inside it is never lost ----


@pytest.mark.parametrize(
    "span, start, end",
    [
        # "translate the complete block back by two dates; keep its size" (metric_*-01/t2)
        (placed(first=("its_first_day", -2), length=6), "2026-09-21", "2026-09-26"),
        # "finish a five-day block the day before that opening date"
        (placed(last=("its_first_day", -1), length=5), "2026-09-18", "2026-09-22"),
        # "begin one day after the old first day, include four dates"
        (placed(first=("its_first_day", 1), length=4), "2026-09-24", "2026-09-27"),
        # "make the opening date the closing date of a three-day block"
        (placed(last=("its_first_day", 0), length=3), "2026-09-21", "2026-09-23"),
    ],
)
def test_a_redo_with_new_days_is_the_earlier_request_on_those_days(span, start, end):
    words = "Same calculation, new days."
    request, calls = read(words, said(redo(words, span)), history=[SIX])
    assert request.kind == "data" and calls == 1
    assert windows(request) == [(date.fromisoformat(start), date.fromisoformat(end))]
    (part,) = request.parts
    assert part.metrics == ["still_hr_above_resting"] and part.operation == "mean"


def test_a_redo_with_another_statistic_keeps_the_days():
    """french_sleep-02/t2: "garde ces dates et donne plutôt la médiane" repeated the mean."""
    words = "Garde ces dates et donne plutôt la médiane."
    request, _ = read(words, said(redo(words, operation="median")), history=[SIX])
    assert request.parts[0].operation == "median"
    assert windows(request) == [(date(2026, 9, 23), date(2026, 9, 28))]


def test_an_unchanged_redo_is_the_same_request():
    words = "Say that again, shorter."
    request, _ = read(words, said(redo(words)), history=[SIX])
    assert request.kind == "data" and request.parts[0].operation == "mean"
    assert windows(request) == [(date(2026, 9, 23), date(2026, 9, 28))]


def test_a_redo_naming_new_dates_and_a_measure_after_guidance_reads_that_data():
    """long_context-01/t7: "return to the steps result for October 3-9" got plank guidance."""
    state = {**SIX.request_state, "guidance": ["plank"], "last": "guidance"}
    after = Turn("How do I do a plank?", "Hold a straight line.", request_state=state)
    words = "Return to the steps result for October 3-9 and repeat the average."
    clause = redo(words, dates("2026-10-03", "2026-10-09"), operation="mean", metrics=["steps"])
    request, _ = read(words, said(clause), history=[after])
    assert request.kind == "data" and request.parts[0].metrics == ["steps"]
    assert windows(request) == [(date(2026, 10, 3), date(2026, 10, 9))]


def test_an_unchanged_redo_after_guidance_is_still_that_guidance():
    state = {**SIX.request_state, "guidance": ["plank"], "last": "guidance"}
    after = Turn("How do I do a plank?", "Hold a straight line.", request_state=state)
    words = "Again, in fewer words."
    request, _ = read(words, said(redo(words)), history=[after])
    assert request.kind == "guidance" and request.topics == ["plank"]


def test_a_redo_after_a_status_and_a_figure_repeats_both():
    """mixed_log-01/t3: "say both again in a shorter answer" dropped the status."""
    state = {**SIX.request_state, "last": "status"}
    words = "Say both again in a shorter answer."
    request, _ = read(
        words, said(redo(words)), history=[Turn("Saved? And HR?", "x", request_state=state)]
    )
    assert request.kind == "status" and request.status and request.reads


THRESHOLD = Turn(
    "Days at or above 5,000 steps, Oct 1-7?",
    "3 days",
    request_state={
        "data": [
            {
                "metrics": ["steps"],
                "operation": "count",
                "windows": [{"start": "2026-10-01", "end": "2026-10-07"}],
                "comparison": ">=",
                "threshold": 5000,
            }
        ]
    },
)


def test_a_new_boundary_keeps_the_comparison():
    """threshold_4-01/t2: "keep the dates and comparison; change the boundary" became >."""
    words = "Keep the dates and comparison; change the boundary to 5600."
    request, _ = read(words, said(redo(words, threshold=5600)), history=[THRESHOLD])
    (part,) = request.parts
    assert (part.comparison, part.threshold, part.operation) == (">=", 5600, "count")


def test_the_reader_sees_every_parameter_an_edit_may_keep():
    shown = earlier_results(THRESHOLD.request_state)[0]
    assert shown["comparison"] == ">=" and shown["threshold"] == 5000


# ---- the placed days of a date edit: each is the day it names ----


@pytest.mark.parametrize(
    "span, start, end",
    [
        # "the five dates immediately before that range", both ways of placing it
        (placed(last=("its_first_day", -1), length=5), "2026-09-18", "2026-09-22"),
        (placed(first=("its_first_day", -5), length=5), "2026-09-18", "2026-09-22"),
        # "only its final two dates"
        (placed(last=("its_last_day", 0), length=2), "2026-09-27", "2026-09-28"),
        # "without its first and last day": both placed, no length
        (placed(first=("its_first_day", 1), last=("its_last_day", -1)), "2026-09-24", "2026-09-27"),
    ],
)
def test_a_placed_day_is_the_day_it_names(span, start, end):
    words = "Same measure, new days."
    clause = data(words, ["still_hr_above_resting"], "mean", span, earlier_result=0)
    request, _ = read(words, said(clause), history=[SIX])
    assert windows(request) == [(date.fromisoformat(start), date.fromisoformat(end))]


@pytest.mark.parametrize(
    "span",
    [
        placed(first=("its_first_day", 1), last=("its_last_day", -1), length=6),  # 4 days, not 6
        placed(first=("its_last_day", 0), last=("its_first_day", 0)),  # ends before it starts
        placed(first=("its_first_day", 1)),  # one day placed, no length
        placed(length=3),  # nothing placed
    ],
)
def test_placed_days_that_do_not_make_a_period_go_back(span):
    words = "Same measure, new days."
    wrong = data(words, ["still_hr_above_resting"], "mean", span, earlier_result=0)
    right = data(words, ["still_hr_above_resting"], "mean", SAME, earlier_result=0)
    request, calls = read(words, said(wrong), said(right), history=[SIX])
    assert calls == 2 and windows(request) == [(date(2026, 9, 23), date(2026, 9, 28))]


def test_a_recorded_single_offset_reading_still_parses_as_the_day_it_named():
    """Replays of earlier audits hold the old form: its offset was its boundary's day."""
    old = {
        "kind": "from_earlier",
        "landmark": "its_first_day",
        "offset": -1,
        "boundary": "ends_there",
        "length": 5,
    }
    words = "x"
    clause = data(words, ["still_hr_above_resting"], "mean", old, earlier_result=0)
    request, _ = read(words, said(clause), history=[SIX])
    assert windows(request) == [(date(2026, 9, 18), date(2026, 9, 22))]


# ---- naming no metric keeps the earlier one; every measure is said ----

RESTING = earlier("2026-11-09", "2026-11-15", "resting_hr", "mean")


@pytest.mark.parametrize("operation", ["inherit", "mean"])
def test_a_date_edit_naming_no_metric_keeps_the_earlier_metric(operation):
    """date_lastweek-02/t2: "use last week, Monday through Sunday" became a look at everything."""
    words = "Use last week, Monday through Sunday."
    week = {"kind": "calendar", "unit": "week", "offset": -1}
    request, _ = read(words, said(data(words, [], operation, week)), history=[RESTING])
    assert request.kind == "data" and request.parts[0].metrics == ["resting_hr"]
    assert request.parts[0].operation == "mean" and not request.parts[0].every_metric
    assert windows(request) == [(date(2026, 11, 9), date(2026, 11, 15))]


def test_a_cold_dated_read_naming_no_metric_is_still_every_measure():
    words = "Contrast Oct 2-15 with Sep 1-14."
    clause = data(words, [], "compare", dates("2026-10-02", "2026-10-15"), dates("2026-09-01"))
    clause["periods"][1]["end"] = "2026-09-14"
    request, _ = read(words, said(clause))
    assert request.kind == "investigate" and request.parts[0].metrics == []


def test_every_measure_said_after_an_earlier_result_is_every_measure():
    words = "Now everything you track over Oct 2-15 against Sep 1-14."
    clause = data(
        words, [], "compare", dates("2026-10-02", "2026-10-15"), dates("2026-09-01", "2026-09-14")
    )
    request, _ = read(words, said(clause | {"every_metric": True}), history=[RESTING])
    assert request.kind == "investigate" and request.parts[0].metrics == []


# ---- 2. every parameter and older result stays addressable ----

LAGGED = Turn(
    "Steps against next-day HRV, Sep 22-Nov 20?",
    "No clear link.",
    request_state={
        "data": [
            {
                "metrics": ["steps", "hrv_ms"],
                "operation": "correlate",
                "windows": [{"start": "2026-09-22", "end": "2026-11-20"}],
                "max_lag": 1,
            }
        ]
    },
)


def cause(max_lag):
    words = "Can that result prove walking caused a change in HRV?"
    clause = data(words, ["steps", "hrv_ms"], "correlate", SAME, earlier_result=0, asks_cause=True)
    return words, clause | {"max_lag": max_lag}


def test_a_cause_question_on_a_lagged_result_keeps_its_lag():
    """assoc_lag-02/t2: the one-day lag was dropped and a same-day test reported."""
    words, clause = cause(None)
    request, _ = read(words, said(clause), history=[LAGGED])
    assert request.parts[0].max_lag == 1


def test_a_lag_said_is_the_lag_used():
    words, clause = cause(0)
    request, _ = read(words, said(clause), history=[LAGGED])
    assert request.parts[0].max_lag == 0


def test_an_older_result_stays_addressable_after_a_new_one():
    steps = earlier("2026-10-03", "2026-10-09", "steps", "mean")
    words = "And resting heart rate for Nov 9-15?"
    clause = data(words, ["resting_hr"], "mean", dates("2026-11-09", "2026-11-15"))
    _, state, _ = interpret(
        ScriptedLLM(request_turns=[ScriptedLLM.call("read_request", **said(clause))]),
        words,
        [steps],
        TODAY,
        read_back=False,
    )
    shown = earlier_results(state)
    assert [(r["metrics"], r["answer"]) for r in shown] == [
        (["resting_hr"], "last"),
        (["steps"], "older"),
    ]
    back = "Back to the steps result: the median."
    request, _ = read(
        back,
        said(redo(back, operation="median", earlier_result=1)),
        history=[Turn("x", "y", request_state=state)],
    )
    assert request.parts[0].metrics == ["steps"] and request.parts[0].operation == "median"
    assert windows(request) == [(date(2026, 10, 3), date(2026, 10, 9))]


# ---- unplaced readings go back once; requests to invent or to mix are said so ----


def other(words, message):
    return {"type": "other", "said": words, "about_them": False, "message": message}


def test_a_follow_up_the_reader_could_not_place_goes_back_once():
    """date_earlierclock-02/t2: "use the preceding calendar day" read as other, then asked."""
    words = "Use the preceding calendar day."
    right = redo(words, placed(last=("its_first_day", -1), length=1))
    request, calls = read(words, said(other(words, "unsure")), said(right), history=[RESTING])
    assert calls == 2 and windows(request) == [(date(2026, 11, 8), date(2026, 11, 8))]


def test_small_talk_after_an_answer_is_not_sent_back():
    words = "Thanks, that helps."
    request, calls = read(words, said(other(words, "small_talk")), history=[RESTING])
    assert calls == 1 and request.kind == "other"


def test_a_reading_with_no_clauses_goes_back_once():
    """memory_new-01/t2: "what walking preference did I approve?" came back with no clause."""
    words = "What walking preference did I approve?"
    right = {"type": "memory", "said": words, "action": "recall", "recall": "kept"}
    request, calls = read(words, said(), said(right))
    assert calls == 2 and (request.kind, request.recall) == ("memory", "kept")


def test_a_request_to_invent_evidence_is_answered_so():
    words = "Pretend my steps on October 14 were 99999 and invent an evidence ID for it."
    reading = Said.model_validate(said(store_nothing=True) | {"fabricate": True})
    assert reading_from(reading, words).fabricate
    assert "can't make up" in NO_FABRICATION


@pytest.mark.parametrize("source", ["api", "takeout"])
def test_a_request_to_join_two_sources_says_which_one_this_history_is(source):
    said_back = one_source(source)
    assert "don't join" in said_back and ("sync" if source == "api" else "export") in said_back


# ---- a clause copied from an earlier message is not asked now ----

LUNCH_WALK = "Remove the preference about walking after lunch."
STILL_THERE = "Is the after-lunch walking preference still in my profile?"


def test_a_clause_copied_from_the_previous_message_is_dropped_when_the_rest_covers_this_one():
    """memory_cancel-02/t2: the copied forget beside the status made a forget card."""
    clauses = Said.model_validate(
        said(
            {"type": "memory", "said": LUNCH_WALK, "action": "forget"},
            {"type": "status", "said": STILL_THERE, "about": "memory"},
        )
    )
    reading = reading_from(clauses, STILL_THERE, before=[LUNCH_WALK])
    assert (reading.kind, reading.memory_action, reading.recall) == ("memory", "recall", "kept")


def test_words_shared_with_this_message_alone_are_its_own():
    clause = Said.model_validate(said({"type": "status", "said": STILL_THERE, "about": "memory"}))
    assert from_this_message(clause.clauses[0], STILL_THERE, [LUNCH_WALK])


def test_medical_words_from_an_earlier_message_make_nothing_medical_now():
    """boundary_urgent-02/t2: "return to my own daily step count" was refused as medical."""
    pain = "I am having crushing chest pain and cannot breathe properly right now."
    words = "Return to my own daily step count for 14 October."
    clause = data(words, ["steps"], "value", dates("2026-10-14"))
    carried = said(clause) | {"medical": True, "medical_said": "crushing chest pain"}
    assert not reading_from(Said.model_validate(carried), words, before=[pain]).medical
    asked = "Do I have a heart condition, given my resting heart rate?"
    own = said() | {"medical": True, "medical_said": "Do I have a heart condition"}
    assert reading_from(Said.model_validate(own), asked, before=[pain]).medical


# ---- 3. validated facts bind the action ----


def test_a_paused_cards_active_time_edit_keeps_the_pause_on_the_new_card(setup):  # noqa: F811
    """workout_paused-01/t3 and -02/t3: refused, then redrafted with the pause dropped."""
    client, _, agent = setup
    headers = sign_in(setup)
    start = (datetime.now(UTC) - timedelta(hours=3)).replace(microsecond=0)
    first = log_first(
        client,
        headers,
        agent,
        walk(start, 50, active=38),
        "Log my walk: 38 minutes active, 12 minutes paused, 50 minutes in all.",
    )
    words = "Active walking was 33 minutes, with the same twelve stopped. Keep the start."
    agent.llm.request_turns = [
        reader_said(
            {
                "type": "correct",
                "said": words,
                "duration_minutes": 33,
                "duration_is": "active",
                "paused_minutes": 12,
            }
        )
    ]
    agent.llm.turns = [ScriptedLLM.call(SUBMIT, summary="Done.", claims=[])]
    second = client.post(
        "/chat", headers=headers, json={"text": words, "conversationId": first["conversationId"]}
    ).json()[-1]
    entries = {e["id"]: e for e in client.get("/actions", headers=headers).json()}
    new, old = entries[second["actionIds"][0]], entries[first["actionIds"][0]]
    assert old["status"] == "cancelled" and new["status"] == "draft"
    begins = datetime.fromisoformat(new["log"]["startTime"])
    assert begins == start and new["log"]["activeSeconds"] == 33 * 60
    assert datetime.fromisoformat(new["log"]["endTime"]) - begins == timedelta(minutes=45)


def test_an_unplaced_duration_with_a_new_day_changes_nothing_until_answered(setup):  # noqa: F811
    """Half an edit is a card nobody asked for: the day is not moved alone."""
    client, _, agent = setup
    headers = sign_in(setup)
    start = (datetime.now(UTC) - timedelta(hours=3)).replace(microsecond=0)
    first = log_first(
        client,
        headers,
        agent,
        walk(start, 50, active=38),
        "Log my walk: 38 minutes active, 12 minutes paused, 50 minutes in all.",
    )
    words = "Make it 30 minutes, and a day earlier."
    agent.llm.request_turns = [
        reader_said(
            {"type": "correct", "said": words, "duration_minutes": 30, "days_from_card": -1}
        )
    ]
    agent.llm.turns = [ScriptedLLM.call(SUBMIT, summary="Done.", claims=[])]
    second = client.post(
        "/chat", headers=headers, json={"text": words, "conversationId": first["conversationId"]}
    ).json()[-1]
    assert not second.get("actionIds") and "12-minute pause" in second["text"]
    (entry,) = client.get("/actions", headers=headers).json()
    assert entry["status"] == "draft" and entry["log"]["startTime"] == first_start(
        first, client, headers
    )


def first_start(first, client, headers):
    entries = {e["id"]: e for e in client.get("/actions", headers=headers).json()}
    return entries[first["actionIds"][0]]["log"]["startTime"]


def test_a_food_draft_on_a_day_the_reader_read_is_not_refused_by_the_day_pattern(setup):  # noqa: F811
    """food_draft-01/t1: "Oct31" passed the reader and failed the second day recognizer."""
    client, _, agent = setup
    headers = sign_in(setup)
    zone = ZoneInfo(settings.timezone)
    day = (datetime.now(zone) - timedelta(days=21)).date()
    words = f"Draft a {day:%b}{day.day} snack at17:10, synthetic crackers, 118kcal and 3g protein."
    agent.llm.request_turns = [
        reader_said({"type": "log", "said": words, "entry": "food", "on_date": day.isoformat()})
    ]
    eaten = datetime.combine(day, datetime.min.time(), zone).replace(hour=17, minute=10)
    payload = {
        "kind": "food",
        "foodName": "synthetic crackers",
        "mealType": "SNACK",
        "consumedAt": eaten.isoformat(),
        "energyKcal": 118,
        "proteinG": 3,
    }
    agent.llm.turns = [
        ScriptedLLM.call("propose_food_log", **payload),
        ScriptedLLM.call(SUBMIT, summary="Draft ready.", claims=[]),
    ]
    reply = client.post("/chat", headers=headers, json={"text": words}).json()[-1]
    assert reply.get("actionIds")
    (entry,) = client.get("/actions", headers=headers).json()
    assert datetime.fromisoformat(entry["log"]["consumedAt"]).astimezone(zone).date() == day


def test_a_named_run_is_carded_as_a_run_not_a_generic_workout(setup):  # noqa: F811
    """workout_nocard-01/t3: "prepare a run" became WORKOUT."""
    client, _, agent = setup
    headers = sign_in(setup)
    start = (datetime.now(UTC) - timedelta(hours=5)).replace(microsecond=0)
    words = "Then prepare a run for this morning, lasting 25 minutes."
    agent.llm.request_turns = [
        reader_said(
            {
                "type": "log",
                "said": words,
                "entry": "workout",
                "exercise_type": "RUNNING",
                "duration_minutes": 25,
            }
        )
    ]
    agent.llm.turns = [
        ScriptedLLM.call("propose_workout_log", **(walk(start, 25) | {"exerciseType": "WORKOUT"})),
        ScriptedLLM.call(SUBMIT, summary="Draft ready.", claims=[]),
    ]
    client.post("/chat", headers=headers, json={"text": words})
    (entry,) = client.get("/actions", headers=headers).json()
    assert entry["log"]["exerciseType"] == "RUNNING"


def test_a_type_the_tracker_does_not_have_is_left_to_the_draft():
    words = "Prepare a frisbee golf round, 30 minutes."
    clause = {"type": "log", "said": words, "entry": "workout", "exercise_type": "DISC_GOLF"}
    assert reading_from(Said.model_validate(said(clause)), words).exercise_type is None


def test_a_status_question_reads_the_waiting_cards_values():
    """workout_paused-01/t4: "exactly what is still waiting" got only "a card is waiting"."""
    start = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)
    card = chat.card_described(walk(start, 50, active=38), ZoneInfo("UTC"))
    said_back = status_reply(["draft"], card)
    assert "38 min active" in said_back and "12 min paused" in said_back
    assert "50 min from start to end" in said_back and "15:00" in said_back
    assert status_reply(["succeeded"], card).startswith("Yes")


# ---- 4. memory acts on the current message's own words ----


def test_forgetting_a_fact_the_conversation_is_about_shows_the_picker_that_conversation():
    """memory_replace-01/t3: "forget that updated preference" asked which, of one fact."""
    from app.agent.listener import which_kept

    llm = ScriptedLLM([ScriptedLLM.call("pick_kept", item=1)])
    before = ["Update it: I now prefer walking after dinner.", "Kept: walking after dinner."]
    index, _ = which_kept(llm, "Forget that updated preference.", ["walking after dinner"], before)
    sent = llm.requests[-1]["messages"][1]["content"]
    assert index == 0 and "walking after dinner." in sent and "conversation just before" in sent


def test_the_memory_clauses_own_words_are_the_fact_to_keep():
    """mixed_memory-02/t1: the sleep question beside it was proposed as a fact too."""
    words = "Average time asleep October 3 through 9, and please save my preference for walks."
    clause = data("Average time asleep October 3 through 9", ["sleep_minutes"], "mean")
    keep = {"type": "memory", "said": "please save my preference for walks", "action": "remember"}
    reading = reading_from(Said.model_validate(said(clause, keep)), words)
    assert reading.memory_said == "please save my preference for walks"


def test_nothing_kept_now_is_not_said_as_nothing_ever_approved():
    said_back = recalled([], ChatState(), [], "kept")
    assert "right now" in said_back and "approved" not in said_back


# ---- 5. options come from the resolved topic, and a shortfall is said ----


def habit(metric):
    window = Window(start=date(2026, 10, 11), end=date(2026, 10, 24))
    return Evidence(
        tool="habit_options",
        metrics=(metric,),
        windows=(window,),
        n=14,
        sufficient=True,
        stats={"levers": []},
    )


def test_options_on_a_look_are_searched_for_its_measures_not_its_words():
    """investigate_*-0x/t4: the elliptical request was searched for itself and found nothing."""
    looked = Request(
        kind="investigate", focus="coaching", parts=[ResolvedPart(metrics=[], operation="describe")]
    )
    query = coaching_query(looked, [habit("sleep_efficiency"), habit("recovery_score")])
    assert query and "sleep efficiency" in query and "label" not in query
    named = Request(
        kind="investigate",
        focus="coaching",
        parts=[ResolvedPart(metrics=["steps"], operation="describe")],
    )
    assert "steps" in coaching_query(named, [habit("sleep_efficiency")])
    assert coaching_query(Request(kind="data"), []) is None


def passage(number, text):
    stats = {"passage_id": f"p{number}", "text": text, "source": "CDC", "title": f"Tip {number}"}
    return Evidence(tool="knowledge", metrics=(), windows=(), n=0, sufficient=True, stats=stats)


def test_general_points_are_labelled_and_a_shortfall_is_said(monkeypatch):
    found = [passage(1, "Keep a regular wake time, even at weekends, to anchor your sleep.")]
    monkeypatch.setattr("app.agent.ask.more_passages", lambda query, llm, count: (found, 0.0))
    result = AgentResult(run_id="r", stop_reason="submitted", summary="Steps went up.")
    _fill_points(None, result, "Everyday habits that support better sleep", 3, None)
    assert "- General (CDC): Keep a regular wake time" in result.summary
    assert any("asked for 3" in n and "support 1" in n for n in result.notes)


# ---- 6. what a reply says is what the data and sources hold ----

FOOD_DAY = date(2026, 10, 31)


def meal(**values):
    eaten = datetime.combine(FOOD_DAY, datetime.min.time(), UTC).replace(hour=17)
    return {"kind": "food", "foodName": "crackers", "consumedAt": eaten.isoformat(), **values}


def food_read(nutrients):
    part = ResolvedPart(
        metrics=["food_logs"],
        operation="food",
        windows=[Window(start=FOOD_DAY, end=FOOD_DAY)],
        nutrients=nutrients,
    )
    return execute(
        Request(kind="data", parts=[part]),
        pd.DataFrame(),
        TODAY,
        food_logs=[meal(energyKcal=118, carbohydrateG=20)],
        zone=UTC,
    )


def test_an_unrecorded_nutrient_asked_about_is_said_unknown_not_repeated_away():
    """food_unknown-0x/t2: protein, not recorded, got energy, carbs and fat instead."""
    said_back = food_read(["protein"]).summary
    assert "Protein: not recorded, so it is unknown, not zero" in said_back
    assert "Energy" not in said_back and "Carbohydrate" not in said_back


def test_with_no_nutrient_named_every_recorded_one_is_said():
    said_back = food_read([]).summary
    assert "Energy consumed: 118 kcal" in said_back and "Carbohydrate: 20 g" in said_back
    assert "Protein" not in said_back


def test_a_food_clause_naming_its_nutrient_as_a_metric_carries_it():
    words = "And protein for that same entry?"
    clause = data(words, ["protein"], "inherit", SAME, earlier_result=0, source="food_log")
    reading = reading_from(Said.model_validate(said(clause)), words, earlier=True)
    assert reading.parts[0].nutrients == ["protein"]


def test_a_retry_keeps_the_fields_its_error_was_not_about():
    """food_draft-02/t2: the retry added a snack filter that no one asked for."""
    first = said(data("x", [], "food", source="food_log", meal_type=None))
    second = said(data("x", [], "food", dates("2026-10-31"), source="food_log", meal_type="SNACK"))
    kept = kept_fields(second, first, ("source", "operation", "meal_type"))
    clause = kept["clauses"][0]
    assert clause["meal_type"] is None and clause["periods"] == [dates("2026-10-31")]


def test_a_food_read_with_no_days_goes_back_and_keeps_every_meal():
    words = "Before confirming it, read that date's confirmed food calories."
    llm = ScriptedLLM(
        request_turns=[
            ScriptedLLM.call(
                "read_request", **said(data(words, [], "food", source="food_log", meal_type=None))
            ),
            ScriptedLLM.call(
                "read_request",
                **said(
                    data(
                        words,
                        ["calories"],
                        "value",
                        dates("2026-10-31"),
                        source="food_log",
                        meal_type="SNACK",
                    )
                ),
            ),
        ]
    )
    request, _, _ = interpret(llm, words, [], TODAY, read_back=False)
    (part,) = request.parts
    assert part.operation == "food" and part.meal_type is None
    assert part.windows == [Window(start=FOOD_DAY, end=FOOD_DAY)]


def test_a_constant_series_is_said_with_evidence_that_shows_it():
    """assoc_constant-0x: the constancy was said with nothing to inspect."""
    days = pd.date_range("2026-09-22", periods=20)
    frame = pd.DataFrame({"steps": [8000.0] * 20, "hrv_ms": [40.0 + i % 5 for i in range(20)]})
    frame.index = days
    part = ResolvedPart(
        metrics=["steps", "hrv_ms"],
        operation="correlate",
        windows=[Window(start=days[0].date(), end=days[-1].date())],
    )
    done = execute(Request(kind="data", parts=[part]), frame, TODAY)
    (claim,) = [c for c in done.claims if c.kind == "data_quality"]
    assert "steps stayed the same on every day" in claim.text
    cited = [done.evidence[i] for i in claim.evidence_ids]
    assert {e.tool for e in cited} == {"describe", "correlate"}
    assert any(e.tool == "describe" and e.stats["sd"] == 0 for e in cited)


def test_a_guidance_topic_keeps_its_base_movement():
    """guide_unknown-02: the topic lost "push-up", and "the standard floor movement" then
    taught a foam-roller stretch."""
    words = "Do vetted ordinary pushup instructions cover a moving-surfboard variation?"
    clause = {
        "type": "guidance",
        "said": words,
        "topics": ["moving-surfboard variation"],
        "movement": "push-up",
        "question": words,
    }
    reading = reading_from(Said.model_validate(said(clause, subject="general")), words)
    assert reading.topics == ["push-up, moving-surfboard variation"]
    plain = clause | {"topics": ["standard floor push-up"]}
    again = reading_from(Said.model_validate(said(plain, subject="general")), words)
    assert again.topics == ["standard floor push-up"]


def test_claims_said_by_code_cite_what_they_say():
    """Every new claim cites a record the result holds."""
    done = food_read(["protein"])
    assert all(i in done.evidence for c in done.claims for i in c.evidence_ids)
    assert all(isinstance(c, Claim) for c in done.claims)
