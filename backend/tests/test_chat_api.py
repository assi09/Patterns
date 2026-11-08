import json
import time
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.agent.agent import SUBMIT
from app.agent.llm import Completion, ScriptedLLM, ToolCall, Usage
from app.agent.router import EXPERT_LABELS, LABELS, Classification
from app.api import auth, chat
from app.api.chat import AgentParts, answer_text
from app.api.main import create_app
from app.api.store import analyze, get_data
from app.auth.accounts import LoginThrottle
from app.config import settings
from app.db.models import ChatMessage, EvidenceRecord, User
from app.db.session import session_scope
from app.ingest.takeout import DailyData
from app.synthetic import generate

START = date(2026, 7, 1)
PASSWORD = "correct horse battery"


class FixedRouter:
    def __init__(self, **given: float):
        topic = dict.fromkeys(LABELS, 0.0) | given
        self.result = Classification(topic, dict.fromkeys(EXPERT_LABELS, 0.0), source="test")

    def classify(self, question: str, earlier=()) -> Classification:
        return self.result


def submission(summary: str, cost: float = 0.0, claims=()) -> Completion:
    call = ToolCall("submit", SUBMIT, {"summary": summary, "claims": list(claims)})
    return Completion(None, (call,), "scripted", Usage(), cost, 0.0)


def describe_then_claim(text: str, cost: float = 0.004, metric: str = "sleep_minutes"):
    """Runs `describe` on a metric (sleep unless told), then submits one claim citing it."""

    def submit(messages):
        payload = next(
            json.loads(m["content"])
            for m in reversed(messages)
            if m["role"] == "tool" and '"tool": "describe"' in m["content"]
        )
        claim = {
            "text": text,
            "kind": "no_change",
            "evidence_ids": [payload["evidence_id"]],
            "metric": metric,
        }
        return submission("Here is what I found.", cost, [claim])

    end = (START + timedelta(days=59)).isoformat()
    return [
        ScriptedLLM.call("describe", metric=metric, start=START.isoformat(), end=end),
        submit,
    ]


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


@pytest.fixture
def agent():
    return AgentParts(ScriptedLLM([]), FixedRouter(sleep=0.9), None)


@pytest.fixture
def client(engine, agent, monkeypatch) -> TestClient:
    monkeypatch.setattr(auth, "throttle", LoginThrottle())
    monkeypatch.setattr(chat, "_busy", set())
    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    data = analyze(DailyData(frame=generate(START, 60, seed=5).frame), datetime.now(UTC))
    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[get_data] = lambda: data
    app.dependency_overrides[chat.get_agent] = lambda: agent
    app.dependency_overrides[chat.get_sessions] = lambda: lambda: session_scope(engine)
    return TestClient(app)


def signed_in(client, engine, email: str = "person@example.com", approved: bool = True) -> dict:
    token = client.post("/auth/signup", json={"email": email, "password": PASSWORD}).json()["token"]
    if approved:
        with session_scope(engine) as session:
            session.scalar(select(User).where(User.email == email)).status = "approved"
    return {"Authorization": f"Bearer {token}"}


def ask(client, headers, text: str = "How did I sleep?", **options):
    return client.post("/chat", json={"text": text, **options}, headers=headers)


# Access


def test_the_chat_needs_an_approved_account(client, engine):
    assert client.get("/chat").status_code == 401
    pending = signed_in(client, engine, approved=False)
    assert client.get("/chat", headers=pending).json()["error"]["code"] == "not_approved"
    assert ask(client, pending).status_code == 403


def test_a_new_person_has_an_empty_chat(client, engine):
    assert client.get("/chat", headers=signed_in(client, engine)).json() == []


# Answering


def test_the_apps_own_scores_can_be_asked_about(client, engine):
    # The daily table holds no scores; the chat adds them, and strain belongs to activity.
    llm = ScriptedLLM(describe_then_claim("Your strain held steady.", metric="strain"))
    activity = AgentParts(llm, FixedRouter(activity=0.9), None)
    client.app.dependency_overrides[chat.get_agent] = lambda: activity
    response = ask(client, signed_in(client, engine), "How was my strain?")
    assert response.status_code == 200, response.text
    answer = response.json()[1]
    assert answer["answeredBy"] == "activity" and len(answer["evidenceIds"]) == 1


