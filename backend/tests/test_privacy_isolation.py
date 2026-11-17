"""One person can never read, change or delete another person's data through the API.

Two approved people each get a record of every kind. Then each route that takes an id is called by
the other person with the first person's id: it must answer 404 or 403, never the record, and the
record must be unchanged afterwards. Routes that take no id must return the caller's own data.
All values are made up.
"""

from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.analysis.evidence import Evidence, Window
from app.db.models import (
    Alarm,
    ChatMessage,
    CheckIn,
    Conversation,
    DailyMetric,
    EvidenceRecord,
    HealthAction,
    MemoryEpisode,
    MemoryFact,
    MemoryInterest,
    Notification,
    Reminder,
    SyncRun,
    User,
)
from app.db.session import session_scope

NOW = datetime(2026, 10, 26, 9, tzinfo=UTC)
DAY = NOW.date() - timedelta(days=1)
PASSWORD = "correct horse battery"
STEPS = {"a": 11111.0, "b": 22222.0}  # each person's own made-up value


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


def plant(db, who: str) -> dict:
    """One record of every kind for this person; returns their ids."""
    user = User(email=f"{who}@example.com", status="approved")
    db.add(user)
    db.flush()
    u = user.id
    conversation = Conversation(user_id=u)
    db.add(conversation)
    db.flush()
    message = ChatMessage(
        user_id=u, conversation_id=conversation.id, role="assistant", text=f"{who} secret"
    )
    evidence = Evidence(
        tool="trend",
        metrics=("steps",),
        windows=(Window(start=DAY - timedelta(days=27), end=DAY),),
        n=28,
        sufficient=True,
        stats={"slope": 1.0 if who == "a" else 2.0},
    )
    rows = [
        message,
        EvidenceRecord(
            user_id=u, id=evidence.id, tool=evidence.tool, payload=evidence.model_dump(mode="json")
        ),
        MemoryFact(user_id=u, kind="routine", text=f"{who} runs on Sundays", status="approved"),
        MemoryEpisode(
            user_id=u,
            conversation_id=conversation.id,
            day=DAY,
            text=f"{who} talked about sleep",
            through=NOW,
        ),
        MemoryInterest(user_id=u, topic="steps"),
        Reminder(
            user_id=u,
            title=f"{who} bedtime",
            message="Wind down",
            schedule={"kind": "weekly", "time": "22:30", "weekdays": [0, 1, 2, 3, 4]},
            timezone="UTC",
            channels=["in_app"],
            status="active",
            source="person",
        ),
        Notification(user_id=u, kind="reminder", title=f"{who} note", body="made up"),
        Alarm(
            user_id=u,
            kind="change",
            key=f"{who}-steps",
            day=DAY,
            severity=1.0,
            title=f"{who} alarm",
            body="made up",
        ),
        HealthAction(
            user_id=u,
            request_key=f"{who}-req",
            fingerprint=f"{who}-fp",
            kind="food",
            payload={
                "kind": "food",
                "foodName": f"{who} lunch",
                "mealType": "LUNCH",
                "consumedAt": "2026-10-25T12:00:00+03:00",
                "energyKcal": 650,
            },
        ),
        CheckIn(user_id=u, day=NOW.date(), rating=4 if who == "a" else 2),
        SyncRun(
            user_id=u,
            source="google_health",
            status="succeeded",
            range_start=DAY - timedelta(days=39),
            range_end=DAY,
            started_at=NOW,
            finished_at=NOW,
        ),
    ]
    db.add_all(rows)
    for back in range(40):
        db.add(
            DailyMetric(
                user_id=u,
                source="google_health",
                day=DAY - timedelta(days=back),
                metric="steps",
                value=STEPS[who],
            )
        )
    db.flush()
    ids = {
        "user": u,
        "conversation": conversation.id,
        "message": message.id,
        "evidence": evidence.id,
    }
    for row in rows[2:9]:
        if hasattr(row, "id"):  # an interest is keyed by its topic
            ids[type(row).__name__] = row.id
    return ids


@pytest.fixture
def world(engine):
    from app.api import auth
    from app.api.main import create_app
    from app.auth import accounts

    with session_scope(engine) as db:
        ids = {who: plant(db, who) for who in ("a", "b")}

    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[auth.now] = lambda: NOW
    client = TestClient(app)
    headers = {}
    for who in ("a", "b"):
        with session_scope(engine) as session:
            user = session.scalar(select(User).where(User.email == f"{who}@example.com"))
            accounts.set_password(session, user, PASSWORD)
        token = client.post(
            "/auth/login", json={"email": f"{who}@example.com", "password": PASSWORD}
        ).json()["token"]
        headers[who] = {"Authorization": f"Bearer {token}"}
    return client, headers, ids


