""" "Where did that advice come from?" is answered from the last answer, never from memory.

Without a place in the reading it was sent back as unplaced and retried as a memory recall, and
the reply was about saved memory (the Fitbit replay's control P8, 2026-11-22).
"""

from datetime import date
from types import SimpleNamespace

import pytest
from test_clauses import said

from app.agent.ask import ask
from app.agent.clauses import SOURCE_AND_MORE, Said, reading_from
from app.agent.context import Turn, turns_from
from app.agent.llm import Budget, ScriptedLLM
from app.agent.provenance import NEITHER, NO_EARLIER, answer_source
from app.agent.requests import Ambiguous, Request
from app.agent.router import KeywordRouter

TODAY = date(2026, 11, 19)
PLANK = {"title": "Plank", "source": "free-exercise-db", "url": "https://example.org/plank"}
ASKED = "Where did that advice come from?"


def guidance_turn():
    return Turn("How do I do a plank?", "Hold a straight line on your forearms.", sources=(PLANK,))


def data_turn():
    state = {
        "data": [
            {
                "metrics": ["steps"],
                "operation": "sum",
                "windows": [{"start": "2026-11-09", "end": "2026-11-15"}],
            }
        ]
    }
    claim = {"text": "Total steps: 61,000", "evidence_ids": ["abc123"]}
    return Turn("Steps last week?", "Total steps: 61,000.", claims=(claim,), request_state=state)


# ---- what the reply says ----


def test_a_guidance_answer_names_its_public_source_and_links_it():
    reply, links = answer_source([guidance_turn()], TODAY)
    assert "Plank (free-exercise-db)" in reply and "not from your data" in reply
    assert links == [PLANK]


def test_a_data_answer_names_the_records_and_days_it_was_computed_from():
    reply, links = answer_source([data_turn()], TODAY)
    assert "your own records" in reply and "steps" in reply.casefold()
    assert "Nov 9" in reply and "Nov 15" in reply and links == []


def test_an_answer_with_neither_says_so_rather_than_inventing_one():
    reply, links = answer_source([Turn("Thanks!", "You're welcome.")], TODAY)
    assert reply == NEITHER and links == []


def test_with_no_earlier_answer_there_is_nothing_to_source():
    assert answer_source([], TODAY) == (NO_EARLIER, [])


def test_only_the_last_answer_counts():
    reply, links = answer_source([guidance_turn(), data_turn()], TODAY)
    assert "your own records" in reply and links == []


def test_a_stored_message_keeps_its_sources_in_the_history():
    question = SimpleNamespace(role="user", text="How do I do a plank?")
    answer = SimpleNamespace(
        role="assistant", text="Hold it.", claims=[], answered_by="general", refused=False,
        sources=[PLANK],
    )  # fmt: skip
    (turn,) = turns_from([question, answer])
    assert turn.sources == (PLANK,)


# ---- how it is read ----


def test_a_source_question_is_its_own_kind():
    reading = reading_from(Said.model_validate(said({"type": "source", "said": ASKED})), ASKED)
    assert reading.kind == "source"


def test_a_source_question_beside_another_request_is_asked_about():
    words = f"{ASKED} And my steps on Nov 3?"
    clauses = (
        {"type": "source", "said": ASKED},
        {
            "type": "data",
            "said": "And my steps on Nov 3?",
            "metrics": ["steps"],
            "operation": "value",
            "periods": [{"kind": "dates", "start": "2026-11-03", "end": "2026-11-03"}],
        },
    )
    with pytest.raises(Ambiguous, match=SOURCE_AND_MORE):
        reading_from(Said.model_validate(said(*clauses)), words)


# ---- the whole answer ----


@pytest.mark.parametrize("turn, has_links", [(guidance_turn(), True), (data_turn(), False)])
def test_the_answer_comes_from_the_last_answer_and_reads_no_data(turn, has_links):
    import pandas as pd

    frame = pd.DataFrame({"steps": [1.0]}, index=pd.date_range("2026-11-01", periods=1))
    answer = ask(
        ScriptedLLM([]),
        KeywordRouter(),
        frame,
        ASKED,
        history=[turn],
        today=TODAY,
        request_bundle=(Request(kind="source"), {}, Budget()),
    )
    expected, links = answer_source([turn], TODAY)
    assert answer.result.summary == expected
    assert answer.result.sources == links and bool(links) is has_links
    assert not answer.result.evidence  # nothing new is read for it