def test_a_question_is_answered_with_verified_claims_and_stored(client, engine, agent):
    agent.llm.turns.extend(describe_then_claim("Your time asleep held steady."))
    headers = signed_in(client, engine)

    response = ask(client, headers)
    assert response.status_code == 200, response.text
    question, answer = response.json()
    assert question["role"] == "user" and question["text"] == "How did I sleep?"
    assert answer["role"] == "assistant"
    # The summary is the answer; the claim backs it as evidence, not as repeated text.
    assert answer["text"] == "Here is what I found."
    assert answer["answeredBy"] == "sleep" and answer["routed"] is True
    assert len(answer["evidenceIds"]) == 1
    assert "refused" not in answer  # absent rather than false, like the mock

    assert client.get("/chat", headers=headers).json() == [question, answer]
    evidence = client.get(f"/evidence/{answer['evidenceIds'][0]}", headers=headers)
    assert evidence.status_code == 200 and evidence.json()["tool"] == "describe"
    with session_scope(engine) as session:
        assert session.scalar(select(ChatMessage.cost_usd).where(ChatMessage.role == "assistant"))
        assert session.scalar(select(EvidenceRecord.id)) == answer["evidenceIds"][0]


def test_picking_an_expert_is_not_routed(client, engine, agent):
    agent.llm.turns.append(submission("Nothing stood out."))
    answer = ask(client, signed_in(client, engine), expert="sleep", depth="deep").json()[1]
    assert answer["answeredBy"] == "sleep" and answer["routed"] is False


def test_an_out_of_scope_question_is_refused_at_no_cost(client, engine, agent):
    agent.router.result = Classification(
        dict.fromkeys(LABELS, 0.0) | {"out_of_scope": 0.95},
        dict.fromkeys(EXPERT_LABELS, 0.0),
        source="test",
    )
    answer = ask(client, signed_in(client, engine), "Do I have apnea?").json()[1]
    assert answer["refused"] is True
    assert "answeredBy" not in answer and agent.llm.requests == []


def test_earlier_turns_are_given_to_the_next_answer(client, engine, agent):
    headers = signed_in(client, engine)
    agent.llm.turns.append(submission("Nothing stood out."))
    ask(client, headers, "How did I sleep last month?")
    agent.llm.turns.append(submission("Weekends looked the same."))
    ask(client, headers, "What about on weekends?")
    second_run = json.dumps(agent.llm.requests[-1]["messages"])
    assert "How did I sleep last month?" in second_run
    assert len(client.get("/chat", headers=headers).json()) == 4


def test_a_summary_reaches_the_next_answer_in_its_own_chat_and_no_other(client, engine, agent):
    headers = signed_in(client, engine)
    first = client.post("/conversations", headers=headers).json()["id"]
    for n in range(5):
        agent.llm.turns.append(submission("Nothing stood out."))
        ask(client, headers, f"Question {n}", conversationId=first)
    with session_scope(engine) as db:
        person = db.scalar(select(User)).id
    agent.llm.turns.append(ScriptedLLM.say("They are preparing for a marathon."))
    chat.update_summary(lambda: session_scope(engine), agent.llm, person, uuid.UUID(first))

    agent.llm.turns.append(submission("Nothing stood out."))
    ask(client, headers, "And now?", conversationId=first)
    assert "preparing for a marathon" in json.dumps(agent.llm.requests[-1]["messages"])

    other = client.post("/conversations", headers=headers).json()["id"]
    agent.llm.turns.append(submission("Nothing stood out."))
    ask(client, headers, "Something new", conversationId=other)
    assert "preparing for a marathon" not in json.dumps(agent.llm.requests[-1]["messages"])


def test_people_never_see_each_others_chat(client, engine, agent):
    first = signed_in(client, engine, "first@example.com")
    second = signed_in(client, engine, "second@example.com")
    agent.llm.turns.append(submission("Nothing stood out."))
    ask(client, first, "A question only I asked")
    assert client.get("/chat", headers=second).json() == []
    agent.llm.turns.append(submission("Nothing stood out."))
    ask(client, second)
    assert "A question only I asked" not in json.dumps(agent.llm.requests[-1]["messages"])


