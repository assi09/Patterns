"""Codex's review of bcdb0ff: one record-aware renderer for every observation a reply can say,
coaching included; a repeat beside another clause keeps what it is; the same result is kept once;
and a retry keeps a length the message said. Each case is a reproduction from the review with
its contrasting controls; made-up data only."""

from datetime import date

import pandas as pd
import pytest
from test_clauses import SAME, data, read, redo, said
from test_e1c1eec_review import STEP_UP, TAGGED, WEEKENDS, WHOLE, records

from app.agent.agent import AgentResult
from app.agent.ask import ask, coaching_by_code
from app.agent.context import Turn
from app.agent.llm import Budget, ScriptedLLM
from app.agent.requests import kept_fields, resolve
from app.agent.router import KeywordRouter
from app.agent.verifier import Claim, verify
from app.analysis.habits import tag_effect
from app.analysis.tools import change_point, weekday_split

# ---- 1. coaching's observations go through the same renderer ----


@pytest.mark.parametrize(
    "record",
    [
        change_point(STEP_UP, "steps", WHOLE),
        weekday_split(WEEKENDS, "steps", WHOLE),
        tag_effect(TAGGED, "hard_training", "steps", WHOLE),
        *records(STEP_UP),
    ],
    ids=lambda r: r.tool,
)
def test_a_coaching_answers_observation_is_stated_with_its_figures(record):
    """coaching_render_probe: change point, weekday split and tag effect came out as "Steps went
    up: against ." in coaching, and the tagged one was re-kinded as a change."""
    kind = "change" if record.tool in ("change_point", "compare_windows", "trend") else "value"
    result = AgentResult(run_id="r", stop_reason="submitted", summary="Model prose.")
    result.evidence[record.id] = record
    result.claims = [
        Claim(
            text="Steps differed.",
            kind=kind,
            metric="steps",
            direction="up",
            evidence_ids=[record.id],
        )
    ]
    coaching_by_code(result, [], 1)
    assert " against ." not in result.summary and ": ." not in result.summary
    assert "Model prose" not in result.summary
    published = [c for c in result.claims if record.id in c.evidence_ids]
    assert not verify(published, result.evidence).rejected


def test_a_coaching_observation_with_no_figure_to_state_is_said_left_out():
    short = change_point(STEP_UP.iloc[:4], "steps", WHOLE)
    result = AgentResult(run_id="r", stop_reason="submitted", summary="Model prose.")
    result.evidence[short.id] = short
    result.claims = [Claim(text="x", kind="value", metric="steps", evidence_ids=[short.id])]
    coaching_by_code(result, [], 1)
    assert not short.sufficient and any("left out" in n for n in result.notes)
    assert "Model prose" not in result.summary


# ---- 2. a repeat beside another clause keeps what it is ----

LOOK_STATE = {
    "last": "investigate",
    "focus": "overview",
    "data": [
        {
            "metrics": [],
            "operation": "describe",
            "windows": [
                {"start": "2026-10-11", "end": "2026-10-24"},
                {"start": "2026-08-17", "end": "2026-08-30"},
            ],
        }
    ],
    "answer": {"kind": "investigate", "parts": 1, "reads": 0, "focus": "overview"},
}
FRAME = pd.DataFrame(
    {"steps": [5000.0] * 14 + [10000.0] * 14},
    index=pd.date_range("2026-08-17", periods=14).append(pd.date_range("2026-10-11", periods=14)),
)
WORDS = "Repeat that all-measure comparison."
STATUS = {"type": "status", "said": "Also tell me whether the entry is saved.", "about": "entry"}


def composed(*companions):
    from app.agent.clauses import Said, reading_from

    words = " ".join([WORDS, *(c["said"] for c in companions)])
    raw = said(redo(WORDS), *companions)
    reading = reading_from(Said.model_validate(raw), words, earlier=True)
    return words, resolve(reading, LOOK_STATE, date(2026, 11, 21))


def test_a_repeated_overview_beside_a_status_is_both_in_the_answer():
    """independent_probes: only the status came back, with no note and no claim."""
    words, request = composed(STATUS)
    assert request.kind == "investigate" and request.status and request.parts[0].metrics == []
    answer = ask(
        ScriptedLLM([]),
        KeywordRouter(),
        FRAME,
        words,
        today=date(2026, 11, 21),
        request_bundle=(request, {}, Budget()),
    )
    assert "Steps went up" in answer.result.summary and answer.result.all_claims
    assert any("written to your tracker" in n or "Not yet" in n for n in answer.result.notes)


def test_a_repeated_overview_beside_guidance_is_asked_about_not_dropped():
    guide = {
        "type": "guidance",
        "said": "And explain a plank.",
        "topics": ["plank"],
        "question": "x",
    }
    from app.agent.requests import TOGETHER, Ambiguous

    with pytest.raises(Ambiguous, match=TOGETHER):
        composed(guide)


def test_a_repeated_overview_alone_is_the_overview():
    _, request = composed()
    assert request.kind == "investigate" and not request.status and not request.reads


