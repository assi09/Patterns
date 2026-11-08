import json
from dataclasses import replace
from datetime import date

import pytest

from app.agent.agent import SUBMIT
from app.agent.ask import REFUSAL, ask, default_router
from app.agent.experts import CONSULT
from app.agent.llm import Completion, ScriptedLLM, ToolCall, Usage
from app.agent.router import (
    EXPERT_LABELS,
    LABELS,
    Classification,
    FallbackRouter,
    KeywordRouter,
    RouterError,
)
from app.config import Settings
from app.synthetic import generate


@pytest.fixture(scope="module")
def frame():
    return generate(date(2026, 7, 1), 60, seed=5).frame


class FixedRouter:
    def __init__(self, needs: tuple[str, ...] = (), **given: float):
        topic = dict.fromkeys(LABELS, 0.0) | given
        needed = {e: 1.0 if e in needs else 0.0 for e in EXPERT_LABELS}
        self.result = Classification(topic, needed, source="test")
        self.questions: list[str] = []
        self.earlier: list[list[str]] = []

    def classify(self, question: str, earlier=()) -> Classification:
        self.questions.append(question)
        self.earlier.append(list(earlier))
        return self.result


def route_step(reply) -> dict:
    return next(s for s in reply.result.trace if s["type"] == "route")


def empty_submission() -> Completion:
    call = ToolCall("submit", SUBMIT, {"summary": "Nothing stood out.", "claims": []})
    return Completion(None, (call,), "scripted", Usage(), 0.0, 0.0)


def test_an_out_of_scope_question_is_refused_without_calling_the_model(frame):
    llm = ScriptedLLM([])
    reply = ask(llm, FixedRouter(out_of_scope=0.9, sleep=0.1), frame, "Do I have apnea?")
    assert reply.result.stop_reason == "refused" and reply.result.summary == REFUSAL
    assert llm.requests == []
    assert [s["type"] for s in reply.result.trace] == ["context", "route"]
    assert route_step(reply)["action"] == "refuse"


def test_a_clear_question_goes_to_its_expert_without_consults(frame):
    llm = ScriptedLLM([empty_submission()])
    reply = ask(llm, FixedRouter(sleep=0.9, general=0.1), frame, "How is my sleep?")
    assert reply.result.expert == "sleep" and reply.route.routed
    assert "You are the sleep expert" in llm.requests[0]["messages"][0]["content"]
    assert CONSULT not in llm.requests[0]["tools"]


def test_a_cross_domain_question_lets_the_lead_consult_the_other_expert(frame):
    llm = ScriptedLLM([empty_submission()])
    router = FixedRouter(("recovery", "sleep"), recovery=0.75, sleep=0.25)
    reply = ask(llm, router, frame, "Did my late nights hurt my recovery?")
    assert reply.result.expert == "recovery" and reply.route.consult == ("sleep",)
    assert CONSULT in llm.requests[0]["tools"]
    step = route_step(reply)
    assert step["expert"] == "recovery" and step["consult"] == ["sleep"]
    assert step["probabilities"]["sleep"] == pytest.approx(0.25)
    assert step["needs"] == {"sleep": 1.0, "recovery": 1.0, "activity": 0.0, "nutrition": 0.0}


def test_low_confidence_goes_to_the_general_agent(frame):
    llm = ScriptedLLM([empty_submission()])
    reply = ask(llm, FixedRouter(sleep=0.34, recovery=0.33, activity=0.33), frame, "Anything?")
    assert reply.route.action == "general" and reply.result.expert == "general"
    assert "You are the" not in llm.requests[0]["messages"][0]["content"]


def test_a_question_about_the_chat_is_answered_from_it_not_from_the_data(frame):
    from app.agent.context import Turn

    history = [Turn("I had pasta, log it", "A logging draft is ready for review.")]
    llm = ScriptedLLM([ScriptedLLM.say("You asked me to log pasta.")])
    # Nutrition has no data here; before, its expert answered that without reading the chat.
    router = FixedRouter(("nutrition",), conversation=0.8, nutrition=0.2)
    reply = ask(llm, router, frame, "What did I just say?", history=history, choice="nutrition")
    assert reply.route.action == "conversation"
    assert reply.result.summary == "You asked me to log pasta."
    assert reply.result.expert == "general"
    assert [s["type"] for s in reply.result.trace][:3] == ["context", "route", "recall"]


