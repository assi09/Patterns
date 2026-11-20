"""The reader with explicit anchors and sources, read back by a small model (readback.py), and the
answers code says itself. Replaces the word-pattern checks that the v5, v6 and v7 audits showed
both rejected right readings and let wrong ones through.

Offline, the read-back's verdicts are scripted: these tests show what code hands the checker
(exact dates and how they stand to earlier results), and what happens with each verdict. Whether
the small model judges well is measured live, not here. Made-up dates and rows only.
"""

import json
from datetime import date
from types import SimpleNamespace

import pytest
from test_action_api import setup, sign_in  # noqa: F401 (the fixture)
from test_broad_questions import Router, planted, submit
from test_clauses import data, dates, earlier, said, windows
from test_v5_reliability import frame_until

from app.agent.agent import AgentResult
from app.agent.ask import MEDICAL_REFUSAL, ask
from app.agent.context import Turn
from app.agent.findings import render_overview
from app.agent.llm import ScriptedLLM
from app.agent.readback import described, relations
from app.agent.requested import execute
from app.agent.requests import Ambiguous, Reading, ResolvedPart, interpret, resolve
from app.agent.world import _used, answer_world, for_topic
from app.analysis.evidence import Window

TODAY = date(2026, 10, 31)


def verdict(matches=True, problem="", question=""):
    return ScriptedLLM.call("verdict", matches=matches, problem=problem, question=question)


def read(question, *readings, checks=(), history=(), today=TODAY):
    llm = ScriptedLLM(
        request_turns=[ScriptedLLM.call("read_request", **r) for r in readings],
        check_turns=list(checks) or None,
    )
    request, _, budget = interpret(llm, question, list(history), today, read_back=True)
    return request, llm


def checked_texts(llm):
    return [r["messages"][1]["content"] for r in llm.requests if r["role"] == "check"]


# ---- what code hands the checker ----


def test_each_period_says_how_it_stands_to_the_earlier_results_and_today():
    earlier_ = [(0, [Window(start="2026-08-03", end="2026-08-07")])]
    after = relations(Window(start="2026-08-08", end="2026-08-09"), earlier_, TODAY)
    moved = relations(Window(start="2026-08-04", end="2026-08-08"), earlier_, TODAY)
    same = relations(Window(start="2026-08-03", end="2026-08-07"), earlier_, TODAY)
    before = relations(Window(start="2026-07-30", end="2026-08-02"), earlier_, TODAY)
    assert "starts the day after earlier result 0 ends" in after
    assert "earlier result 0 moved 1 day(s) later" in moved
    assert "the same days as earlier result 0" in same
    assert "ends the day before earlier result 0 starts" in before
    assert relations(Window(start="2026-10-25", end="2026-10-31"), [], TODAY) == ["ends today"]


def test_the_reading_is_described_with_its_source_statistic_and_dates():
    state = {
        "data": [
            {
                "metrics": ["food_logs"],
                "operation": "food",
                "windows": [{"start": "2026-10-20", "end": "2026-10-20"}],
            }
        ]
    }
    request = resolve(
        Reading(
            kind="data",
            parts=[
                {
                    "metrics": ["calories"],
                    "operation": "value",
                    "reference": 0,
                    "periods": [{"kind": "inherit"}],
                    "source": "tracker",
                }
            ],
        ),
        state,
        TODAY,
    )
    before, reading = described(request, state, TODAY)
    assert "meals they logged" in before
    assert "the value of calories burned (from the tracker)" in reading
    assert "Tue Oct 20, 2026" in reading and "the same days as earlier result 0" in reading


# ---- what each verdict does ----

NEXT_TWO = "What does the same statistic come out to on the next two dates after the interval ends?"
BLOCK = earlier("2026-08-03", "2026-08-07", "steps", "min")
OLD_DAYS = data(NEXT_TWO, ["steps"], "min", {"kind": "same_as_earlier"}, earlier_result=0)
NEXT = data(NEXT_TWO, ["steps"], "min", {"kind": "after_earlier", "length": 2}, earlier_result=0)


