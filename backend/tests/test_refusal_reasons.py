"""A refusal says the right reason (the audit of 2026-11-18): a coworker's sleep is an access limit,
not a medical question, and "does that mean it causes it?" after a link is answered, not refused
as off topic."""

import pytest
from test_broad_questions import END, Router, planted

from app.agent.ask import ASSOCIATION_REPLY, ask
from app.agent.context import Turn
from app.agent.limits import other_person
from app.agent.llm import ScriptedLLM


@pytest.mark.parametrize(
    "question, who",
    [
        ("How did my coworker sleep yesterday?", "coworker"),
        ("How many steps did my colleague take?", "colleague"),
        ("How many steps did my neighbour take?", "neighbour"),
        ("What is my coach's resting heart rate?", "coach"),
        ("How did my wife sleep?", "wife"),
    ],
)
def test_someone_else_s_data_is_an_access_limit(question, who):
    assert other_person(question) == who


@pytest.mark.parametrize(
    "question",
    [
        # The audit's counterexample: it must still be answered.
        "My coworker visited yesterday. How many steps did I take yesterday?",
        "My sister visited, is my sleep worse?",
        "Did my deep sleep go up?",
        "How did my average sleep change?",
        "Has my recovery improved?",
    ],
)
def test_the_person_s_own_data_is_not_someone_else_s(question):
    assert other_person(question) is None


def test_a_coworker_s_sleep_gets_the_access_reply_without_a_model():
    llm = ScriptedLLM([])
    reply = ask(llm, Router("day"), planted(), "How did my coworker sleep yesterday?", today=END)
    assert "only see your own" in reply.result.summary and llm.requests == []
    assert "medical" not in reply.result.summary.lower()


LINK = Turn(
    "Does more time asleep go with higher HRV?",
    "Yes, longer nights went with higher HRV.",
    claims=({"text": "Longer nights went with higher HRV.", "kind": "correlation"},),
    answered_by="recovery",
)


@pytest.mark.parametrize(
    "question",
    ["Can you tell me it definitely causes it?", "Does that mean the extra walking caused it?"],
)
def test_a_causality_follow_up_gets_the_association_answer(question):
    llm = ScriptedLLM([])
    reply = ask(llm, Router("world"), planted(), question, today=END, history=[LINK])
    assert reply.result.summary == ASSOCIATION_REPLY and llm.requests == []


def test_a_general_question_about_causes_is_not_caught():
    """No link was just shown, or the question is not about it: left to the usual path."""
    from app.agent.ask import CAUSE_FOLLOW_UP

    assert not CAUSE_FOLLOW_UP.search("What causes a low HRV?")