def test_a_workout_and_a_meal_in_one_request_offer_both_logging_tools(frame):
    from app.agent.agent import ExtraTool
    from app.agent.intent import Intent

    def tool(name):
        return ExtraTool(name, "", {"type": "object", "properties": {}}, lambda a: ("{}", {}))

    tools = {"activity": [tool("propose_workout_log")], "nutrition": [tool("propose_food_log")]}
    router = FixedRouter(("activity", "nutrition"), activity=0.7, nutrition=0.3)
    router.result = replace(
        router.result, intent_probabilities={str(i): float(i == Intent.LOG) for i in Intent}
    )
    llm = ScriptedLLM([empty_submission()])
    ask(llm, router, frame, "Log my swim and the 3 figs before it", action_tools=tools)
    offered = llm.requests[0]["tools"]
    assert "propose_workout_log" in offered and "propose_food_log" in offered
    # Every answer speaks in the same voice.
    assert "Your voice" in llm.requests[0]["messages"][0]["content"]


def test_a_chosen_expert_answers_and_the_answer_says_it_was_chosen(frame):
    llm = ScriptedLLM([empty_submission()])
    router = FixedRouter(("sleep",), sleep=1.0)
    reply = ask(llm, router, frame, "How is my sleep?", choice="activity")
    assert reply.result.expert == "activity" and not reply.route.routed
    assert reply.route.consult == ("sleep",)  # the router still decides who is consulted


def test_only_the_question_reaches_the_router(frame):
    router = FixedRouter(sleep=1.0)
    ask(ScriptedLLM([empty_submission()]), router, frame, "How is my sleep?")
    assert router.questions == ["How is my sleep?"]


def test_request_intent_is_in_the_trace_without_enabling_logging_tools(frame):
    llm = ScriptedLLM([empty_submission()])
    reply = ask(llm, KeywordRouter(), frame, "Log a run.")
    step = route_step(reply)
    assert step["intent"] == "log" and step["intent_probabilities"]["log"] == 1.0
    assert reply.result.expert == "activity"
    assert not any("write" in tool or "log" in tool for tool in llm.requests[0]["tools"])
    assert json.loads(json.dumps(step))["intent"] == "log"


def test_without_a_typesafe_key_the_keyword_rule_routes():
    assert isinstance(default_router(Settings(typesafe_api_key=None)), KeywordRouter)
    router = default_router(Settings(typesafe_api_key="key"))
    assert isinstance(router, FallbackRouter) and isinstance(router.fallback, KeywordRouter)
    assert issubclass(RouterError, RuntimeError)


def submit_claims(claims: list[dict]) -> Completion:
    call = ToolCall("submit", SUBMIT, {"summary": "Here is what I found.", "claims": claims})
    return Completion(None, (call,), "scripted", Usage(), 0.0, 0.0)


@pytest.fixture(scope="module")
def sleep_evidence(frame):
    from app.analysis import tools
    from app.analysis.evidence import Window

    window = Window(start=date(2026, 7, 1), end=date(2026, 8, 29))
    return tools.describe(frame, "sleep_minutes", window)


def earlier_sleep_turn(evidence, answered_by="sleep"):
    from app.agent.context import Turn

    claim = {
        "text": "Your time asleep held steady.",
        "kind": "no_change",
        "evidence_ids": [evidence.id],
        "metric": "sleep_minutes",
    }
    return Turn("How is my sleep?", "Your time asleep held steady.", (claim,), answered_by)


def steady_sleep_claim(evidence) -> dict:
    return {
        "text": "Your time asleep held steady.",
        "kind": "no_change",
        "evidence_ids": [evidence.id],
        "metric": "sleep_minutes",
    }


