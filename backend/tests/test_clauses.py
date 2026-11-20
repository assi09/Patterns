"""The reader's clauses: each request with only its own fields and words (the v4 audit and the
reader replay of 2026-11-19). The expected meaning of each case comes from the audit's frozen
questions and answer key, never from what a reader returned. Made-up data only.
"""

from datetime import date

import pytest
from test_broad_questions import END, Router, planted

from app.agent.ask import STATUS_NONE, STATUS_SAVED, STATUS_WAITING, ask, recalled
from app.agent.clauses import Said, reading_from
from app.agent.context import ChatState, Turn
from app.agent.llm import ScriptedLLM
from app.agent.present import METRICS
from app.agent.requests import RetryReading, interpret, said_schema, strict_schema

TODAY = date(2026, 11, 19)


def said(*clauses, store_nothing=False, subject="self"):
    return {
        "subject": subject,
        "clauses": list(clauses),
        "store_nothing": store_nothing,
        "clarification": "",
    }


def reader(*readings):
    """The reader's scripted readings, read back by a scripted check that accepts only the last
    one: a scenario's earlier readings are the wrong ones (the read-back's judgment itself is
    measured live, not offline)."""
    llm = ScriptedLLM(request_turns=[ScriptedLLM.call("read_request", **r) for r in readings])
    return with_last_accepted(llm, len(readings))


def with_last_accepted(llm, readings):
    def judge(messages):
        made = sum(r["tools"] == ["read_request"] for r in llm.requests)
        return ScriptedLLM.call(
            "verdict",
            matches=made >= readings,
            problem="" if made >= readings else "The reading does not match the message.",
            question="",
        )

    llm.check_turns = [judge] * (2 * readings) if readings > 1 else None
    return llm


def read(question, *readings, history=(), today=TODAY, pending=False):
    llm = reader(*readings)
    request, state, budget = interpret(
        llm, question, list(history), today, pending_draft=pending, read_back=True
    )
    return request, sum(r["tools"] == ["read_request"] for r in llm.requests)


def data(words, metrics, operation, *periods, **extra):
    return {
        "type": "data",
        "said": words,
        "metrics": list(metrics),
        "operation": operation,
        "periods": list(periods),
        **extra,
    }


def dates(start, end=None):
    return {"kind": "dates", "start": start, "end": end or start}


def earlier(start, end, metric="steps", operation="value"):
    window = {"start": start, "end": end}
    part = {"metrics": [metric], "operation": operation, "windows": [window]}
    return Turn("earlier question", "earlier answer", request_state={"data": [part]})


def windows(request, which="parts"):
    return [(w.start, w.end) for p in getattr(request, which) for w in p.windows]


# ---- the schema the reader is given ----


def test_the_reader_schema_is_strict_and_has_only_union_shapes_decoding_takes():
    schema = str(strict_schema(said_schema()))
    assert "oneOf" not in schema and "discriminator" not in schema and "const" not in schema


# ---- logging is never a data question ----

WALK = "Draft my 26-minute walk for November 16, 2026, starting at 15:10."
LOG_WALK = {
    "type": "log",
    "said": WALK,
    "entry": "workout",
    "duration_minutes": 26,
    "on_date": "2026-11-16",
}


def test_a_workout_draft_is_a_log_with_its_own_day_and_no_data_question():
    """Every cold workout draft asked "which earlier measurement?" (the v4 audit)."""
    request, calls = read(WALK, said(LOG_WALK))
    assert (request.kind, request.duration_minutes, request.log_day) == (
        "logging",
        26,
        date(2026, 11, 16),
    )
    assert not request.parts and not request.reads and calls == 1


def test_a_placeholder_data_clause_beside_a_log_is_sent_back():
    placeholder = data(WALK, [], "value")
    request, calls = read(WALK, said(LOG_WALK, placeholder), said(LOG_WALK))
    assert request.kind == "logging" and calls == 2
    with pytest.raises(RetryReading):
        reading_from(Said.model_validate(said(LOG_WALK, placeholder)))


# ---- status is read from the store, and a read beside it is answered too ----

STATUS = "Have you actually written it to my tracker yet?"


@pytest.mark.parametrize(
    "states, reply",
    [(["draft"], STATUS_WAITING), (["succeeded"], STATUS_SAVED), ([], STATUS_NONE)],
)
def test_a_status_question_is_answered_from_the_entries_state(states, reply):
    llm = reader(said({"type": "status", "said": STATUS}))
    answer = ask(llm, Router("chat"), planted(), STATUS, today=END, action_states=states)
    assert answer.result.summary == reply


