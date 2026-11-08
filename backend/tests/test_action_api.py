import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.actions.provider import Outcome
from app.agent.agent import SUBMIT
from app.agent.llm import ScriptedLLM
from app.agent.router import KeywordRouter
from app.api import actions, auth, chat
from app.api.chat import AgentParts
from app.api.main import create_app
from app.api.store import analyze, get_data
from app.config import settings
from app.db.models import User
from app.db.session import session_scope
from app.ingest.takeout import DailyData
from app.synthetic import generate


def _hours_ago(hours: float) -> str:
    """A time a draft may have without naming a day: within the last 24 hours."""
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


FOOD = {
    "kind": "food",
    "foodName": "Example lunch",
    "mealType": "LUNCH",
    "consumedAt": _hours_ago(2),
    "energyKcal": 650,
    "proteinG": 40,
}


@pytest.fixture
def setup(tmp_path):
    config = Config("alembic.ini")
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[chat.get_sessions] = lambda: lambda: session_scope(engine)
    frame = generate(date(2026, 7, 1), 60, seed=5).frame
    app.dependency_overrides[get_data] = lambda: analyze(DailyData(frame=frame), datetime.now(UTC))
    agent = AgentParts(ScriptedLLM([]), KeywordRouter(), None)
    app.dependency_overrides[chat.get_agent] = lambda: agent
    client = TestClient(app)
    return client, engine, agent


def sign_in(setup, email="example@example.com", approve=True):
    client, engine, _ = setup
    result = client.post("/auth/signup", json={"email": email, "password": "correct horse battery"})
    if approve:
        with session_scope(engine) as db:
            db.scalar(select(User).where(User.email == email)).status = "approved"
    return {"Authorization": f"Bearer {result.json()['token']}"}


def propose(client, headers, payload=None):
    return client.post(
        "/actions", headers=headers, json={"requestKey": str(uuid.uuid4()), "log": payload or FOOD}
    )


def test_action_api_needs_sign_in_and_approval(setup):
    client, _, _ = setup
    assert client.get("/actions").status_code == 401
    headers = sign_in(setup, approve=False)
    assert propose(client, headers).status_code == 403
    assert client.get("/actions", headers=headers).status_code == 403


def test_owned_review_edit_confirm_and_undo_api(setup, monkeypatch):
    client, _, _ = setup
    headers = sign_in(setup)
    other = sign_in(setup, "other@example.com")
    row = propose(client, headers).json()
    assert row["status"] == "draft" and row["version"] == 1
    action_id = row["id"]
    for suffix in ("", "/confirm", "/cancel", "/undo", "/revise"):
        response = (
            client.get(f"/actions/{action_id}", headers=other)
            if not suffix
            else client.post(
                f"/actions/{action_id}{suffix}",
                headers=other,
                json={"version": 1, **({"log": FOOD} if suffix == "/revise" else {})},
            )
        )
        assert response.status_code == 404
    assert client.get("/actions", headers=other).json() == []
    changed = client.post(
        f"/actions/{action_id}/revise",
        headers=headers,
        json={"version": 1, "log": FOOD | {"proteinG": 45}},
    ).json()
    assert changed["version"] == 2 and changed["log"]["proteinG"] == 45
    assert (
        client.post(
            f"/actions/{action_id}/confirm", headers=headers, json={"version": 1}
        ).status_code
        == 409
    )
    calls = []

    class Writer:
        def create(self, kind, payload):
            calls.append(("create", payload))
            return Outcome(
                "succeeded", provider_name="users/example/dataTypes/nutrition-log/dataPoints/one"
            )

        def delete(self, kind, name):
            calls.append(("delete", name))
            return Outcome("succeeded")

    monkeypatch.setattr(actions, "get_writer", lambda *args: Writer())
    assert (
        client.post(f"/actions/{action_id}/confirm", headers=headers, json={"version": 2}).json()[
            "status"
        ]
        == "succeeded"
    )
    assert (
        client.post(
            f"/actions/{action_id}/confirm", headers=headers, json={"version": 2}
        ).status_code
        == 200
    )
    assert len(calls) == 1
    assert (
        client.post(f"/actions/{action_id}/undo", headers=headers, json={"version": 2}).json()[
            "status"
        ]
        == "undone"
    )
    assert (
        client.post(f"/actions/{action_id}/undo", headers=headers, json={"version": 2}).status_code
        == 200
    )
    assert len(calls) == 2