def test_a_follow_up_is_routed_with_earlier_questions_and_sees_the_conversation(
    frame, sleep_evidence
):
    llm = ScriptedLLM([empty_submission()])
    router = FixedRouter(("sleep",), sleep=0.9, general=0.1)
    history = [earlier_sleep_turn(sleep_evidence)]
    reply = ask(
        llm,
        router,
        frame,
        "And last week?",
        history=history,
        stored_evidence={sleep_evidence.id: sleep_evidence},
    )
    assert router.earlier == [["How is my sleep?"]]
    task = llm.requests[0]["messages"][1]["content"]
    assert "<context>" in task and "How is my sleep?" in task
    assert task.index("<context>") < task.index("The person asks: And last week?")
    step = reply.result.trace[0]
    assert step["type"] == "context" and step["turns_verbatim"] == [0]
    assert step["evidence"] == [sleep_evidence.id]


def test_a_follow_up_may_cite_an_earlier_answers_evidence_without_recomputing(
    frame, sleep_evidence
):
    llm = ScriptedLLM([submit_claims([steady_sleep_claim(sleep_evidence)])])
    reply = ask(
        llm,
        FixedRouter(("sleep",), sleep=1.0),
        frame,
        "Is that still true?",
        history=[earlier_sleep_turn(sleep_evidence)],
        stored_evidence={sleep_evidence.id: sleep_evidence},
    )
    assert len(reply.result.claims) == 1 and reply.result.rejected == []
    assert not [s for s in reply.result.trace if s["type"] == "tool"]  # nothing recomputed


def test_earlier_evidence_counts_as_its_owners_for_another_lead(frame, sleep_evidence):
    # Recovery may claim about sleep on the sleep expert's earlier evidence, not on the general
    # agent's.
    def run(answered_by):
        llm = ScriptedLLM([submit_claims([steady_sleep_claim(sleep_evidence)])] * 2)
        return ask(
            llm,
            FixedRouter(("recovery",), recovery=1.0),
            frame,
            "Did that go with my HRV?",
            history=[earlier_sleep_turn(sleep_evidence, answered_by)],
            stored_evidence={sleep_evidence.id: sleep_evidence},
        ).result

    assert len(run("sleep").claims) == 1
    assert run("general").claims == []


def test_an_attached_metric_decides_the_lead_unless_the_person_picked_one(frame):
    from app.agent.context import Attachment

    router = FixedRouter(("sleep",), sleep=1.0)
    attached = Attachment("hrv_ms")
    reply = ask(ScriptedLLM([empty_submission()]), router, frame, "Why?", attachment=attached)
    assert reply.result.expert == "recovery" and not reply.route.routed
    assert reply.route.consult == ("sleep",)  # the router still decides who is consulted
    picked = ask(
        ScriptedLLM([empty_submission()]),
        router,
        frame,
        "Why?",
        attachment=attached,
        choice="activity",
    )
    assert picked.result.expert == "activity"


def test_an_attachment_does_not_get_a_medical_question_answered(frame):
    from app.agent.context import Attachment

    llm = ScriptedLLM([])
    router = FixedRouter(out_of_scope=0.9, recovery=0.1)
    reply = ask(llm, router, frame, "Is this arrhythmia?", attachment=Attachment("hrv_ms"))
    assert reply.result.stop_reason == "refused" and llm.requests == []


class FakeGuard:
    """Flags sentences containing any of the given words, and records what it was shown."""

    def __init__(self, *words: str, fail: bool = False):
        self.words, self.fail = words, fail
        self.seen: list[list[str]] = []

    def judge(self, texts):
        from app.agent.guard import GuardError, Judgement

        self.seen.append(list(texts))
        if self.fail:
            raise GuardError("Jev took too long to answer.")
        flags = tuple(any(w in t for w in self.words) for t in texts)
        return Judgement(flags, tuple(float(f) for f in flags))