def test_the_count_and_the_status_are_both_answered():
    frame = planted()
    day = frame.index[-1].date().isoformat()
    question = "Before I tap anything, repeat the step count for that date and say whether the "
    question += "workout has been saved."
    count = data("repeat the step count for that date", ["steps"], "value")
    count["periods"] = [{"kind": "same_as_earlier"}]
    count["earlier_result"] = 0
    llm = reader(said(count, {"type": "status", "said": "say whether the workout has been saved"}))
    answer = ask(
        llm,
        Router("chat"),
        frame,
        question,
        today=END,
        history=[earlier(day, day)],
        after_draft=True,
        action_states=["draft"],
    )
    assert answer.result.summary == STATUS_WAITING
    assert any(f"{frame['steps'].iloc[-1]:,.0f}" in note for note in answer.result.notes)


# ---- periods mean what was said ----


def test_the_5_complete_days_before_today_end_yesterday():
    question = "Mean sleep duration over the 5 complete days before today?"
    right = {"kind": "days_ending", "length": 5, "ending": "today", "offset": -1}
    request, calls = read(question, said(data(question, ["sleep_minutes"], "mean", right)))
    assert windows(request) == [(date(2026, 11, 14), date(2026, 11, 18))] and calls == 1


def test_a_reading_that_misplaces_the_5_days_is_sent_back():
    """The replay's reading: five days ending six days ago."""
    question = "Mean sleep duration over the 5 complete days before today?"
    wrong = {"kind": "days_ending", "length": 5, "ending": "today", "offset": -6}
    right = {"kind": "days_ending", "length": 5, "ending": "today", "offset": -1}
    request, calls = read(
        question,
        said(data(question, ["sleep_minutes"], "mean", wrong)),
        said(data(question, ["sleep_minutes"], "mean", right)),
    )
    assert windows(request) == [(date(2026, 11, 14), date(2026, 11, 18))] and calls == 2
    assert request.attempts[0]["codes"] == ["read_back"]


@pytest.mark.parametrize(
    "day, today, start",
    [
        ("2028-02-29", date(2028, 3, 4), date(2028, 2, 26)),
        ("2027-01-01", date(2027, 1, 8), date(2026, 12, 29)),
    ],
)
def test_that_date_and_the_three_before_it_are_four_days(day, today, start):
    question = "Use the mean over that date and the three dates immediately before it."
    four = {
        "kind": "beside_earlier",
        "counted_from": "its_last_day",
        "offset": 0,
        "new_period": "ends_there",
        "length": 4,
    }
    clause = data(question, ["steps"], "mean", four, earlier_result=0)
    request, calls = read(question, said(clause), history=[earlier(day, day)], today=today)
    assert windows(request) == [(start, date.fromisoformat(day))] and calls == 1


# ---- dates belong to the clause that names them ----

TWO = "Average sleep on Oct 6–12, 2026, and average steps on Oct 20–26, 2026?"
SLEEP_WORDS, STEPS_WORDS = "Average sleep on Oct 6–12, 2026", "average steps on Oct 20–26, 2026"


def two_parts(sleep_days, steps_days):
    return said(
        data(SLEEP_WORDS, ["sleep_minutes"], "mean", dates(*sleep_days)),
        data(STEPS_WORDS, ["steps"], "mean", dates(*steps_days)),
    )


OCT_6, OCT_20 = ("2026-10-06", "2026-10-12"), ("2026-10-20", "2026-10-26")


def test_each_metric_keeps_its_own_dates():
    request, calls = read(TWO, two_parts(OCT_6, OCT_20))
    assert windows(request) == [
        (date(2026, 10, 6), date(2026, 10, 12)),
        (date(2026, 10, 20), date(2026, 10, 26)),
    ]
    assert calls == 1


def test_dates_swapped_between_two_metrics_are_sent_back():
    """Every date appeared somewhere in the request, so the old check passed it (Codex)."""
    request, calls = read(TWO, two_parts(OCT_20, OCT_6), two_parts(OCT_6, OCT_20))
    assert calls == 2 and request.attempts[0]["codes"] == ["read_back"]
    assert windows(request)[0] == (date(2026, 10, 6), date(2026, 10, 12))


# ---- comparisons, negated ----


@pytest.mark.parametrize(
    "words, sign",
    [
        ("no higher than", "<="),
        ("not above", "<="),
        ("no lower than", ">="),
        ("greater than", ">"),
        ("equal to", "=="),
    ],
)
def test_a_correct_comparison_passes_however_it_is_worded(words, sign):
    question = f"In Nov 11–19, 2026, how many days had steps {words} 7100?"
    clause = data(
        question,
        ["steps"],
        "count",
        dates("2026-11-11", "2026-11-19"),
        comparison=sign,
        threshold=7100,
    )
    request, calls = read(question, said(clause))
    assert request.parts[0].comparison == sign and calls == 1


# ---- only what this message asks ----


