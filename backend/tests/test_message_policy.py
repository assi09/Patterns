"""What a message says about itself survives composing it with a repeat of an earlier answer.

"Repeat that all-measure comparison" beside a status question makes the repeated look lead the
answer. The repeat is resolved from a reading of its own clause alone, so the message's own
flags (a medical question, a request to invent figures or to join sources, "don't save this")
were lost whenever it led (the audit of 910da27, item 2 of pr-195-followup-issues.md).
"""

from datetime import date

import pytest
from test_bcdb0ff_review import FRAME, LOOK_STATE, STATUS, WORDS
from test_clauses import data, dates, redo, said

from app.agent.ask import MEDICAL_REFUSAL, NO_FABRICATION, ask
from app.agent.clauses import Said, reading_from
from app.agent.llm import Budget, ScriptedLLM
from app.agent.requests import resolve
from app.agent.router import KeywordRouter

TODAY = date(2026, 11, 21)
FLAGS = {
    "medical": {"medical": True, "medical_said": "is this a heart condition?"},
    "fabricate": {"fabricate": True},
    "mix_sources": {"mix_sources": True},
}


def composed(companion, **flags):
    words = " ".join([WORDS, companion["said"], flags.get("medical_said", "")]).strip()
    raw = said(redo(WORDS), companion) | flags
    reading = reading_from(Said.model_validate(raw), words, earlier=True)
    return words, resolve(reading, LOOK_STATE, TODAY)


@pytest.mark.parametrize("flag", sorted(FLAGS))
def test_a_flag_of_the_message_survives_when_the_repeat_leads(flag):
    _, request = composed(STATUS, **FLAGS[flag])
    assert request.kind == "investigate"  # the repeated look leads
    assert getattr(request, flag) is True


def test_dont_save_this_survives_when_the_repeat_leads():
    _, request = composed(STATUS, store_nothing=True)
    assert request.kind == "investigate" and request.memory == "deny"


@pytest.mark.parametrize("flag", sorted(FLAGS))
def test_a_flag_survives_when_the_current_request_leads(flag):
    """A repeated figure beside a new read: the new read leads, as before."""
    state = {
        "last": "data",
        "data": [
            {
                "metrics": ["steps"],
                "operation": "mean",
                "windows": [{"start": "2026-10-11", "end": "2026-10-24"}],
            }
        ],
        "answer": {"kind": "data", "parts": 1, "reads": 0},
    }
    new = data(
        "And sleep for Oct 1-7", ["sleep_minutes"], "mean", dates("2026-10-01", "2026-10-07")
    )
    words = " ".join(["Again.", new["said"], FLAGS[flag].get("medical_said", "")]).strip()
    raw = said(redo("Again."), new) | FLAGS[flag]
    request = resolve(reading_from(Said.model_validate(raw), words, earlier=True), state, TODAY)
    assert request.kind == "data" and getattr(request, flag) is True


def test_a_repeat_without_flags_has_none():
    """Only this message's flags: none comes from the earlier answer or the repeat."""
    _, request = composed(STATUS)
    assert not (request.medical or request.fabricate or request.mix_sources)
    assert request.memory == "unspecified"


@pytest.mark.parametrize(
    "flag, reply", [("medical", MEDICAL_REFUSAL), ("fabricate", NO_FABRICATION)]
)
def test_the_answer_is_the_fixed_reply_not_the_repeated_look(flag, reply):
    words, request = composed(STATUS, **FLAGS[flag])
    answer = ask(
        ScriptedLLM([]),
        KeywordRouter(),
        FRAME,
        words,
        today=TODAY,
        request_bundle=(request, {}, Budget()),
    )
    assert answer.result.summary == reply
    assert not answer.result.evidence  # no data was read for it