def test_writes_disabled_and_missing_scope_keep_the_draft(setup, monkeypatch):
    from app.db.models import GoogleConnection

    client, engine, _ = setup
    headers = sign_in(setup)
    row = propose(client, headers).json()
    url = f"/actions/{row['id']}/confirm"
    monkeypatch.setattr(settings, "google_writes_enabled", False)
    assert (
        client.post(url, headers=headers, json={"version": 1}).json()["error"]["code"]
        == "writes_disabled"
    )
    monkeypatch.setattr(settings, "google_writes_enabled", True)
    assert (
        client.post(url, headers=headers, json={"version": 1}).json()["error"]["code"]
        == "not_connected"
    )
    with session_scope(engine) as db:
        user = db.scalar(select(User))
        db.add(
            GoogleConnection(user_id=user.id, encrypted_token=b"fake", scopes=[], status="active")
        )
    assert (
        client.post(url, headers=headers, json={"version": 1}).json()["error"]["code"]
        == "write_scope_needed"
    )
    assert client.get(f"/actions/{row['id']}", headers=headers).json()["status"] == "draft"


def test_chat_prepares_a_persisted_nutrition_draft_without_history_or_execution(setup):
    client, _, agent = setup
    headers = sign_in(setup)
    agent.llm.turns.extend(
        [
            ScriptedLLM.call("propose_food_log", **FOOD),
            ScriptedLLM.call(SUBMIT, summary="Draft ready for review.", claims=[]),
        ]
    )
    response = client.post("/chat", headers=headers, json={"text": "Log lunch with 40 g protein."})
    assert response.status_code == 200
    reply = response.json()[-1]
    assert reply["answeredBy"] == "nutrition" and len(reply["actionIds"]) == 1
    # The expert's own words, safe to show: no values, and it says the draft waits for review.
    assert reply["text"] == "Draft ready for review."
    row = client.get(f"/actions/{reply['actionIds'][0]}", headers=headers).json()
    assert row["status"] == "draft" and row["log"]["proteinG"] == 40
    assert "propose_food_log" in agent.llm.requests[0]["tools"]
    assert not any("confirm" in tool or "delete" in tool for tool in agent.llm.requests[0]["tools"])
    assert client.get("/chat", headers=headers).json()[-1]["actionIds"] == reply["actionIds"]


def test_read_only_and_medical_requests_never_get_proposal_tools(setup):
    client, _, agent = setup
    headers = sign_in(setup)
    for text in ("How much protein did I eat?", "Log lunch and diagnose my insomnia."):
        response = client.post("/chat", headers=headers, json={"text": text})
        assert response.status_code == 200
    assert agent.llm.requests == []
    assert client.get("/actions", headers=headers).json() == []


def test_invalid_fields_and_model_confirmation_arguments_are_rejected(setup):
    client, _, _ = setup
    headers = sign_in(setup)
    assert propose(client, headers, FOOD | {"confirmed": True}).status_code == 422
    row = propose(client, headers).json()
    assert (
        client.post(
            f"/actions/{row['id']}/confirm", headers=headers, json={"version": True}
        ).status_code
        == 422
    )


