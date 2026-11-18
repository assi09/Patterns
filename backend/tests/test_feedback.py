"""Testers' reports and feedback: only about their own answers and chats, kept with the answer
they are about, emailed to the admins, listed for admins only, and gone with the account.
Made-up data."""

from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select

from app import email as mail
from app.config import settings
from app.db.models import ChatMessage, Conversation, Feedback, User
from app.db.session import session_scope

NOW = datetime(2026, 11, 18, 18, tzinfo=UTC)
PASSWORD = "correct horse battery"


class FakeMailer:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def send(self, email):
        if self.fail:
            raise mail.MailError("down")
        self.sent.append(email)


@pytest.fixture
def world(tmp_path, monkeypatch):
    from app.api import auth
    from app.api.main import create_app
    from app.auth import accounts

    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):  # SQLite cascades deletes only when asked to
        connection.execute("PRAGMA foreign_keys=ON")

    monkeypatch.setattr(settings, "admin_emails", ["owner@example.com"])
    fake = FakeMailer()
    monkeypatch.setattr(mail, "mailer_from_settings", lambda _s: fake)
    ids = {}
    with session_scope(engine) as db:
        for who in ("owner", "tester", "other"):
            user = User(email=f"{who}@example.com", status="approved")
            db.add(user)
            db.flush()
            accounts.set_password(db, user, PASSWORD)
            chat = Conversation(user_id=user.id)
            db.add(chat)
            db.flush()
            answer = ChatMessage(
                user_id=user.id, conversation_id=chat.id, role="assistant", text=f"{who} answer"
            )
            db.add(answer)
            db.flush()
            ids[who] = {"user": user.id, "chat": str(chat.id), "answer": str(answer.id)}
    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[auth.now] = lambda: NOW
    client = TestClient(app)
    headers = {}
    for who in ("owner", "tester", "other"):
        token = client.post(
            "/auth/login", json={"email": f"{who}@example.com", "password": PASSWORD}
        ).json()["token"]
        headers[who] = {"Authorization": f"Bearer {token}"}
    return client, headers, ids, engine, fake


def test_a_report_keeps_its_answer_and_reaches_the_admins(world):
    client, headers, ids, engine, fake = world
    body = {
        "kind": "report",
        "text": "This number looks wrong",
        "messageId": ids["tester"]["answer"],
    }
    response = client.post("/feedback", json=body, headers=headers["tester"])
    assert response.status_code == 201 and response.json()["quoted"] == "tester answer"
    with session_scope(engine) as db:
        row = db.scalar(select(Feedback))
        assert str(row.conversation_id) == ids["tester"]["chat"]  # taken from the answer
    (email,) = fake.sent
    assert email.to == "owner@example.com" and "This number looks wrong" in email.text
    assert "tester@example.com" in email.text and "tester answer" in email.text


def test_feedback_on_a_whole_chat_and_on_nothing_in_particular(world):
    client, headers, ids, *_ = world
    chat = {"kind": "feedback", "text": "Answers are slow", "conversationId": ids["tester"]["chat"]}
    assert client.post("/feedback", json=chat, headers=headers["tester"]).status_code == 201
    loose = {"kind": "feedback", "text": "Love the Today page"}
    assert client.post("/feedback", json=loose, headers=headers["tester"]).status_code == 201


def test_nobody_reports_on_someone_elses_answer_or_chat(world):
    client, headers, ids, engine, fake = world
    theirs = {"kind": "report", "text": "x", "messageId": ids["other"]["answer"]}
    assert client.post("/feedback", json=theirs, headers=headers["tester"]).status_code == 404
    chat = {"kind": "feedback", "text": "x", "conversationId": ids["other"]["chat"]}
    assert client.post("/feedback", json=chat, headers=headers["tester"]).status_code == 404
    with session_scope(engine) as db:
        assert db.scalar(select(Feedback)) is None
    assert fake.sent == []


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001])
def test_empty_or_overlong_text_is_refused(world, text):
    client, headers, *_ = world
    response = client.post(
        "/feedback", json={"kind": "feedback", "text": text}, headers=headers["tester"]
    )
    assert response.status_code == 422


def test_only_admins_list_feedback(world):
    client, headers, *_ = world
    client.post("/feedback", json={"kind": "feedback", "text": "hello"}, headers=headers["tester"])
    assert client.get("/admin/feedback", headers=headers["tester"]).status_code == 403
    (row,) = client.get("/admin/feedback", headers=headers["owner"]).json()
    assert row["email"] == "tester@example.com" and row["text"] == "hello"


def test_a_failed_email_keeps_the_feedback(world, monkeypatch):
    client, headers, ids, engine, _ = world
    monkeypatch.setattr(mail, "mailer_from_settings", lambda _s: FakeMailer(fail=True))
    body = {"kind": "feedback", "text": "still saved"}
    assert client.post("/feedback", json=body, headers=headers["tester"]).status_code == 201
    with session_scope(engine) as db:
        assert db.scalar(select(Feedback.text)) == "still saved"


def test_feedback_goes_with_the_account(world):
    from app.auth.deletion import delete_account

    client, headers, ids, engine, _ = world
    client.post("/feedback", json={"kind": "feedback", "text": "bye"}, headers=headers["tester"])
    with session_scope(engine) as db:
        delete_account(db, db.get(User, ids["tester"]["user"]))
    with session_scope(engine) as db:
        assert db.scalar(select(Feedback)) is None