def test_a_reading_the_checker_accepts_is_answered_with_one_reading():
    request, llm = read(NEXT_TWO, said(NEXT), checks=[verdict()], history=[BLOCK])
    assert windows(request) == [(date(2026, 8, 8), date(2026, 8, 9))]
    (text,) = checked_texts(llm)
    assert "starts the day after earlier result 0 ends" in text and NEXT_TWO in text


def test_a_mismatch_goes_back_to_the_reader_with_the_checker_s_reason():
    problem = "The message asks for the two days after the interval, not the interval again."
    request, llm = read(
        NEXT_TWO,
        said(OLD_DAYS),
        said(NEXT),
        checks=[verdict(False, problem, "Do you mean Aug 8 and 9?"), verdict()],
        history=[BLOCK],
    )
    assert windows(request) == [(date(2026, 8, 8), date(2026, 8, 9))]
    assert request.attempts[0]["codes"] == ["read_back"]
    retry = [r for r in llm.requests if r["role"] != "check"][-1]["messages"][-1]["content"]
    assert problem in json.loads(retry)["validation_error"]


def test_a_reading_still_wrong_after_its_retry_asks_the_person_the_checker_s_question():
    request, _ = read(
        NEXT_TWO,
        said(OLD_DAYS),
        said(OLD_DAYS),
        checks=[verdict(False, "old days", "Do you mean Aug 8 and 9?")] * 2,
        history=[BLOCK],
    )
    assert request.kind == "clarify" and request.clarification == "Do you mean Aug 8 and 9?"


def test_without_a_checker_the_reading_stands():
    request, _ = read(NEXT_TWO, said(OLD_DAYS), history=[BLOCK])
    assert windows(request) == [(date(2026, 8, 3), date(2026, 8, 7))]


def test_guidance_and_memory_are_not_read_back():
    words = "Please remember that I swim on Fridays."
    memory = {
        "type": "memory",
        "said": words,
        "action": "remember",
        "recall": None,
        "states_new_fact": False,
    }
    _, llm = read(words, said(memory), checks=[verdict(False, "x", "y")])
    assert not checked_texts(llm)


# ---- anchors the reader states ----

LOOK = "Between October 9 and 31, what changed in my data compared with the four weeks before?"


def investigate(words, *periods, **extra):
    return {
        "type": "investigate",
        "said": words,
        "focus": "what_changed",
        "metrics": [],
        "periods": list(periods),
        **extra,
    }


def test_a_baseline_relative_to_the_clause_counts_from_its_first_period():
    """Every v7 investigation asked "which earlier measurement?" on a first message."""
    before = {"kind": "before_earlier", "length": 28, "relative_to": "this_clause"}
    request, _ = read(LOOK, said(investigate(LOOK, dates("2026-10-09", "2026-10-31"), before)))
    assert windows(request) == [
        (date(2026, 10, 9), date(2026, 10, 31)),
        (date(2026, 9, 11), date(2026, 10, 8)),
    ]


def test_relative_to_an_earlier_result_with_none_is_sent_back_not_asked():
    wrong = {"kind": "before_earlier", "length": 28, "relative_to": "earlier_result"}
    right = {"kind": "before_earlier", "length": 28, "relative_to": "this_clause"}
    request, llm = read(
        LOOK,
        said(investigate(LOOK, dates("2026-10-09", "2026-10-31"), wrong)),
        said(investigate(LOOK, dates("2026-10-09", "2026-10-31"), right)),
    )
    assert request.kind == "investigate" and len(windows(request)) == 2
    assert request.attempts[0]["outcome"] == "sent_back"


def test_a_block_relative_to_an_earlier_result_still_uses_it():
    words = "And the 28 days before that?"
    before = {"kind": "before_earlier", "length": 28, "relative_to": "earlier_result"}
    request, _ = read(
        words,
        said(data(words, ["steps"], "mean", before, earlier_result=0)),
        history=[earlier("2026-10-09", "2026-10-31")],
    )
    assert windows(request) == [(date(2026, 9, 11), date(2026, 10, 8))]