def sleep_answer(text: str, summary: str = "Here is what I found."):
    def turn(messages):
        payload = next(
            json.loads(m["content"])
            for m in reversed(messages)
            if m["role"] == "tool" and '"tool": "describe"' in m["content"]
        )
        claim = {
            "text": text,
            "kind": "no_change",
            "evidence_ids": [payload["evidence_id"]],
            "metric": "sleep_minutes",
        }
        call = ToolCall("submit", SUBMIT, {"summary": summary, "claims": [claim]})
        return Completion(None, (call,), "scripted", Usage(), 0.0, 0.0)

    return turn


DESCRIBE_SLEEP = ScriptedLLM.call(
    "describe", metric="sleep_minutes", start="2026-07-01", end="2026-08-29"
)


def test_advice_the_word_check_misses_is_sent_back_then_dropped(frame):
    from app.agent.guard import REASON

    advice = "Your time asleep held steady; cutting caffeine would help."
    llm = ScriptedLLM([DESCRIBE_SLEEP, sleep_answer(advice), sleep_answer(advice)])
    guard = FakeGuard("caffeine")
    reply = ask(llm, FixedRouter(("sleep",), sleep=1.0), frame, "How is my sleep?", guard=guard)
    assert reply.result.claims == [] and reply.result.rejected[0].reasons == (REASON,)
    repair = json.loads(llm.requests[2]["messages"][-1]["content"])
    assert repair["rejected_claims"][0]["reasons"] == [REASON]
    step = next(s for s in reply.result.trace if s["type"] == "guard")
    assert step["flagged"] == [advice]


def test_a_sound_answer_passes_the_guard_and_only_shown_text_is_checked(frame):
    sound = "Your time asleep held steady."
    llm = ScriptedLLM([DESCRIBE_SLEEP, sleep_answer(sound)])
    guard = FakeGuard("caffeine")
    reply = ask(llm, FixedRouter(("sleep",), sleep=1.0), frame, "How is my sleep?", guard=guard)
    assert [c.text for c in reply.result.claims] == [sound]
    assert guard.seen == [[sound, "Here is what I found."]]  # the claim, then the summary


def test_a_summary_that_advises_is_replaced_by_a_verified_claim(frame):
    sound = "Your time asleep held steady."
    advising = "Try going to bed earlier."
    llm = ScriptedLLM(
        [DESCRIBE_SLEEP, sleep_answer(sound, advising), sleep_answer(sound, advising)]
    )
    reply = ask(
        llm,
        FixedRouter(("sleep",), sleep=1.0),
        frame,
        "How is my sleep?",
        guard=FakeGuard("Try"),
    )
    assert reply.result.summary == sound


def test_when_the_guard_is_down_the_word_checks_alone_apply(frame):
    sound = "Your time asleep held steady."
    llm = ScriptedLLM([DESCRIBE_SLEEP, sleep_answer(sound)])
    guard = FakeGuard(fail=True)
    reply = ask(llm, FixedRouter(("sleep",), sleep=1.0), frame, "How is my sleep?", guard=guard)
    assert len(reply.result.claims) == 1
    step = next(s for s in reply.result.trace if s["type"] == "guard")
    assert "took too long" in step["error"]


def test_without_a_typesafe_key_there_is_no_guard():
    from app.agent.ask import default_guard
    from app.agent.guard import JevGuard

    assert default_guard(Settings(typesafe_api_key=None)) is None
    assert isinstance(default_guard(Settings(typesafe_api_key="key")), JevGuard)


CORRELATE_STEPS = ScriptedLLM.call(
    "correlate",
    "corr",
    driver="steps",
    target="sleep_minutes",
    start="2026-07-01",
    end="2026-08-29",
)


def claims_from(*specs):
    """A submission whose claims cite the latest evidence of the named tools."""

    def turn(messages):
        claims = []
        for tool, text, metric in specs:
            payload = next(
                json.loads(m["content"])
                for m in reversed(messages)
                if m["role"] == "tool" and f'"tool": "{tool}"' in m["content"]
            )
            claims.append(
                {
                    "text": text,
                    "kind": "no_change",
                    "evidence_ids": [payload["evidence_id"]],
                    "metric": metric,
                }
            )
        call = ToolCall("submit", SUBMIT, {"summary": "Here is what I found.", "claims": claims})
        return Completion(None, (call,), "scripted", Usage(), 0.0, 0.0)

    return turn


