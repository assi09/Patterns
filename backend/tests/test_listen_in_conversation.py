# ruff: noqa: F811 (pytest fixtures are imported, then named as arguments)
"""Something said about themselves in conversation is listened to; a readback never is.

The memory evaluation's P7 on 2026-11-23: "I don't work night shifts anymore, I'm on day shifts
now." got a friendly reply and no card, and the night-shift fact stayed. The listener hears it
right (a replacement of the kept fact), but it was never called: every message the router sent
to conversation counted as read-only, a proxy for readbacks ("remind me what I said") that also
caught every statement, so "heard now too" could not run for one. The reader's own signals say
which is which: a memory recall is a readback, `told` is something said about them.
"""

from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select
from test_action_api import setup, sign_in  # noqa: F401 (the fixture)
from test_broad_questions import Router
from test_clauses import said
from test_memory_listener import record
from test_readback import says

from app.agent.llm import ScriptedLLM
from app.agent.router import CONVERSATION
from app.api import chat
from app.db import memory
from app.db.models import MemoryFact, User
from app.db.session import session_scope

CHANGE = "I don't work night shifts anymore, I'm on day shifts now."


def conversation_router():
    """The router as it scored P7: about the conversation, so the route is "conversation"."""
    router = Router("chat")
    router.result = replace(
        router.result,
        probabilities=dict.fromkeys(router.result.probabilities, 0.0) | {CONVERSATION: 0.95},
    )
    return router


def chatting(setup, *turns):
    """Signed in, a night-shift fact kept, and every message routed to conversation."""
    client, engine, agent = setup
    headers = sign_in(setup)
    with session_scope(engine) as db:
        user = db.scalar(select(User).where(User.email == "example@example.com")).id
        now = datetime.now(UTC)
        old = memory.propose_fact(
            db, user, "routine", "They work night shifts.", explicit=True, now=now
        )
        memory.decide_fact(db, user, old.id, True, now)
    chatty = replace(agent, router=conversation_router())
    client.app.dependency_overrides[chat.get_agent] = lambda: chatty
    chatty.llm.turns = list(turns)
    return client, engine, headers, user, chatty


def facts(engine, user):
    with session_scope(engine) as db:
        rows = db.scalars(select(MemoryFact).where(MemoryFact.user_id == user)).all()
        return sorted((f.text, f.status) for f in rows)


def test_a_change_said_in_conversation_becomes_a_replacement_card(setup):
    item = {"kind": "routine", "text": "They work day shifts.", "replaces": 1}
    client, engine, headers, user, agent = chatting(
        setup, says("Got it, day shifts now."), record(item)
    )
    agent.llm.request_turns = [
        ScriptedLLM.call(
            "read_request",
            **said({"type": "other", "said": CHANGE, "about_them": True, "message": "about_them"}),
        )
    ]
    reply = client.post("/chat", headers=headers, json={"text": CHANGE}).json()[-1]
    assert "day shifts" in reply["text"]
    assert facts(engine, user) == [
        ("They work day shifts.", "proposed"),  # a card, kept only on a tap
        ("They work night shifts.", "approved"),  # nothing changes without it
    ]


def test_a_readback_in_conversation_never_becomes_a_card(setup):
    """The v5 audit: "remind me what I said" became a preference card."""
    words = "Remind me what I said about my shifts."
    item = {"kind": "routine", "text": "They work night shifts."}
    client, engine, headers, user, agent = chatting(
        setup, says("You said you work night shifts."), record(item)
    )
    recall = {"type": "memory", "said": words, "action": "recall", "recall": "this_chat"}
    agent.llm.request_turns = [ScriptedLLM.call("read_request", **said(recall))]
    client.post("/chat", headers=headers, json={"text": words})
    assert facts(engine, user) == [("They work night shifts.", "approved")]


def test_a_question_that_tells_nothing_about_them_is_not_listened_to(setup):
    words = "Who made you, by the way?"
    item = {"kind": "routine", "text": "They are curious about the app."}
    client, engine, headers, user, agent = chatting(
        setup, says("A small team built me."), record(item)
    )
    other = {"type": "other", "said": words, "about_them": False, "message": "small_talk"}
    agent.llm.request_turns = [ScriptedLLM.call("read_request", **said(other))]
    client.post("/chat", headers=headers, json={"text": words})
    assert facts(engine, user) == [("They work night shifts.", "approved")]
    assert not any("record" in str(r.get("tools")) for r in agent.llm.requests)  # never asked