# ---- sources the reader states ----

MEAL_DAY = Turn(
    "q",
    "a",
    request_state={
        "data": [
            {
                "metrics": ["food_logs"],
                "operation": "food",
                "windows": [{"start": "2026-10-20", "end": "2026-10-20"}],
            }
        ]
    },
)


@pytest.mark.parametrize(
    "clause, metrics",
    [
        (
            data(
                "calories burned?",
                ["calories"],
                "value",
                {"kind": "same_as_earlier"},
                earlier_result=0,
                source="tracker",
            ),
            ["calories"],
        ),
        (
            data(
                "just dinner",
                [],
                "sum",
                {"kind": "same_as_earlier"},
                earlier_result=0,
                source="food_log",
                meal_type="DINNER",
            ),
            ["food_logs"],
        ),
        (
            data(
                "and protein?",
                ["protein"],
                "sum",
                {"kind": "same_as_earlier"},
                earlier_result=0,
                source="food_log",
            ),
            ["food_logs"],
        ),
    ],
)
def test_the_source_is_what_the_reader_says(clause, metrics):
    request, _ = read(clause["said"], said(clause), history=[MEAL_DAY])
    assert request.parts[0].metrics == metrics


def test_food_logs_named_under_the_tracker_can_only_mean_the_food_log():
    words = "the meals"
    reading = data(
        words, ["food_logs"], "sum", {"kind": "same_as_earlier"}, earlier_result=0, source="tracker"
    )
    request, _ = read(words, said(reading), history=[MEAL_DAY])
    assert request.parts[0].metrics == ["food_logs"]


def test_a_tracker_metric_beside_food_eaten_is_sent_back_to_be_split():
    words = "steps and the meals"
    mixed = data(
        words, ["food_logs", "steps"], "food", {"kind": "same_as_earlier"}, earlier_result=0
    )
    request, _ = read(words, said(mixed), history=[MEAL_DAY])
    assert request.attempts[0]["outcome"] == "sent_back"


def test_a_count_with_no_threshold_goes_back_once_then_asks():
    words = "How many days last week?"
    count = data(words, ["steps"], "count", {"kind": "calendar", "unit": "week", "offset": -1})
    request, _ = read(words, said(count), said(count))
    assert request.kind == "clarify" and "threshold" in request.clarification


# ---- guidance subjects and medical requests the reader states ----


def guidance(words, topics=(), refers_back=False):
    return {
        "type": "guidance",
        "said": words,
        "topics": list(topics),
        "refers_back": refers_back,
        "question": words,
    }


def test_a_follow_up_refers_back_to_the_earlier_subject():
    state = {"guidance": ["desk worker", "interrupt long sitting"]}
    request = resolve(
        Reading(
            kind="guidance", guidance_reference=True, guidance_question="Is a walk an example?"
        ),
        state,
        TODAY,
    )
    assert request.topics == ["desk worker, interrupt long sitting"]


def test_referring_back_to_nothing_asks():
    with pytest.raises(Ambiguous):
        resolve(
            Reading(kind="guidance", guidance_reference=True, guidance_question="And it?"),
            {},
            TODAY,
        )


def test_a_general_guidance_question_is_looked_up_as_asked():
    words = "What does the guidance say about winding down before bed?"
    request, _ = read(words, said(guidance(words)))
    assert request.kind == "guidance" and request.topics == []


def test_a_medical_request_is_refused_before_any_data_is_read():
    words = "Does that number mean I have a heart condition?"
    reading = said(data(words, ["resting_hr"], "value", dates("2026-10-30"))) | {"medical": True}
    llm = ScriptedLLM([submit()], request_turns=[ScriptedLLM.call("read_request", **reading)] * 2)
    reply = ask(llm, Router("lookup"), planted(), words, today=TODAY)
    assert reply.result.summary == MEDICAL_REFUSAL and reply.route.action == "refuse"
    assert not reply.result.evidence