def test_a_repeated_figure_beside_a_status_is_a_read():
    steps = {
        "metrics": ["steps"],
        "operation": "mean",
        "windows": [{"start": "2026-10-11", "end": "2026-10-24"}],
    }
    history = [Turn("x", "y", request_state={"last": "data", "data": [steps]})]
    words = f"{WORDS} {STATUS['said']}"
    request, _ = read(words, said(redo(WORDS), STATUS), history=history, pending=True)
    assert request.kind == "status" and [p.metrics for p in request.reads] == [["steps"]]


# ---- 3. the same result is kept once, and the next turn is not asked which ----

THREE = "For this reply, up to three sourced ideas."


def test_a_repeat_and_a_look_for_the_same_follow_up_are_one_result_now_and_next_turn():
    """investigate_lowwear-02/t4: both were saved, and "why did those change?" asked which."""
    look = {
        "type": "investigate",
        "said": THREE,
        "focus": "coaching",
        "metrics": [],
        "periods": [SAME],
        "earlier_result": 0,
        "points": 3,
    }
    history = [Turn("Review every measure.", "Nothing changed.", request_state=LOOK_STATE)]
    from app.agent.llm import ScriptedLLM as Scripted
    from app.agent.requests import interpret

    llm = Scripted(
        request_turns=[Scripted.call("read_request", **said(redo(THREE, options=3), look))]
    )
    request, state, _ = interpret(llm, THREE, history, date(2026, 11, 21), read_back=False)
    assert request.kind == "investigate" and not request.reads and len(state["data"]) == 1
    assert (state["answer"]["parts"], state["answer"]["reads"]) == (1, 0)
    why = "Why did those changes happen?"
    clause = {
        "type": "investigate",
        "said": why,
        "focus": "why",
        "metrics": [],
        "periods": [SAME],
        "earlier_result": None,
    }
    following, _ = read(
        why, said(clause), history=[*history, Turn(THREE, "x", request_state=state)]
    )
    assert following.kind == "investigate" and len(following.parts[0].windows) == 2


def test_a_state_saved_with_a_duplicate_reads_it_once():
    duplicated = {**LOOK_STATE, "data": LOOK_STATE["data"] * 2}
    why = "Why?"
    clause = {
        "type": "investigate",
        "said": why,
        "focus": "why",
        "metrics": [],
        "periods": [SAME],
        "earlier_result": None,
    }
    request, _ = read(why, said(clause), history=[Turn("x", "y", request_state=duplicated)])
    assert request.kind == "investigate" and len(request.parts[0].windows) == 2


def test_different_results_still_ask_which():
    other = {
        "metrics": ["steps"],
        "operation": "mean",
        "windows": [{"start": "2026-10-11", "end": "2026-10-24"}],
    }
    two = {**LOOK_STATE, "data": [*LOOK_STATE["data"], other], "answer": None}
    words = "And the median?"
    request, _ = read(
        words, said(data(words, [], "median", SAME)), history=[Turn("x", "y", request_state=two)]
    )
    assert request.kind == "clarify"


# ---- 4. a retry keeps a length the message said ----

LENGTH_WORDS = "Make the opening date the closing date of a three-day block."


def placed(first, last, length):
    day = lambda edge: {"counted_from": edge, "days_after": 0}  # noqa: E731
    return {
        "kind": "from_earlier",
        "new_first_day": day(first) if first else None,
        "new_last_day": day(last) if last else None,
        "length": length,
    }


def test_a_retry_that_drops_the_said_length_gets_it_back():
    """metric_strain-02/t2: both days placed at one day with length 3; the retry dropped the
    length and one day was accepted."""
    first = said(redo(LENGTH_WORDS, placed("its_first_day", "its_first_day", 3)))
    second = said(redo(LENGTH_WORDS, placed(None, "its_first_day", None)))
    kept = kept_fields(second, first, ("periods.length",))
    assert kept["clauses"][0]["periods"][0]["length"] == 3


def test_the_whole_retry_gives_the_three_days_or_asks_never_one_day():
    block = Turn(
        "Median strain Sep 16-21?",
        "7.7",
        request_state={
            "data": [
                {
                    "metrics": ["strain"],
                    "operation": "median",
                    "windows": [{"start": "2026-09-16", "end": "2026-09-21"}],
                }
            ],
            "last": "data",
        },
    )
    first = said(redo(LENGTH_WORDS, placed("its_first_day", "its_first_day", 3)))
    fixed = said(redo(LENGTH_WORDS, placed(None, "its_first_day", None)))
    request, _ = read(LENGTH_WORDS, first, fixed, history=[block])
    assert [(w.start, w.end) for p in request.parts for w in p.windows] == [
        (date(2026, 9, 14), date(2026, 9, 16))
    ]
    still = said(redo(LENGTH_WORDS, placed("its_first_day", "its_first_day", None)))
    asked, _ = read(LENGTH_WORDS, first, still, history=[block])
    assert asked.kind == "clarify"  # one day is never accepted in place of the three said
    assert "Which 3 days" in asked.clarification