def test_missing_fields_request_details_without_persisting_a_partial_log(setup):
    client, _, agent = setup
    headers = sign_in(setup)
    agent.llm.turns.extend(
        [
            ScriptedLLM.call("propose_food_log", foodName="Example lunch", proteinG=40),
            ScriptedLLM.call(
                SUBMIT, summary="When did you eat it, and which meal was it?", claims=[]
            ),
        ]
    )
    response = client.post("/chat", headers=headers, json={"text": "Log lunch with 40 g protein."})
    assert response.status_code == 200
    assert "actionIds" not in response.json()[-1]
    assert client.get("/actions", headers=headers).json() == []
    content = agent.llm.requests[-1]["messages"]
    assert any("consumedAt" in m.get("content", "") for m in content if m["role"] == "tool")


def test_missing_details_can_continue_the_owned_pending_logging_request(setup):
    client, _, agent = setup
    headers = sign_in(setup)
    agent.llm.turns.extend(
        [
            ScriptedLLM.call(SUBMIT, summary="When did you eat this meal?", claims=[]),
            ScriptedLLM.call("propose_food_log", **FOOD),
            ScriptedLLM.call(SUBMIT, summary="Draft ready for review.", claims=[]),
        ]
    )
    first = client.post("/chat", headers=headers, json={"text": "Log lunch with 40 g protein."})
    assert first.status_code == 200 and "actionIds" not in first.json()[-1]
    follow = client.post("/chat", headers=headers, json={"text": "At 12:00 today, UTC+3."})
    assert follow.status_code == 200 and len(follow.json()[-1]["actionIds"]) == 1
    assert follow.json()[-1]["text"] == "Draft ready for review."


def test_read_only_topic_change_clears_the_pending_log(setup):
    client, _, agent = setup
    headers = sign_in(setup)
    agent.llm.turns.extend([ScriptedLLM.call(SUBMIT, summary="When did you eat it?", claims=[])])
    client.post("/chat", headers=headers, json={"text": "Log lunch with 40 g protein."})
    client.post("/chat", headers=headers, json={"text": "How much protein did I eat yesterday?"})
    client.post("/chat", headers=headers, json={"text": "At noon."})
    # "At noon." alone is only asked about: no logging tool is offered for it.
    assert len(agent.llm.requests) == 2 and agent.llm.requests[1]["tools"] == []
    assert client.get("/actions", headers=headers).json() == []


def test_expired_pending_log_does_not_offer_proposal_tools(setup):
    from datetime import timedelta

    from app.db.models import ChatMessage

    client, engine, agent = setup
    headers = sign_in(setup)
    agent.llm.turns.extend([ScriptedLLM.call(SUBMIT, summary="When did you eat it?", claims=[])])
    client.post("/chat", headers=headers, json={"text": "Log lunch with 40 g protein."})
    with session_scope(engine) as db:
        rows = list(db.scalars(select(ChatMessage).order_by(ChatMessage.created_at)))
        for index, row in enumerate(rows):
            row.created_at = datetime.now(UTC) - timedelta(hours=25) + timedelta(seconds=index)
    client.post("/chat", headers=headers, json={"text": "At noon."})
    # "At noon." alone is only asked about: no logging tool is offered for it.
    assert len(agent.llm.requests) == 2 and agent.llm.requests[1]["tools"] == []
    assert client.get("/actions", headers=headers).json() == []


def test_database_errors_do_not_echo_or_log_health_payloads(setup, monkeypatch, caplog):
    from sqlalchemy.exc import StatementError

    from app.actions import store

    client, _, _ = setup
    headers = sign_in(setup)

    def fail(*args):
        raise StatementError("private health input", "INSERT", FOOD, RuntimeError("private"))

    monkeypatch.setattr(store, "propose", fail)
    response = propose(client, headers)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"
    assert "private" not in response.text and "Example lunch" not in caplog.text


def test_mixed_food_log_does_not_invent_a_read_answer_without_nutrition_history(setup):
    client, _, agent = setup
    headers = sign_in(setup)
    agent.llm.turns.extend(
        [
            ScriptedLLM.call("propose_food_log", **FOOD),
            ScriptedLLM.call(SUBMIT, summary="Your protein intake increased.", claims=[]),
        ]
    )
    response = client.post(
        "/chat", headers=headers, json={"text": "Log lunch and show me my protein total."}
    )
    reply = response.json()[-1]
    assert reply["actionIds"] and "No nutrition history is available yet." in reply["text"]
    assert "increased" not in reply["text"]