# ---- an overview is said by code ----


@pytest.fixture(scope="module")
def two_changes():
    from test_broad_questions import ON

    from app.synthetic import Step

    return planted(Step("steps", ON, -5000.0), Step("sleep_minutes", ON, -90.0))


def test_an_overview_lists_its_clear_changes_each_cited_and_counts_the_rest(two_changes):
    from test_v5_reliability import overview

    from app.agent.verifier import _significant

    records = list(overview(two_changes).values())
    text, claims = render_overview(records, TODAY)
    clear = [r for r in records if "difference" in r.stats and _significant(r)]
    steady = [r for r in records if "difference" in r.stats and not _significant(r)]
    assert "the clear changes were" in text and "Steps went down" in text
    assert f"The other {len(steady)} measures tested showed no clear change" in text
    assert {c.metric for c in claims if c.kind == "change"} == {r.metrics[0] for r in clear}
    assert set(claims[-1].evidence_ids) == {r.id for r in steady}


def test_an_overview_answer_drops_the_model_s_prose(two_changes):
    llm = ScriptedLLM(
        [submit("Your sleep fell; the rest looked steady.")] * 3,
        request_turns=[
            ScriptedLLM.call("read_request", kind="investigate", focus="what_changed", parts=[])
        ]
        * 2,
    )
    from test_broad_questions import END

    reply = ask(llm, Router("change"), two_changes, "What changed lately?", today=END)
    assert "the rest looked steady" not in reply.result.summary
    assert "clear changes were" in reply.result.summary
    assert all(c.evidence_ids[0] in reply.result.evidence for c in reply.result.claims)


# ---- guidance cites the passages the writer used ----


def test_the_writer_s_sources_line_is_read_and_removed():
    assert _used("Lie down.\nSources: 1, 3") == ("Lie down.", [1, 3])
    assert _used("Lie down.") == ("Lie down.", None)


def says(text):
    return ScriptedLLM.say(text)


def test_only_the_passages_the_writer_used_are_cited():
    from app.agent.knowledge import KNOWLEDGE_LOOKUP

    llm = ScriptedLLM(
        [
            ScriptedLLM.call(KNOWLEDGE_LOOKUP, query="wind down before bed"),
            says("Do something calm before bed, the same way each night.\nSources: 1"),
        ],
        embeddings_fail=True,
    )
    outside = SimpleNamespace(web=lambda *args: {"error": "disabled"})
    result = answer_world(llm, "What helps me wind down before bed?", outside)
    (claim,) = result.claims
    assert len(claim.evidence_ids) == 1 and "Sources" not in result.summary


def found(title, kind="exercise"):
    return SimpleNamespace(passage=SimpleNamespace(title=title, kind=kind))


def test_the_variant_pick_decides_even_when_a_title_matches():
    """A word-for-word title match no longer bypasses the pick: "regular push-up" matched no
    title but got plyo and single-arm; "bodyweight bridge" got the physioball one (v7)."""
    llm = ScriptedLLM([ScriptedLLM.call("same_exercise", items=[2])])
    picked = for_topic(
        [found("Physioball Hip Bridge"), found("Butt Lift (Bridge)"), found("Sleep", "guideline")],
        "bodyweight bridge",
        llm,
        SimpleNamespace(check=lambda: None, charge=lambda c: None, calls=0, cost_usd=0.0),
    )
    assert [f.passage.title for f in picked] == ["Butt Lift (Bridge)", "Sleep"]


# ---- carried over from the v6 file: behaviour, not wording ----


