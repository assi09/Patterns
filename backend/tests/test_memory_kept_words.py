# ruff: noqa: F811 (pytest fixtures are imported, then named as arguments)
""" "I already keep that in mind" only when the kept fact says it, in these words.

The audit of 910da27 (memory_replace-01/t1): "after dinner now, rather than before breakfast"
was answered "I already keep that in mind" while only the old preference was kept: the listener
took the new words for the kept ones, and that judgment alone was the reply. Now a kept fact in
other words, on an explicit "remember", is a replacement card; a true duplicate is still kept.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from test_action_api import setup, sign_in  # noqa: F401 (the fixture)
from test_memory_listener import (  # noqa: F401 (the fixtures)
    NOW,
    TODAY,
    conversation_with,
    engine,
    hear,
    inbox,
    person,
    record,
)

from app.agent.llm import ScriptedLLM
from app.api import chat as api
from app.db import memory
from app.db.models import MemoryFact, User
from app.db.session import session_scope

OLD = "Walks before breakfast"
NEW = "Walks after dinner"


def kept(engine, person, text=OLD) -> str:
    fact_id = hear(engine, person, text, kind="preference", explicit=True)[0]
    with session_scope(engine) as db:
        memory.decide_fact(db, person, fact_id, True, NOW)
    return fact_id


def facts(engine, person) -> list[tuple[str, str, object]]:
    with session_scope(engine) as db:
        rows = db.scalars(select(MemoryFact).where(MemoryFact.user_id == person)).all()
        return sorted((f.text, f.status, f.replaces_id) for f in rows)


# ---- what is recorded ----


def test_an_edit_the_listener_took_for_the_kept_fact_is_a_replacement_card(engine, person):
    old = kept(engine, person)
    new = hear(
        engine, person, NEW, kind="preference", same_as=old, explicit=True, replace_reworded=True
    )
    assert new[0] != old and new[1] == "proposed"
    assert facts(engine, person) == [(NEW, "proposed", old), (OLD, "approved", None)]


def test_the_same_words_again_stay_the_kept_fact(engine, person):
    old = kept(engine, person)
    again = hear(
        engine, person, "walks before  BREAKFAST", kind="preference", same_as=old,
        explicit=True, replace_reworded=True,
    )  # fmt: skip
    assert again[:2] == (old, "approved")
    assert facts(engine, person) == [(OLD, "approved", None)]


def test_without_an_explicit_request_other_words_are_heard_as_before(engine, person):
    """Only "remember that …" offers a replacement; listening in the background is unchanged."""
    old = kept(engine, person)
    assert hear(engine, person, NEW, kind="preference", same_as=old)[:2] == (old, "approved")


def test_a_declined_fact_is_never_offered_again_in_other_words(engine, person):
    old = hear(engine, person, OLD, kind="preference", explicit=True)[0]
    with session_scope(engine) as db:
        memory.decide_fact(db, person, old, False, NOW)
    assert hear(engine, person, NEW, kind="preference", same_as=old, replace_reworded=True) is None


# ---- what the reply says ----


def listened(engine, person, text, item, asked=True):
    _, message = conversation_with(engine, person)
    parts = api.AgentParts(ScriptedLLM([record(item)]), None, None)
    sessions = lambda: session_scope(engine)  # noqa: E731
    return api.listen_to(sessions, parts, person, message, text, TODAY, NOW, asked=asked)


def test_remembering_an_edit_puts_it_on_a_card(engine, person):
    kept(engine, person)
    words = "Remember: I walk after dinner now, rather than before breakfast."
    statuses = listened(engine, person, words, {"kind": "preference", "text": NEW, "same_as": 1})
    assert statuses == ["proposed"]
    assert "Tap Keep on the card" in api.noted_reply(statuses)
    assert inbox(engine) == 2  # the first card, then the replacement


def test_remembering_a_true_duplicate_says_it_is_kept(engine, person):
    kept(engine, person)
    words = "Remember that I walk before breakfast."
    statuses = listened(engine, person, words, {"kind": "preference", "text": OLD, "same_as": 1})
    assert statuses == ["approved"]
    assert api.noted_reply(statuses) == api.ALREADY_KEPT


def test_other_words_matched_without_a_card_are_never_said_to_be_kept(engine, person):
    kept(engine, person)
    item = {"kind": "preference", "text": NEW, "same_as": 1}
    statuses = listened(
        engine, person, "I walk after dinner now, not before breakfast.", item, asked=False
    )
    assert statuses == ["approved_reworded"]
    reply = api.noted_reply(statuses)
    assert reply == api.KEPT_REWORDED and "already keep that" not in reply


# ---- through the chat ----


def remember(client, headers, agent, words, item):
    agent.llm.request_turns = [
        ScriptedLLM.call(
            "read_request",
            subject="self",
            clauses=[{"type": "memory", "said": words, "action": "remember"}],
            store_nothing=False,
            clarification="",
        )
    ]
    agent.llm.turns = [record(item)]
    response = client.post("/chat", headers=headers, json={"text": words})
    assert response.status_code == 200, response.text
    return response.json()[-1]["text"]


def signed_in_with_a_kept_walk(setup):  # noqa: F811
    client, engine, agent = setup
    headers = sign_in(setup)
    with session_scope(engine) as db:
        user = db.scalar(select(User).where(User.email == "example@example.com")).id
    now = datetime.now(UTC)
    with session_scope(engine) as db:
        old = memory.propose_fact(db, user, "preference", OLD, explicit=True, now=now).id
    with session_scope(engine) as db:
        memory.decide_fact(db, user, old, True, now)
    return client, engine, agent, headers, user


def test_an_edit_through_the_chat_is_a_card_not_already_kept(setup):  # noqa: F811
    client, engine, agent, headers, user = signed_in_with_a_kept_walk(setup)
    words = "Remember: I walk after dinner now, rather than before breakfast."
    text = remember(
        client, headers, agent, words, {"kind": "preference", "text": NEW, "same_as": 1}
    )
    assert "already keep" not in text and "Tap Keep on the card" in text
    assert facts(engine, user)[0][:2] == (NEW, "proposed")  # waiting for a tap
    assert facts(engine, user)[1][:2] == (OLD, "approved")  # nothing changed without it


def test_a_duplicate_through_the_chat_is_already_kept(setup):  # noqa: F811
    client, engine, agent, headers, user = signed_in_with_a_kept_walk(setup)
    words = "Remember that I walk before breakfast."
    text = remember(
        client, headers, agent, words, {"kind": "preference", "text": OLD, "same_as": 1}
    )
    assert api.ALREADY_KEPT in text
    assert [f[:2] for f in facts(engine, user)] == [(OLD, "approved")]