def test_the_first_result_only_is_one_clause():
    question = "For the first result only, use the median instead; keep its dates."
    clause = data(question, ["steps"], "median", {"kind": "same_as_earlier"}, earlier_result=0)
    request, _ = read(question, said(clause), history=[earlier("2026-11-01", "2026-11-06")])
    assert len(request.parts) == 1 and request.parts[0].operation == "median"


# ---- memory: the action, the consent and the scope of recall ----


def test_forget_with_do_not_save_is_still_a_forget():
    """ "Remove my fun-run goal" came out as forget and don't-save, and was answered "Okay, I
    won't keep that" while the goal stayed (the v4 audit)."""
    words = "Remove my fun-run goal from what you remember, please."
    forget = {"type": "memory", "said": words, "action": "forget"}
    llm = reader(said(forget, store_nothing=True))
    reply = ask(llm, Router("chat"), planted(), words, today=END)
    assert reply.result.stop_reason == "noted"


def test_recall_of_this_chat_keeps_what_was_said_without_storing():
    told = "Only in our conversation, without storing it: I ride an e-bike to work."
    history = [Turn(told, "Got it.")]
    text = recalled([], ChatState(), history, "this_chat")
    assert "e-bike" in text and "Kept" not in text


def test_recall_of_what_is_kept_leaves_out_what_was_only_said():
    history = [Turn("I ride an e-bike to work, by the way.", "Got it.")]
    chat = ChatState(kept=("Prefers swimming over running",))
    text = recalled([], chat, history, "kept")
    assert "swimming" in text and "e-bike" not in text


# ---- the 34 metrics read the same through clauses ----


@pytest.mark.parametrize("metric", list(METRICS))
def test_every_metric_s_value_and_previous_day_resolve_through_clauses(metric):
    question = f"My {metric} on 2026-11-11?"
    request, _ = read(question, said(data(question, [metric], "value", dates("2026-11-11"))))
    assert request.parts[0].metrics == [metric]
    assert windows(request) == [(date(2026, 11, 11), date(2026, 11, 11))]
    before = {
        "kind": "beside_earlier",
        "counted_from": "its_last_day",
        "offset": -1,
        "new_period": "ends_there",
        "length": 1,
    }
    back = data("Back up by a single calendar day", [metric], "value", before, earlier_result=0)
    request, _ = read(
        "Back up by a single calendar day.",
        said(back),
        history=[earlier("2026-11-11", "2026-11-11", metric)],
    )
    assert windows(request) == [(date(2026, 11, 10), date(2026, 11, 10))]


# ---- the smoke run's three misreadings (real readings, 2026-11-19) ----

AROUND = "Use the mean over that date and the three dates immediately before it."
FOUR = {
    "kind": "beside_earlier",
    "counted_from": "its_last_day",
    "offset": 0,
    "new_period": "ends_there",
    "length": 4,
}


def around(*periods):
    return said(data(AROUND, ["steps"], "mean", *periods, earlier_result=0))


def test_the_same_day_plus_a_shift_for_one_mean_is_sent_back_not_asked():
    wrong = around({"kind": "same_as_earlier"}, {"kind": "shift_earlier", "days": -3})
    request, calls = read(
        AROUND,
        wrong,
        around(FOUR),
        history=[earlier("2028-02-29", "2028-02-29")],
        today=date(2028, 3, 4),
    )
    assert windows(request) == [(date(2028, 2, 26), date(2028, 2, 29))] and calls == 2
    assert request.attempts[0]["stage"] == "resolve"


def test_the_same_day_alone_for_that_date_and_three_before_is_sent_back():
    """It answered one day, silently: the stop rule of the smoke run."""
    request, calls = read(
        AROUND,
        around({"kind": "same_as_earlier"}),
        around(FOUR),
        history=[earlier("2027-01-01", "2027-01-01")],
        today=date(2027, 1, 8),
    )
    assert windows(request) == [(date(2026, 12, 29), date(2027, 1, 1))] and calls == 2
    assert request.attempts[0]["codes"] == ["read_back"]


def test_a_clause_copied_from_an_earlier_message_is_sent_back():
    """ "What have I told you about riding?" came back as remembering the previous message."""
    question = "What have I told you in this conversation about riding?"
    before = "Keep this only in our conversation, without storing it: I favour evening bike rides."
    stray = said(
        {"type": "memory", "said": before, "action": "remember"},
        {"type": "other", "said": question},
    )
    right = said({"type": "memory", "said": question, "action": "recall", "recall": "this_chat"})
    request, calls = read(question, stray, right, history=[Turn(before, "Got it.")])
    assert (request.kind, request.memory_action, request.recall) == (
        "memory",
        "recall",
        "this_chat",
    )
    assert calls == 2