def test_a_relationship_with_no_paired_days_gives_each_metric_s_coverage():
    frame = frame_until(date(2026, 11, 19), ("steps", "hrv_ms"))
    frame["hrv_ms"] = float("nan")
    request = resolve(
        Reading(
            kind="data",
            parts=[
                {
                    "metrics": ["steps", "hrv_ms"],
                    "operation": "correlate",
                    "periods": [{"kind": "explicit", "start": "2026-11-03", "end": "2026-11-08"}],
                }
            ],
        ),
        {},
        date(2026, 11, 19),
    )
    result = execute(request, frame, date(2026, 11, 19))
    assert (
        "steps on 6 of 6 days" in result.summary and "no heart rate variability" in result.summary
    )
    (claim,) = result.claims
    assert len(claim.evidence_ids) == 2 and all(i in result.evidence for i in claim.evidence_ids)


@pytest.mark.parametrize("told", [False, True])
def test_a_pure_question_leaves_no_candidate_in_the_store(setup, monkeypatch, told):  # noqa: F811
    from dataclasses import replace

    from test_v5_reliability import Synchronous, reader_said

    from app.api import chat

    client, _, agent = setup
    headers = sign_in(setup)
    monkeypatch.setattr(chat, "update_summary", lambda *args: None)
    monkeypatch.setattr(chat, "_pool", Synchronous(chat._pool))
    listening = replace(agent, background=True)
    client.app.dependency_overrides[chat.get_agent] = lambda: listening
    question = "During Jul 1-7 count the days on which my steps were 6000 or above."
    statement = "I'm aiming for 6000 steps a day."
    clauses = [
        data(
            question,
            ["steps"],
            "count",
            dates("2026-07-01", "2026-07-07"),
            comparison=">=",
            threshold=6000,
        )
    ]
    if told:
        clauses.insert(0, {"type": "other", "said": statement})
    agent.llm.request_turns = [reader_said(*clauses)]
    agent.llm.turns = [
        ScriptedLLM.call(
            "record_memories", memories=[{"kind": "goal", "text": "Aims for 6000 steps"}]
        )
    ] * 2
    text = f"{statement} {question}" if told else question
    first = client.post("/chat", headers=headers, json={"text": text}).json()[-1]
    kept = client.get("/memory", headers=headers).json()
    assert bool(kept["waiting"] + kept["noticed"] + kept["kept"]) == told
    assert "at or above 6,000" in first["text"]


def test_resolved_part_helper_sanity():
    assert ResolvedPart(metrics=["steps"], operation="mean").windows == []
    assert AgentResult(run_id="x", stop_reason="x").side_claims == []


def _compared(metric: str, difference: float, p: float, rank: int | None = None):
    from app.analysis.evidence import Evidence

    stats = {"difference": difference, "p_value": p, "mean_recent": 1.0, "mean_baseline": 1.0}
    if rank is not None:
        stats["overview_rank"] = rank
    return Evidence(
        tool="compare_windows",
        metrics=[metric],
        windows=[
            Window(start="2026-10-12", end="2026-10-31"),
            Window(start="2026-09-21", end="2026-10-11"),
        ],
        stats=stats,
        n=20,
        sufficient=True,
    )


def test_an_overview_with_nine_clear_changes_names_and_cites_every_one():
    """v8 showed "1 more measures also changed clearly." with no citation: past the eighth, a
    clear change was counted but neither named nor linked to its evidence."""
    moved = [
        "steps",
        "distance_km",
        "calories",
        "hrv_ms",
        "deep_sleep_minutes",
        "rem_sleep_minutes",
        "sleep_minutes",
        "light_sleep_minutes",
        "time_in_bed",
    ]
    clear = [_compared(m, -1.0 if i % 2 else 1.0, 0.001, rank=i + 1) for i, m in enumerate(moved)]
    steady = [_compared("resting_hr", 0.1, 0.6)]
    text, claims = render_overview([*clear, *steady], TODAY)
    changes = [c for c in claims if c.kind == "change"]
    assert [c.metric for c in changes] == moved
    assert {i for c in changes for i in c.evidence_ids} == {r.id for r in clear}
    assert "Also changed clearly: time in bed (up)." in text and "more measures" not in text
    assert "The other 1 measure tested showed no clear change" in text
    assert claims[-1].evidence_ids == [steady[0].id]
