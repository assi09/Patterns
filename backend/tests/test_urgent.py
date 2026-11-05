"""Emergencies get a fixed reply from code, whatever the router says."""

from datetime import date

import pytest

from app.agent.agent import SUBMIT, answer
from app.agent.ask import URGENT_BODY_REPLY, URGENT_MIND_REPLY, ask
from app.agent.llm import ScriptedLLM
from app.agent.router import EXPERT_LABELS, LABELS, Classification
from app.agent.verifier import MEDICAL
from app.synthetic import generate

FRAME = generate(date(2026, 7, 1), 60, seed=4).frame


class Sleep:
    def classify(self, question, earlier=()):
        return Classification(
            dict.fromkeys(LABELS, 0.0) | {"sleep": 0.9},
            dict.fromkeys(EXPERT_LABELS, 0.0),
            source="test",
        )


def reply(question: str):
    llm = ScriptedLLM([ScriptedLLM.say("x")] * 4)
    return ask(llm, Sleep(), FRAME, question), llm


@pytest.mark.parametrize(
    "question",
    [
        "My chest hurts when I run, what is it?",
        "I have chest pain since this morning",
        "pain in my chest and my arm",
        "I can't breathe properly",
        "I fainted at the gym",
        "my face is drooping",
    ],
)
def test_a_body_emergency_gets_the_fixed_reply_and_no_model(question):
    answer_, llm = reply(question)
    assert answer_.result.summary == URGENT_BODY_REPLY
    assert answer_.result.stop_reason == "urgent" and llm.requests == []


@pytest.mark.parametrize(
    "question", ["I want to die", "I've been thinking about suicide", "I keep hurting myself"]
)
def test_thoughts_of_self_harm_get_their_own_reply(question):
    assert reply(question)[0].result.summary == URGENT_MIND_REPLY


@pytest.mark.parametrize(
    "question",
    [
        "How is my chest workout affecting recovery?",
        "How did I sleep last night?",
        "I was dying after leg day",
        "Did my breathing rate change?",
    ],
)
def test_ordinary_questions_are_not_taken_for_emergencies(question):
    assert reply(question)[0].result.stop_reason != "urgent"


def test_an_urgent_turn_is_kept_out_of_memory_like_a_refusal():
    assert reply("I have chest pain")[0].route.action == "refuse"


def test_the_replies_name_no_condition_or_treatment():
    assert not MEDICAL.search(URGENT_BODY_REPLY + URGENT_MIND_REPLY)


def test_a_model_that_replies_in_text_twice_is_still_brought_to_submit():
    llm = ScriptedLLM(
        [
            ScriptedLLM.say("Here is my answer."),
            ScriptedLLM.say("As I said."),
            ScriptedLLM.call(SUBMIT, summary="Nothing stood out.", claims=[]),
        ]
    )
    result = answer(llm, FRAME, "Anything?")
    assert result.stop_reason == "submitted"
    assert "not shown to the person" in str(llm.requests[1]["messages"][-1])