def test_a_general_logging_request_can_be_narrowed_to_food_on_the_next_reply(setup):
    client, _, agent = setup
    headers = sign_in(setup)
    agent.llm.turns.extend(
        [
            ScriptedLLM.call(SUBMIT, summary="Is this a meal or a workout?", claims=[]),
            ScriptedLLM.call("propose_food_log", **FOOD),
            ScriptedLLM.call(SUBMIT, summary="Draft ready for review.", claims=[]),
        ]
    )
    client.post("/chat", headers=headers, json={"text": "Log something."})
    response = client.post(
        "/chat",
        headers=headers,
        json={
            "text": "Food: Example lunch, 650 kcal and 40 g protein for lunch "
            "at 2026-10-24T12:00:00+03:00."
        },
    )
    assert len(response.json()[-1]["actionIds"]) == 1
    assert "propose_workout_log" in agent.llm.requests[0]["tools"]
    assert "propose_workout_log" not in agent.llm.requests[1]["tools"]


def test_workout_drafts_carry_the_trackers_reading_and_revising_reads_it_again(setup, monkeypatch):
    from app.actions.schemas import Measured

    client, _, _ = setup
    headers = sign_in(setup)
    readings = iter([Measured(status="no_data"), Measured(status="measured", steps=900)])
    asked = []

    def measure_workout(db, user_id, start, end, exercise_type):
        asked.append((start, end))
        return next(readings)

    monkeypatch.setattr(actions, "measure_workout", measure_workout)
    workout = {
        "kind": "workout",
        "exerciseType": "WALKING",
        "startTime": _hours_ago(2),
        "endTime": _hours_ago(1.5),
        "activeSeconds": 1200,
        "measured": {"status": "measured", "caloriesKcal": 9000},  # never trusted from a client
    }
    created = propose(client, headers, workout).json()
    measured = created["log"]["measured"]
    assert measured["status"] == "no_data" and measured["caloriesKcal"] is None
    # "Refresh" in the app saves the same log again; the tracker is read again.
    revised = client.post(
        f"/actions/{created['id']}/revise",
        headers=headers,
        json={"version": created["version"], "log": created["log"]},
    ).json()
    assert revised["version"] == created["version"] + 1
    assert revised["log"]["measured"]["steps"] == 900
    assert len(asked) == 2


def test_without_google_a_workout_draft_is_kept_unmeasured(setup):
    client, _, _ = setup
    headers = sign_in(setup)
    workout = {
        "kind": "workout",
        "exerciseType": "RUNNING",
        "startTime": _hours_ago(2),
        "endTime": _hours_ago(1.5),
        "activeSeconds": 1200,
    }
    created = propose(client, headers, workout)
    assert created.status_code == 201
    assert created.json()["log"]["measured"]["status"] == "unavailable"


def test_a_log_only_workout_request_is_not_told_it_left_activity_uncovered(setup):
    client, _, agent = setup
    headers = sign_in(setup)
    workout = {
        "kind": "workout",
        "exerciseType": "KICKBOXING",
        "startTime": "2026-10-24T18:00:00+00:00",
        "endTime": "2026-10-24T18:45:00+00:00",
        "activeSeconds": 2700,
    }
    agent.llm.turns.extend(
        [
            ScriptedLLM.call("propose_workout_log", **workout),
            ScriptedLLM.call(SUBMIT, summary="Draft ready for review.", claims=[]),
        ]
    )
    response = client.post(
        "/chat",
        headers=headers,
        json={"text": "Log my 45 minute kickboxing workout yesterday at 6pm."},
    )
    reply = response.json()[-1]
    assert reply["answeredBy"] == "activity" and len(reply["actionIds"]) == 1
    assert "was not checked" not in reply["text"]
    assert len(agent.llm.requests) == 2  # no repair round asking for activity claims