def attempts(ids: dict) -> list[tuple[str, str, dict | None]]:
    """Every route that takes an id, aimed at this person's records."""
    action, fact = ids["HealthAction"], ids["MemoryFact"]
    return [
        ("GET", f"/actions/{action}", None),
        ("POST", f"/actions/{action}/cancel", {"version": 1}),
        ("POST", f"/actions/{action}/confirm", {"version": 1}),
        ("POST", f"/actions/{action}/undo", {"version": 1}),
        ("POST", f"/alarms/{ids['Alarm']}/feedback", {"useful": False}),
        ("GET", f"/chat?conversation={ids['conversation']}", None),
        ("PUT", f"/chat/{ids['message']}/rating", {"rating": "down"}),
        ("PATCH", f"/conversations/{ids['conversation']}", {"title": "taken"}),
        ("DELETE", f"/conversations/{ids['conversation']}", None),
        ("POST", f"/notifications/{ids['Notification']}/read", None),
        ("POST", f"/memory/facts/{fact}/decision", {"keep": False}),
        ("PATCH", f"/memory/facts/{fact}", {"text": "changed by someone else"}),
        ("DELETE", f"/memory/facts/{fact}", None),
        ("DELETE", f"/memory/episodes/{ids['MemoryEpisode']}", None),
        ("PATCH", f"/reminders/{ids['Reminder']}", {"version": 1, "status": "paused"}),
        ("DELETE", f"/reminders/{ids['Reminder']}", None),
        ("GET", f"/evidence/{ids['evidence']}", None),
    ]


def test_no_route_hands_one_persons_records_to_another(world):
    client, headers, ids = world
    for owner, other in (("a", "b"), ("b", "a")):
        for method, path, body in attempts(ids[owner]):
            response = client.request(method, path, json=body, headers=headers[other])
            if path.startswith("/memory/facts/") and method in ("POST", "PATCH"):
                # The memory store refuses with the same words as for a fact that never existed.
                assert response.status_code == 422 and "no such fact" in response.text
            else:
                assert response.status_code in (403, 404), (method, path, response.status_code)
            assert f"{owner} " not in response.text, (method, path)  # none of the owner's text
            assert str(ids[owner]["user"]) not in response.text


def test_the_records_are_untouched_and_the_owner_still_reaches_them(world, engine):
    client, headers, ids = world
    for method, path, body in attempts(ids["a"]):
        client.request(method, path, json=body, headers=headers["b"])
    with session_scope(engine) as db:
        a = ids["a"]
        assert db.get(Conversation, a["conversation"]) is not None
        assert db.get(ChatMessage, a["message"]).rating is None
        fact = db.get(MemoryFact, a["MemoryFact"])
        assert fact.status == "approved" and fact.text == "a runs on Sundays"
        assert db.get(MemoryEpisode, a["MemoryEpisode"]) is not None
        assert db.get(Reminder, a["Reminder"]).status == "active"
        assert db.get(Notification, a["Notification"]).read_at is None
        assert db.get(Alarm, a["Alarm"]).feedback is None
        assert db.get(HealthAction, a["HealthAction"]).status == "draft"
    # The control: the owner reaches the same records with the same requests.
    own = headers["a"]
    assert client.get(f"/evidence/{ids['a']['evidence']}", headers=own).status_code == 200
    assert client.get(f"/actions/{ids['a']['HealthAction']}", headers=own).status_code == 200
    chat = client.get(f"/chat?conversation={ids['a']['conversation']}", headers=own)
    assert chat.status_code == 200 and "a secret" in chat.text


def test_muting_a_topic_mutes_only_ones_own(world, engine):
    client, headers, ids = world
    assert client.delete("/memory/interests/steps", headers=headers["b"]).status_code == 204
    with session_scope(engine) as db:
        muted = {row.user_id: row.muted for row in db.scalars(select(MemoryInterest))}
        assert muted == {ids["a"]["user"]: False, ids["b"]["user"]: True}


def test_routes_without_an_id_answer_with_the_callers_own_data(world):
    client, headers, ids = world
    for who, other in (("a", "b"), ("b", "a")):
        mine = headers[who]
        day = client.get(f"/days/{DAY.isoformat()}", headers=mine)
        assert day.status_code == 200
        assert str(int(STEPS[who])) in day.text and str(int(STEPS[other])) not in day.text
        series = client.get("/metrics/steps?days=14", headers=mine).text
        assert str(int(STEPS[other])) not in series
        checkin = client.get(f"/checkins/{NOW.date().isoformat()}", headers=mine).json()
        assert checkin["rating"] == (4 if who == "a" else 2)
        for path in (
            "/conversations",
            "/memory",
            "/reminders",
            "/notifications",
            "/alarms",
            "/actions",
        ):
            response = client.get(path, headers=mine)
            assert response.status_code == 200, path
            assert f"{other} " not in response.text, path
            assert str(ids[other]["user"]) not in response.text, path


def test_a_pending_account_reaches_nothing_but_its_own_status(world, engine):
    from app.auth import accounts

    client, _, ids = world
    with session_scope(engine) as db:
        waiting = User(email="waiting@example.com", status="pending")
        db.add(waiting)
        db.flush()
        accounts.set_password(db, waiting, PASSWORD)
    token = client.post(
        "/auth/login", json={"email": "waiting@example.com", "password": PASSWORD}
    ).json()["token"]
    pending = {"Authorization": f"Bearer {token}"}
    assert client.get("/auth/me", headers=pending).json()["status"] == "pending"
    for path in (
        f"/days/{DAY.isoformat()}",
        "/conversations",
        "/memory",
        "/reminders",
        f"/evidence/{ids['a']['evidence']}",
        "/pulse/today",
    ):
        assert client.get(path, headers=pending).status_code == 403, path
