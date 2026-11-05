"""How the agent works on each kind of question: tools, guide, up-front evidence, widening."""

from datetime import date

import pytest

from app.agent.agent import SUBMIT, Claim, fallback_summary
from app.agent.ask import ask
from app.agent.intent import Intent
from app.agent.llm import Completion, ScriptedLLM, ToolCall, Usage
from app.agent.router import EXPERT_LABELS, LABELS, Classification, JevRouter, KeywordRouter
from app.agent.strategy import COACHING_OFFER, STRATEGIES, coaching_evidence, snapshot
from app.analysis.day import with_scores
from app.synthetic import Coupling, generate

START = date(2026, 7, 1)


@pytest.fixture(scope="module")
def frame():
    planted = (Coupling("bedtime_hour", "sleep_efficiency", 0, -0.9),)
    return with_scores(generate(START, 90, planted, seed=2).frame)


class Router:
    def __init__(self, question_type, intent=Intent.READ, **topic):
        self.result = Classification(
            dict.fromkeys(LABELS, 0.0) | (topic or {"sleep": 0.9}),
            dict.fromkeys(EXPERT_LABELS, 0.0),
            source="test",
            intent_probabilities={str(i): float(i == intent) for i in Intent},
            question_types={question_type: 1.0} if question_type else {},
        )

    def classify(self, question, earlier=()):
        return self.result


def submit(summary="Done.", claims=()):
    call = ToolCall("submit", SUBMIT, {"summary": summary, "claims": list(claims)})
    return Completion(None, (call,), "scripted", Usage(), 0.0, 0.0)


def offered_tools(llm):
    return set(llm.requests[0]["tools"])


@pytest.mark.parametrize(
    "question, kind",
    [
        ("How can I sleep better?", "coaching"),
        ("Why is my HRV low?", "why"),
        ("How did I sleep last night?", "day"),
        ("Do I sleep less on weekends?", "pattern"),
        ("Has my resting heart rate changed lately?", "change"),
        ("What was my best sleep this month?", "lookup"),
    ],
)
def test_the_keyword_router_tells_question_types_apart(question, kind):
    assert KeywordRouter().classify(question).question_type == kind


def test_jev_is_asked_the_question_type_in_the_same_call():
    questions = JevRouter("key").payload("How can I sleep better?")["questions"]
    assert questions["question_type"]["type"] == "choice"
    assert set(questions["question_type"]["criteria"]) == {*STRATEGIES, "world"}


def test_a_day_question_starts_with_a_snapshot_it_can_answer_from(frame):
    llm = ScriptedLLM([submit()])
    reply = ask(llm, Router("day"), frame, "How did I sleep last night?")
    task = llm.requests[0]["messages"][1]["content"]
    assert "Snapshot of the latest day" in task and "No hypotheses" in task
    assert offered_tools(llm) >= {"compare_day", "expand_tools"}
    assert "record_hypotheses" in offered_tools(llm)  # always there, just not asked for
    assert "correlate" not in offered_tools(llm)
    # The snapshot's evidence can be cited without a single tool call.
    sleep_id = next(i for i in reply.context.evidence) if reply.context.evidence else None
    assert sleep_id is None  # the conversation context itself is empty here


def evidence_id_for(task: str, name: str, section: str = "") -> str:
    """The evidence id the task lists for a metric (after `section`), as the model reads it."""
    lines = task[task.index(section) :].splitlines() if section else task.splitlines()
    line = next(line for line in lines if line.startswith(f"- {name} (evidence_id "))
    return line.split("evidence_id ")[1].split(")")[0]


def test_a_snapshot_claim_passes_with_no_tool_call(frame):
    found, _ = snapshot(frame, list(frame.columns))
    position = next(e for e in found if e.metrics[0] == "sleep_minutes").stats["position"]
    direction = {"above": "up", "below": "down", "within": None}[position]

    def answer_from_snapshot(messages):
        sleep_id = evidence_id_for(messages[1]["content"], "time asleep")
        claim = {
            "text": f"Last night's time asleep was {position} your usual range.",
            "kind": "day",
            "evidence_ids": [sleep_id],
            "metric": "sleep_minutes",
            "direction": direction,
        }
        return submit("Here is last night.", [claim])

    llm = ScriptedLLM([answer_from_snapshot])
    reply = ask(llm, Router("day"), frame, "How did I sleep last night?")
    assert [c.metric for c in reply.result.claims] == ["sleep_minutes"]
    assert reply.result.budget.calls == 1  # one model call; its only tool call was the submission
    assert reply.result.budget.tool_calls == 1


def test_coaching_gets_tested_habits_up_front_and_an_offer_after(frame):
    _, text = coaching_evidence(frame, "sleep", list(frame.columns))
    assert "supported:" in text

    def suggest(messages):
        task = messages[1]["content"]
        assert "Habits tested on this person's own days" in task
        claim = {
            "text": "On nights you were in bed earlier, your sleep efficiency was higher, so you "
            "could try that.",
            "kind": "suggestion",
            "evidence_ids": [evidence_id_for(task, "sleep efficiency", "Habits tested")],
            "metric": "sleep_efficiency",
        }
        return submit("Your data points to one habit.", [claim])

    reply = ask(ScriptedLLM([suggest]), Router("coaching"), frame, "How can I sleep better?")
    assert [c.kind for c in reply.result.claims] == ["suggestion"]
    assert reply.result.notes[-1] == COACHING_OFFER


def test_the_agent_can_widen_its_tools_once(frame):
    def expand(messages):
        return Completion(
            None,
            (ToolCall("x", "expand_tools", {"reason": "need a correlation"}),),
            "scripted",
            Usage(),
            0.0,
            0.0,
        )

    llm = ScriptedLLM([expand, expand, submit()])
    reply = ask(llm, Router("day"), frame, "How did I sleep last night, and why?")
    assert "correlate" not in set(llm.requests[0]["tools"])
    assert "correlate" in set(llm.requests[1]["tools"])  # widened for the next turn
    steps = [s for s in reply.result.trace if s.get("type") == "expand"]
    assert len(steps) == 1 and steps[0]["reason"] == "need a correlation"


def test_logging_keeps_the_full_toolbox(frame):
    llm = ScriptedLLM([submit()])
    ask(llm, Router("coaching", intent=Intent.LOG), frame, "Log a 30 minute run")
    assert "expand_tools" not in offered_tools(llm)


def test_an_unknown_type_works_like_before(frame):
    llm = ScriptedLLM([submit()])
    ask(llm, Router(None), frame, "Tell me about my data")
    task = llm.requests[0]["messages"][1]["content"]
    assert "record_hypotheses" in task and "Snapshot" not in task


def test_the_route_step_records_the_question_type(frame):
    reply = ask(ScriptedLLM([submit()]), Router("pattern"), frame, "Do I sleep less on weekends?")
    route = next(s for s in reply.result.trace if s["type"] == "route")
    assert route["question_type"] == "pattern"


def test_a_failed_summary_is_rebuilt_from_the_claims_grouped():
    claims = [
        Claim(
            text="time asleep did not clearly change",
            kind="no_change",
            evidence_ids=["a"],
            metric="sleep_minutes",
        ),
        Claim(
            text="bedtime did not clearly change",
            kind="no_change",
            evidence_ids=["b"],
            metric="bedtime_hour",
        ),
        Claim(
            text="sleep efficiency went down",
            kind="change",
            evidence_ids=["c"],
            metric="sleep_efficiency",
            direction="down",
        ),
    ]
    assert fallback_summary(claims) == (
        "Sleep efficiency went down. Time asleep and bedtime showed no clear change."
    )