def listening(agent) -> AgentParts:
    return AgentParts(agent.llm, agent.router, None, background=True)


def wait_for(check, seconds: float = 5.0):
    """Polls for what a background job leaves behind."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if found := check():
            return found
        time.sleep(0.02)
    raise AssertionError("the background job left nothing")


def test_what_is_heard_becomes_a_card_only_when_asked_for(client, engine, agent):
    headers = signed_in(client, engine)
    parts = listening(agent)
    client.app.dependency_overrides[chat.get_agent] = lambda: parts
    heard = ScriptedLLM.call(
        "record_memories", memories=[{"kind": "routine", "text": "Works night shifts"}]
    )
    agent.llm.turns.append(heard)  # the reply itself needs no model
    reply = ask(client, headers, "Please remember that I work night shifts").json()[-1]
    assert "Keep" in reply["text"]

    def card():
        return client.get("/memory", headers=headers).json()["waiting"]

    [fact] = wait_for(card)
    assert fact["text"] == "Works night shifts" and fact["kind"] == "routine"
    inbox = client.get("/notifications", headers=headers).json()
    assert inbox["items"][0]["kind"] == "memory" and inbox["items"][0]["factId"] == fact["id"]

    kept = client.post(f"/memory/facts/{fact['id']}/decision", json={"keep": True}, headers=headers)
    assert kept.json()["status"] == "approved"
    assert client.get("/notifications", headers=headers).json()["unread"] == 0


def test_a_plain_question_costs_no_listening_call(client, engine, agent):
    headers = signed_in(client, engine)
    parts = listening(agent)
    client.app.dependency_overrides[chat.get_agent] = lambda: parts
    agent.llm.turns.extend(describe_then_claim("Your time asleep held steady."))
    ask(client, headers, "How did I sleep last month?")
    time.sleep(0.1)  # the job would have run by now
    assert not [r for r in agent.llm.requests if r["tools"] == ["record_memories"]]


def test_a_refused_message_is_not_listened_to(client, engine, agent):
    headers = signed_in(client, engine)
    parts = AgentParts(agent.llm, FixedRouter(out_of_scope=0.9), None, background=True)
    client.app.dependency_overrides[chat.get_agent] = lambda: parts
    ask(client, headers, "I think I have something wrong with me")
    assert agent.llm.requests == []


def test_a_failed_run_is_stored_as_a_plain_apology(client, engine, agent):
    # The script is empty, so the model call fails.
    question, answer = ask(client, signed_in(client, engine)).json()
    assert answer["text"] == chat.FAILED
    assert question["text"] == "How did I sleep?"


def test_the_answer_text_is_the_summary_then_the_notes():
    text = answer_text("Your sleep held steady.", ["A.", "B."], ["Note."])
    assert text == "Your sleep held steady.\n\nNote."
    # Without a summary, the claims are read out as one paragraph, capitalized.
    assert answer_text("", ["time asleep held steady.", "Bedtime too."], []) == (
        "Time asleep held steady. Bedtime too."
    )
    assert answer_text("", [], []) == chat.FAILED


def test_the_agent_gets_the_local_time_not_the_last_day_of_data(client, engine, agent):
    agent.llm.turns.append(submission("Nothing stood out."))
    ask(client, signed_in(client, engine))
    task = agent.llm.requests[0]["messages"][1]["content"]
    assert "\nIt is now " in task and "UTC" in task


def test_a_reply_to_a_logging_question_is_given_with_its_request(client, engine, agent):
    from app.agent.intent import Intent

    headers = signed_in(client, engine)
    # The agent asks for the time instead of preparing a draft.
    agent.router.result = Classification(
        dict.fromkeys(LABELS, 0.0) | {"nutrition": 0.95},
        dict.fromkeys(EXPERT_LABELS, 0.0),
        source="test",
        intent_probabilities={str(i): float(i == Intent.LOG) for i in Intent},
    )
    agent.llm.turns.append(submission("When did you eat it?"))
    ask(client, headers, "Log a snack: an apple, 95 kcal")
    # The reply alone is unclear; it continues the logging request.
    agent.router.result = Classification(
        dict.fromkeys(LABELS, 0.0) | {"nutrition": 0.95},
        dict.fromkeys(EXPERT_LABELS, 0.0),
        source="test",
        intent_probabilities={str(i): float(i == Intent.CLARIFY) for i in Intent},
    )
    agent.llm.turns.append(submission("Noted."))
    ask(client, headers, "at 10:30")
    task = agent.llm.requests[-1]["messages"][1]["content"]
    assert "Earlier request: Log a snack: an apple, 95 kcal" in task
    assert "You asked: When did you eat it?" in task
    assert "Their reply: at 10:30" in task
    # What is stored and shown stays the person's own words.
    assert client.get("/chat", headers=headers).json()[-2]["text"] == "at 10:30"


def _log_route(agent, intent):
    from app.agent.intent import Intent

    agent.router.result = Classification(
        dict.fromkeys(LABELS, 0.0) | {"activity": 0.95},
        dict.fromkeys(EXPERT_LABELS, 0.0),
        source="test",
        intent_probabilities={str(i): float(i == Intent(intent)) for i in Intent},
    )


def test_every_reply_in_a_logging_request_reaches_the_agent(client, engine, agent):
    headers = signed_in(client, engine)
    _log_route(agent, "log")
    agent.llm.turns.append(submission("What type of workout?"))
    ask(client, headers, "Log a workout, started at 3 pm for 1 hour 30 min")
    _log_route(agent, "clarify")
    agent.llm.turns.append(submission("What intensity was it?"))
    ask(client, headers, "Weightlifting")
    agent.llm.turns.append(submission("Noted."))
    ask(client, headers, "hard")
    task = agent.llm.requests[-1]["messages"][1]["content"]
    assert "Earlier request: Log a workout, started at 3 pm for 1 hour 30 min" in task
    assert "They added: Weightlifting" in task
    assert "You asked: What intensity was it?" in task
    assert "Their reply: hard" in task


def test_the_agent_is_told_the_persons_own_local_time(client, engine, agent):
    headers = signed_in(client, engine)
    assert (
        client.put("/me/timezone", headers=headers, json={"timezone": "Asia/Beirut"}).status_code
        == 204
    )
    agent.llm.turns.append(submission("Noted."))
    ask(client, headers, "How did I sleep?")
    assert "Asia/Beirut" in agent.llm.requests[-1]["messages"][1]["content"]


def test_a_reply_to_the_log_or_ask_question_continues_with_the_meal(client, engine, agent):
    from app.agent.intent import Intent

    headers = signed_in(client, engine)
    unclear = Classification(
        dict.fromkeys(LABELS, 0.0) | {"nutrition": 0.95},
        dict.fromkeys(EXPERT_LABELS, 0.0),
        source="test",
        intent_probabilities={str(i): float(i == Intent.CLARIFY) for i in Intent},
    )
    # Only saying what was eaten: the agent reacts and asks whether to log it, without tools.
    agent.router.result = unclear
    meal = "I ate chicken and rice: 50 g carbs, 40 g protein, 10 g fat"
    question = "Chicken and rice, a solid meal! Want me to log it, or look at your data?"
    agent.llm.turns.append(ScriptedLLM.say(question))
    _, asked = ask(client, headers, meal).json()
    assert asked["text"] == question
    assert agent.llm.requests[0]["tools"] == []
    # "yes log" alone is unclear too, but it answers that question: the meal comes with it, and
    # the logging tool is offered.
    agent.llm.turns.append(submission("Which meal was it?"))
    ask(client, headers, "yes log")
    request = agent.llm.requests[-1]
    task = request["messages"][1]["content"]
    assert f"Earlier request: {meal}" in task
    assert "Their reply: yes log" in task
    assert "propose_food_log" in json.dumps(request.get("tools", []))


def test_asking_what_was_said_during_a_logging_request_reads_the_chat(client, engine, agent):
    from app.agent.intent import Intent

    headers = signed_in(client, engine)
    agent.router.result = Classification(
        dict.fromkeys(LABELS, 0.0) | {"nutrition": 0.95},
        dict.fromkeys(EXPERT_LABELS, 0.0),
        source="test",
        intent_probabilities={str(i): float(i == Intent.CLARIFY) for i in Intent},
    )
    ask(client, headers, "I had a bowl of pasta")  # asks whether to log, without a model call
    agent.router.result = Classification(
        dict.fromkeys(LABELS, 0.0) | {"conversation": 0.9, "nutrition": 0.1},
        dict.fromkeys(EXPERT_LABELS, 0.0),
        source="test",
        intent_probabilities={str(i): float(i == Intent.CLARIFY) for i in Intent},
    )
    agent.llm.turns.append(ScriptedLLM.say("You said you had a bowl of pasta."))
    _, answer = ask(client, headers, "what was my previous message saying").json()
    assert answer["text"] == "You said you had a bowl of pasta."
    assert answer["answeredBy"] == "general"
    task = agent.llm.requests[-1]["messages"][1]["content"]
    assert "I had a bowl of pasta" in task and "Do you want me to log that" in task


# Attachments


def test_an_attached_metric_leads_and_an_unknown_one_is_refused(client, engine, agent):
    headers = signed_in(client, engine)
    agent.llm.turns.append(submission("Nothing stood out."))
    attachment = {"kind": "metric", "metric": "steps"}
    question, answer = ask(client, headers, "What about this?", attachment=attachment).json()
    assert question["attachment"] == attachment
    assert answer["answeredBy"] == "activity"
    bad = ask(client, headers, attachment={"kind": "metric", "metric": "made_up"})
    assert bad.status_code == 422


@pytest.mark.parametrize(
    "attachment", [{"kind": "finding"}, {"kind": "metric"}, {"kind": "other", "id": "x"}]
)
def test_incomplete_attachments_are_invalid(client, engine, attachment):
    response = ask(client, signed_in(client, engine), attachment=attachment)
    assert response.status_code == 422


def test_an_unknown_finding_is_not_found(client, engine):
    response = ask(client, signed_in(client, engine), attachment={"kind": "finding", "id": "f9"})
    assert response.status_code == 404


@pytest.mark.parametrize("text", ["", "x" * 2001])
def test_empty_or_huge_questions_are_invalid(client, engine, text):
    assert ask(client, signed_in(client, engine), text).status_code == 422


# Spending and waiting


def test_a_person_stops_at_their_daily_cap(client, engine, agent, monkeypatch):
    monkeypatch.setattr(settings, "chat_daily_cap_per_user_usd", 0.01)
    headers = signed_in(client, engine)
    agent.llm.turns.append(submission("Nothing stood out.", cost=0.012))
    assert ask(client, headers).status_code == 200
    refused = ask(client, headers)
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "daily_limit"
    # Someone else can still ask.
    agent.llm.turns.append(submission("Nothing stood out."))
    assert ask(client, signed_in(client, engine, "other@example.com")).status_code == 200


def test_the_app_stops_at_its_daily_total(client, engine, agent, monkeypatch):
    monkeypatch.setattr(settings, "chat_daily_cap_total_usd", 0.01)
    agent.llm.turns.append(submission("Nothing stood out.", cost=0.012))
    assert ask(client, signed_in(client, engine, "first@example.com")).status_code == 200
    refused = ask(client, signed_in(client, engine, "second@example.com"))
    assert refused.json()["error"]["code"] == "app_daily_limit"


def test_yesterdays_spending_does_not_count(client, engine, agent, monkeypatch):
    monkeypatch.setattr(settings, "chat_daily_cap_per_user_usd", 0.01)
    headers = signed_in(client, engine)
    agent.llm.turns.append(submission("Nothing stood out.", cost=0.012))
    ask(client, headers)
    with session_scope(engine) as session:
        for message in session.scalars(select(ChatMessage)):
            message.created_at -= timedelta(days=2)
    agent.llm.turns.append(submission("Nothing stood out."))
    assert ask(client, headers).status_code == 200


def test_a_slow_answer_is_stored_when_it_is_ready(client, engine, agent, monkeypatch):
    monkeypatch.setattr(settings, "chat_wait_s", 0.05)
    headers = signed_in(client, engine)

    def slow(messages):
        time.sleep(0.3)
        return submission("Nothing stood out.")

    agent.llm.turns.append(slow)
    response = ask(client, headers)
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "still_answering"
    busy = ask(client, headers)  # the first is still running
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "busy"

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(client.get("/chat", headers=headers).json()) < 2:
        time.sleep(0.05)
    messages = client.get("/chat", headers=headers).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["text"].startswith("Nothing stood out.")


# Conversations


def test_questions_go_to_their_conversation_and_are_named_by_the_first(client, engine, agent):
    headers = signed_in(client, engine)
    agent.llm.turns.append(submission("Nothing stood out."))
    first = ask(client, headers, "How did I sleep last month?").json()
    sleep_chat = first[0]["conversationId"]
    new = client.post("/conversations", headers=headers).json()
    assert new["title"] == "New chat" and new["messages"] == 0
    agent.llm.turns.append(submission("Steps held steady."))
    ask(client, headers, "  How   many steps\ndid I take? ", conversationId=new["id"])

    chats = client.get("/conversations", headers=headers).json()
    assert [c["title"] for c in chats] == [
        "How many steps did I take?",
        "How did I sleep last month?",
    ]
    assert [c["messages"] for c in chats] == [2, 2]
    # Each conversation shows only its own messages; the default is the latest used.
    mine = client.get("/chat", params={"conversation": sleep_chat}, headers=headers).json()
    assert [m["text"] for m in mine][0] == "How did I sleep last month?" and len(mine) == 2
    latest = client.get("/chat", headers=headers).json()
    assert latest[0]["conversationId"] == new["id"]  # the message keeps its own spacing
    # The steps chat's answer did not see the sleep chat's turns.
    assert "How did I sleep last month?" not in json.dumps(agent.llm.requests[-1]["messages"])


def test_a_long_first_question_makes_a_short_title(client, engine, agent):
    headers = signed_in(client, engine)
    agent.llm.turns.append(submission("Nothing stood out."))
    ask(client, headers, "Why " + "really " * 30 + "?")
    title = client.get("/conversations", headers=headers).json()[0]["title"]
    assert len(title) == 60 and title.endswith("…")


def test_conversations_can_be_renamed_and_deleted(client, engine, agent):
    headers = signed_in(client, engine)
    agent.llm.turns.append(submission("Nothing stood out."))
    chat_id = ask(client, headers).json()[0]["conversationId"]
    renamed = client.patch(f"/conversations/{chat_id}", json={"title": "Sleep"}, headers=headers)
    assert renamed.json()["title"] == "Sleep" and renamed.json()["messages"] == 2
    assert (
        client.patch(f"/conversations/{chat_id}", json={"title": ""}, headers=headers).status_code
        == 422
    )
    assert client.delete(f"/conversations/{chat_id}", headers=headers).status_code == 204
    assert client.get("/conversations", headers=headers).json() == []
    assert client.get("/chat", headers=headers).json() == []
    with session_scope(engine) as session:
        assert session.scalar(select(ChatMessage.id)) is None


def test_people_never_reach_each_others_conversations(client, engine, agent):
    first = signed_in(client, engine, "first@example.com")
    second = signed_in(client, engine, "second@example.com")
    agent.llm.turns.append(submission("Nothing stood out."))
    chat_id = ask(client, first).json()[0]["conversationId"]
    for response in (
        client.get("/chat", params={"conversation": chat_id}, headers=second),
        client.patch(f"/conversations/{chat_id}", json={"title": "Mine"}, headers=second),
        client.delete(f"/conversations/{chat_id}", headers=second),
        ask(client, second, conversationId=chat_id),
    ):
        assert response.status_code == 404, response.text
    assert client.get("/conversations", headers=second).json() == []
    assert len(client.get("/chat", params={"conversation": chat_id}, headers=first).json()) == 2


def test_only_an_idle_chats_episode_reaches_another_chat(client, engine, agent):
    from app.db import memory

    headers = signed_in(client, engine)
    agent.llm.turns.extend(describe_then_claim("Your time asleep held steady."))
    sleep_chat = ask(client, headers).json()[0]["conversationId"]
    other = client.post("/conversations", headers=headers).json()["id"]

    # Still in use: nothing from it crosses over.
    agent.llm.turns.append(submission("Nothing to add."))
    ask(client, headers, "How is my sleep lately?", conversationId=other)
    assert "Your time asleep held steady." not in json.dumps(agent.llm.requests[-1]["messages"])

    later = datetime.now(UTC) + memory.EPISODE_IDLE + timedelta(minutes=1)
    with session_scope(engine) as session:
        user = session.scalar(select(User))
        assert memory.consolidate(session, user.id, later) == 1  # the other chat has no claims
        from_other = memory.memory_items(session, user.id, later, uuid.UUID(other))
        from_same = memory.memory_items(session, user.id, later, uuid.UUID(sleep_chat))
    [episode] = [item for item in from_other if item.kind == "episode"]
    assert episode.metrics == ("sleep_minutes",) and episode.evidence[0].tool == "describe"
    assert "Your time asleep held steady." in episode.text
    assert not [item for item in from_same if item.kind == "episode"]  # its own turns are history

    agent.llm.turns.append(submission("As you saw before, sleep held steady."))
    ask(client, headers, "How is my sleep now?", conversationId=other)
    assert "Your time asleep held steady." in json.dumps(agent.llm.requests[-1]["messages"])


def test_deleting_a_chat_deletes_its_episode(client, engine, agent):
    from app.db import memory
    from app.db.models import MemoryEpisode

    headers = signed_in(client, engine)
    agent.llm.turns.extend(describe_then_claim("Your time asleep held steady."))
    chat_id = ask(client, headers).json()[0]["conversationId"]
    later = datetime.now(UTC) + memory.EPISODE_IDLE + timedelta(minutes=1)
    with session_scope(engine) as session:
        memory.consolidate(session, session.scalar(select(User)).id, later)
    assert client.delete(f"/conversations/{chat_id}", headers=headers).status_code == 204
    with session_scope(engine) as session:
        assert session.scalars(select(MemoryEpisode)).all() == []


def test_pinned_conversations_come_first(client, engine, agent):
    headers = signed_in(client, engine)
    agent.llm.turns.extend([submission("One."), submission("Two.")])
    older = ask(client, headers, "First question").json()[0]["conversationId"]
    newer = client.post("/conversations", headers=headers).json()["id"]
    ask(client, headers, "Second question", conversationId=newer)
    pinned = client.patch(f"/conversations/{older}", json={"pinned": True}, headers=headers).json()
    assert pinned["pinned"] is True and pinned["title"] == "First question"
    assert [c["id"] for c in client.get("/conversations", headers=headers).json()] == [older, newer]
    both = client.patch(
        f"/conversations/{older}", json={"pinned": False, "title": "Renamed"}, headers=headers
    ).json()
    assert both["pinned"] is False and both["title"] == "Renamed"


def test_an_edited_question_replaces_it_and_what_followed(client, engine, agent):
    headers = signed_in(client, engine)
    # Each answer without claims gets one repair round, so each question takes two turns.
    agent.llm.turns.extend(
        submission(text) for text in ("One.", "One.", "Two.", "Two.", "Edited.", "Edited.")
    )
    first = ask(client, headers, "How did I sleep?").json()
    chat_id = first[0]["conversationId"]
    ask(client, headers, "And on weekends?", conversationId=chat_id)
    edited = ask(client, headers, "How did I sleep in October?", replaces=first[0]["id"]).json()
    assert edited[0]["conversationId"] == chat_id
    texts = [
        m["text"]
        for m in client.get("/chat", params={"conversation": chat_id}, headers=headers).json()
    ]
    assert texts[0] == "How did I sleep in October?" and len(texts) == 2
    assert texts[1].startswith("Edited.")
    # The replaced turns are gone from what the next run is told.
    assert "And on weekends?" not in json.dumps(agent.llm.requests[-1]["messages"])


def test_only_ones_own_question_can_be_replaced(client, engine, agent):
    first = signed_in(client, engine, "first@example.com")
    second = signed_in(client, engine, "second@example.com")
    agent.llm.turns.append(submission("One."))
    question, answer = ask(client, first).json()
    assert ask(client, second, replaces=question["id"]).status_code == 404
    assert ask(client, first, replaces=answer["id"]).status_code == 404  # an answer, not a question
    other = client.post("/conversations", headers=first).json()["id"]
    wrong = ask(client, first, replaces=question["id"], conversationId=other)
    assert wrong.status_code == 422
    assert (
        len(
            client.get(
                "/chat", params={"conversation": question["conversationId"]}, headers=first
            ).json()
        )
        == 2
    )


# Reminders through the agent


def remind_router(agent, intent_name):
    from app.agent.intent import Intent

    agent.router.result = Classification(
        dict.fromkeys(LABELS, 0.0) | {"sleep": 0.9},
        dict.fromkeys(EXPERT_LABELS, 0.0),
        source="test",
        intent_probabilities={str(i): float(i == Intent(intent_name)) for i in Intent},
    )


def test_asking_for_a_reminder_prepares_one_to_tap_on(client, engine, agent):
    headers = signed_in(client, engine)
    remind_router(agent, "remind")
    nights = {"kind": "weekly", "time": "22:30", "weekdays": [0, 1, 2, 3, 4]}
    agent.llm.turns.extend(
        [
            ScriptedLLM.call(
                "propose_reminder", title="Wind down", message="Screens off soon.", schedule=nights
            ),
            submission("Here's a wind-down reminder. Tap Set on the card to turn it on."),
        ]
    )
    _, answer = ask(client, headers, "Remind me every weeknight at 22:30 to wind down").json()
    assert answer["text"] == "Here's a wind-down reminder. Tap Set on the card to turn it on."
    [reminder_id] = answer["reminderIds"]
    request = agent.llm.requests[0]
    assert {"propose_reminder", "list_reminders"} <= set(request["tools"])
    assert "propose_reminder" in request["messages"][0]["content"]  # the reminder rules
    [reminder] = client.get("/reminders", headers=headers).json()
    assert reminder["id"] == reminder_id and reminder["status"] == "proposed"
    assert reminder["source"] == "agent" and reminder["nextDueAt"] is None
    # The chat keeps the card after a reload.
    assert client.get("/chat", headers=headers).json()[-1]["reminderIds"] == [reminder_id]


def test_a_reply_saying_the_reminder_is_on_is_replaced(client, engine, agent):
    from app.reminders.tools import REMINDER_NOTE

    headers = signed_in(client, engine)
    remind_router(agent, "remind")
    once = {"kind": "once", "date": "2030-01-02", "time": "07:00"}
    agent.llm.turns.extend(
        [
            ScriptedLLM.call("propose_reminder", title="Log breakfast", message="", schedule=once),
            submission("Done! I've set it for 07:00."),
        ]
    )
    _, answer = ask(client, headers, "Remind me tomorrow at 7 to log breakfast").json()
    assert answer["text"] == REMINDER_NOTE


def test_the_answer_to_a_missing_time_continues_the_reminder(client, engine, agent):
    headers = signed_in(client, engine)
    remind_router(agent, "remind")
    agent.llm.turns.append(submission("What time would you like it?"))
    ask(client, headers, "Remind me to stretch every day")
    remind_router(agent, "clarify")  # "at 18:00" alone is unclear
    every_day = {"kind": "weekly", "time": "18:00", "weekdays": list(range(7))}
    agent.llm.turns.extend(
        [
            ScriptedLLM.call("propose_reminder", title="Stretch", message="", schedule=every_day),
            submission("Tap Set on the card to turn it on."),
        ]
    )
    _, answer = ask(client, headers, "at 18:00").json()
    request = agent.llm.requests[-2]
    assert "Earlier request: Remind me to stretch every day" in request["messages"][1]["content"]
    assert "propose_reminder" in request["tools"]
    assert len(answer["reminderIds"]) == 1


def test_questions_about_data_are_not_offered_reminder_tools(client, engine, agent):
    headers = signed_in(client, engine)
    remind_router(agent, "read")
    agent.llm.turns.append(submission("Nothing stood out."))
    ask(client, headers)
    assert "propose_reminder" not in agent.llm.requests[0]["tools"]


def test_a_correction_read_as_data_still_continues_the_logging_request():
    from app.agent.ask import _just_a_reply

    assert _just_a_reply("40 minutes, no wait it was 50 minutes")
    assert not _just_a_reply("how did I sleep last night")
    assert not _just_a_reply("my steps this week?")
