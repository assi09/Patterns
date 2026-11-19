"""Forgetting something kept: a card the person taps, never a deletion by the agent alone.

"Please forget my old running goal" had no path that deleted anything (Codex's review,
2026-11-19). Each step is checked through the store or the API, not only by the reply's words.
Made-up facts only.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from test_chat_api import agent, ask, client, engine, listening, signed_in  # noqa: F401

from app.agent.llm import ScriptedLLM
from app.api import chat
from app.db import memory
from app.db.models import MemoryFact, Notification, User
from app.db.session import session_scope

NOW = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)


def keep(session, user_id, text, kind="goal") -> MemoryFact:
    fact = memory.propose_fact(session, user_id, kind, text, now=NOW)
    return memory.decide_fact(session, user_id, fact.id, approve=True, now=NOW)


@pytest.fixture
def person(engine):  # noqa: F811
    with session_scope(engine) as session:
        user = User(email="forget@example.com", status="approved")
        session.add(user)
        session.flush()
        return user.id


def rows(engine, user_id):  # noqa: F811
    with session_scope(engine) as session:
        return {
            (f.text, f.status, f.forgets_id is not None)
            for f in session.scalars(select(MemoryFact).where(MemoryFact.user_id == user_id))
        }


# ---- the store ----


def test_tapping_forget_deletes_the_kept_fact_and_its_card(engine, person):  # noqa: F811
    with session_scope(engine) as session:
        goal = keep(session, person, "Wants to run a 10k")
        card = memory.propose_forget(session, person, goal.id, now=NOW)
        assert card.forgets_id == goal.id and card.status == "proposed"
        assert memory.kept_facts(session, person)[0].id == goal.id  # still kept until the tap
        memory.decide_fact(session, person, card.id, approve=True, now=NOW)
    assert rows(engine, person) == set()


def test_keeping_it_leaves_the_fact_and_drops_only_the_question(engine, person):  # noqa: F811
    with session_scope(engine) as session:
        goal = keep(session, person, "Wants to run a 10k")
        card = memory.propose_forget(session, person, goal.id, now=NOW)
        memory.decide_fact(session, person, card.id, approve=False, now=NOW)
    assert rows(engine, person) == {("Wants to run a 10k", "approved", False)}


def test_only_something_kept_can_be_forgotten(engine, person):  # noqa: F811
    with session_scope(engine) as session:
        waiting = memory.propose_fact(session, person, "goal", "Wants to swim", now=NOW)
        with pytest.raises(memory.MemoryRejected):
            memory.propose_forget(session, person, waiting.id, now=NOW)
        with pytest.raises(memory.MemoryRejected):
            memory.propose_forget(session, person, uuid.uuid4(), now=NOW)


def test_asking_twice_gives_the_same_card(engine, person):  # noqa: F811
    with session_scope(engine) as session:
        goal = keep(session, person, "Wants to run a 10k")
        first = memory.propose_forget(session, person, goal.id, now=NOW)
        assert memory.propose_forget(session, person, goal.id, now=NOW).id == first.id


def test_a_forget_card_is_never_a_fact_the_listener_or_recall_sees(engine, person):  # noqa: F811
    with session_scope(engine) as session:
        goal = keep(session, person, "Wants to run a 10k")
        memory.propose_forget(session, person, goal.id, now=NOW)
        held = memory.held_facts(session, person)
        assert [f.id for f in held] == [goal.id]
        profile = memory.profile(session, person, NOW.date(), NOW)
        assert profile.lines == ("goal: Wants to run a 10k",)  # kept until the tap


def test_the_inbox_asks_and_is_read_once_decided(engine, person):  # noqa: F811
    with session_scope(engine) as session:
        goal = keep(session, person, "Wants to run a 10k")
        card = memory.propose_forget(session, person, goal.id, now=NOW)
        note = session.scalar(select(Notification).where(Notification.fact_id == card.id))
        assert note.title == "Forget this?" and note.body == "Wants to run a 10k"
        memory.decide_fact(session, person, card.id, approve=True, now=NOW)
        unread = session.scalars(
            select(Notification).where(
                Notification.user_id == person, Notification.read_at.is_(None)
            )
        )
        assert not list(unread)


def test_someone_else_s_fact_cannot_be_forgotten(engine, person):  # noqa: F811
    with session_scope(engine) as session:
        other = User(email="other@example.com", status="approved")
        session.add(other)
        session.flush()
        theirs = keep(session, other.id, "Wants to run a marathon")
        with pytest.raises(memory.MemoryRejected):
            memory.propose_forget(session, person, theirs.id, now=NOW)


# ---- through the chat and the memory page ----


def reader_says_forget(llm):
    llm.request_turns = [
        ScriptedLLM.call("read_request", kind="memory", memory_action="forget")
    ] * 2


def signed_in_with(client, engine, text):  # noqa: F811
    headers = signed_in(client, engine)
    with session_scope(engine) as session:
        user = session.scalar(select(User).where(User.email == "person@example.com"))
        keep(session, user.id, text)
    return headers


def test_forget_in_the_chat_raises_a_card_and_the_tap_deletes(client, engine, agent):  # noqa: F811
    headers = signed_in_with(client, engine, "Wants to run a 10k")
    parts = listening(agent)
    client.app.dependency_overrides[chat.get_agent] = lambda: parts
    reader_says_forget(agent.llm)
    agent.llm.turns += [ScriptedLLM.say("none"), ScriptedLLM.call("pick_kept", item=1)]
    reply = ask(client, headers, "Please forget my old running goal.").json()[-1]
    assert "tap Forget" in reply["text"] and "Wants to run a 10k" in reply["text"]
    page = client.get("/memory", headers=headers).json()
    [card] = page["waiting"]
    assert card["action"] == "forget" and [f["text"] for f in page["kept"]] == [card["text"]]
    tapped = client.post(
        f"/memory/facts/{card['id']}/decision", json={"keep": True}, headers=headers
    )
    assert tapped.status_code == 200
    page = client.get("/memory", headers=headers).json()
    assert page["kept"] == [] and page["waiting"] == []


def test_an_unclear_forget_lists_what_is_kept_and_deletes_nothing(client, engine, agent):  # noqa: F811
    headers = signed_in_with(client, engine, "Wants to run a 10k")
    parts = listening(agent)
    client.app.dependency_overrides[chat.get_agent] = lambda: parts
    reader_says_forget(agent.llm)
    agent.llm.turns += [ScriptedLLM.say("none"), ScriptedLLM.call("pick_kept", item=0)]
    reply = ask(client, headers, "Forget that thing.").json()[-1]
    assert reply["text"].startswith(chat.FORGET_WHICH) and "Wants to run a 10k" in reply["text"]
    page = client.get("/memory", headers=headers).json()
    assert page["waiting"] == [] and len(page["kept"]) == 1


def test_forget_with_nothing_kept_says_so_without_a_model_call(client, engine, agent):  # noqa: F811
    headers = signed_in(client, engine)
    parts = listening(agent)
    client.app.dependency_overrides[chat.get_agent] = lambda: parts
    reader_says_forget(agent.llm)
    agent.llm.turns += [ScriptedLLM.say("none")]  # the listener only
    reply = ask(client, headers, "Please forget my old running goal.").json()[-1]
    assert reply["text"] == chat.NOTHING_KEPT and not agent.llm.turns