SLEEP_ONLY = claims_from(("describe", "Your time asleep held steady.", "sleep_minutes"))
WITH_STEPS = claims_from(
    ("describe", "Your time asleep held steady.", "sleep_minutes"),
    ("correlate", "Your steps did not clearly go with your time asleep.", "sleep_minutes"),
)
EXERCISE_QUESTION = "Does exercising more change how I sleep?"


def test_a_part_of_the_question_left_out_is_sent_back(frame):
    llm = ScriptedLLM([DESCRIBE_SLEEP, SLEEP_ONLY, CORRELATE_STEPS, WITH_STEPS])
    router = FixedRouter(("sleep", "activity"), sleep=0.8, activity=0.2)
    reply = ask(llm, router, frame, EXERCISE_QUESTION)
    repair = json.loads(llm.requests[2]["messages"][-1]["content"])
    assert repair["uncovered"] == ["activity"]
    assert "one of your own metrics" in repair["instruction"]  # a claim the ownership rule allows
    assert len(reply.result.claims) == 2 and reply.result.uncovered == []
    assert reply.result.notes == []


def test_a_part_still_left_out_is_said_in_a_fixed_note(frame):
    llm = ScriptedLLM([DESCRIBE_SLEEP, SLEEP_ONLY, SLEEP_ONLY])
    router = FixedRouter(("sleep", "activity"), sleep=0.8, activity=0.2)
    reply = ask(llm, router, frame, EXERCISE_QUESTION)
    assert reply.result.uncovered == ["activity"]
    assert reply.result.notes == []  # the note was wrong every time it was seen


def test_a_needed_expert_without_data_is_said_not_asked_for(frame):
    llm = ScriptedLLM([DESCRIBE_SLEEP, SLEEP_ONLY])
    router = FixedRouter(("sleep", "nutrition"), sleep=0.8, nutrition=0.2)
    reply = ask(llm, router, frame, "Does eating late change how I sleep?")
    assert reply.result.uncovered == [] and len(reply.result.claims) == 1
    assert reply.result.notes == ["There is no nutrition data yet, so it is left out here."]


def test_a_coverage_check_does_not_count_as_covering_a_topic():
    from datetime import date

    from app.agent.experts import coverage_check
    from app.agent.verifier import Claim
    from app.analysis import tools
    from app.analysis.evidence import Window

    data = generate(date(2026, 7, 1), 60, seed=5).frame
    covered = tools.coverage(data, Window(start=date(2026, 7, 1), end=date(2026, 8, 29)))
    claim = Claim(text="Wear was complete.", kind="data_quality", evidence_ids=[covered.id])
    assert coverage_check(["activity"], {covered.id: covered})([claim]) == ["activity"]


def test_memory_is_chosen_for_the_metrics_the_question_is_routed_to(frame):
    from datetime import UTC, datetime

    from app.agent.context import MemoryItem

    now = datetime(2026, 9, 1, tzinfo=UTC)
    sleep = MemoryItem(
        "finding", "f-sleep", "Your time asleep went down.", ("sleep_minutes",), now, 0.5
    )
    hrv = MemoryItem("finding", "f-hrv", "Your HRV went down.", ("hrv_ms",), now, 0.5)
    llm = ScriptedLLM([empty_submission()])
    reply = ask(
        llm,
        FixedRouter(("sleep",), sleep=1.0),
        frame,
        "How is my sleep?",
        memory=[sleep, hrv],
        now=now,
    )
    assert reply.context.memory_used == ["f-sleep"]  # sleep reads activity, not recovery
    task = llm.requests[0]["messages"][1]["content"]
    assert "Your time asleep went down." in task and "Your HRV went down." not in task
