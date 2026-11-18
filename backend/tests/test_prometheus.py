"""/metrics for Prometheus: only with the token, labels that never name anyone, and the database's
numbers read at scrape time. Made-up data."""

from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine

from app.api import prometheus
from app.config import settings
from app.db.models import AnswerTrace, ChatMessage, Conversation, Spend, SyncRun, User
from app.db.session import session_scope

TOKEN = "made-up-metrics-token"
NOW = datetime.now(UTC)


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    with session_scope(engine) as db:
        person = User(email="secret.person@example.com", status="approved")
        db.add(person)
        db.flush()
        chat = Conversation(user_id=person.id)
        db.add(chat)
        db.flush()
        for i, (outcome, ms) in enumerate(
            (("answered", 4000), ("answered", 8000), ("refused", 50))
        ):
            message = ChatMessage(
                user_id=person.id,
                conversation_id=chat.id,
                role="assistant",
                text="private words",
                rating="up" if i == 0 else None,
            )
            db.add(message)
            db.flush()
            db.add(
                AnswerTrace(
                    message_id=message.id,
                    outcome=outcome,
                    stop_reason="done",
                    question_type="lookup",
                    latency_ms=ms,
                    rejected_claims=1,
                    tool_errors=1 if i == 1 else 0,
                )
            )
        db.add(Spend(user_id=person.id, kind="answer", cost_usd=0.02, at=NOW))
        db.add(
            SyncRun(
                user_id=person.id,
                source="google_health",
                status="succeeded",
                range_start=NOW.date() - timedelta(days=3),
                range_end=NOW.date(),
                started_at=NOW - timedelta(seconds=12),
                finished_at=NOW,
            )
        )
    return engine


@pytest.fixture
def client(engine, monkeypatch):
    from app.api.main import create_app

    monkeypatch.setattr(settings, "metrics_token", SecretStr(TOKEN))
    app = create_app()
    prometheus._collector.sessions = lambda: session_scope(engine)
    prometheus._collector._last = None
    return TestClient(app)


def scrape(client) -> str:
    response = client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200
    return response.text


def test_no_token_configured_means_no_endpoint(engine, monkeypatch):
    from app.api.main import create_app

    monkeypatch.setattr(settings, "metrics_token", None)
    assert TestClient(create_app()).get("/metrics").status_code == 404


def test_only_the_token_opens_it(client):
    assert client.get("/metrics").status_code == 401
    wrong = {"Authorization": "Bearer guessed"}
    assert client.get("/metrics", headers=wrong).status_code == 401


def test_the_database_numbers_are_there(client):
    text = scrape(client)
    assert 'patterns_answers_total{outcome="answered",type="lookup"} 2.0' in text
    assert 'patterns_answers_total{outcome="refused",type="lookup"} 1.0' in text
    assert "patterns_rejected_claims_total 3.0" in text
    assert "patterns_answers_with_tool_errors_total 1.0" in text
    assert 'patterns_thumbs_total{rating="up"} 1.0' in text
    assert 'patterns_llm_spend_usd_total{kind="answer"} 0.02' in text
    assert 'patterns_spend_today_usd{who="everyone"} 0.02' in text
    assert 'patterns_sync_runs_total{status="succeeded"} 1.0' in text
    assert 'patterns_sync_seconds{quantile="0.5"} 12.0' in text
    assert 'patterns_answer_latency_seconds{quantile="0.5"} 4.0' in text
    assert "patterns_database_up 1.0" in text


def test_requests_are_counted_by_pattern_and_nothing_names_anyone(client):
    client.get("/days/2026-10-05")  # refused without a sign-in, still counted
    text = scrape(client)
    assert 'route="/days/{day}"' in text and "2026-10-05" not in text
    for secret in ("secret.person", "@example.com", "private words"):
        assert secret not in text
    assert 'route="/metrics"' not in text  # scrapes are not counted as traffic


def test_a_database_outage_is_reported_not_raised(client):
    def broken():
        raise RuntimeError("database down")

    prometheus._collector.sessions = broken
    prometheus._collector._last = None
    assert "patterns_database_up 0.0" in scrape(client)


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, email):
        self.sent.append(email)


def test_grafana_alerts_arrive_by_email_only_with_the_token(client, monkeypatch):
    from app import email as mail

    fake = FakeMailer()
    monkeypatch.setattr(mail, "mailer_from_settings", lambda _settings: fake)
    monkeypatch.setattr(settings, "admin_emails", ["owner@example.com"])
    body = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "API down"},
                "annotations": {"summary": "Prometheus cannot reach the Patterns API."},
            },
            {"status": "firing", "labels": {"alertname": "Database down"}, "annotations": {}},
        ],
    }
    assert client.post("/alerts/grafana", json=body).status_code == 401
    wrong = {"Authorization": "Bearer guessed"}
    assert client.post("/alerts/grafana", json=body, headers=wrong).status_code == 401
    auth = {"Authorization": f"Bearer {TOKEN}"}
    response = client.post("/alerts/grafana", json=body, headers=auth)
    assert response.status_code == 200 and response.json() == {"sent": 1}
    (email,) = fake.sent
    assert email.to == "owner@example.com"
    assert email.subject == "[Patterns] FIRING: API down (+1)"
    assert "cannot reach the Patterns API" in email.text and "Database down" in email.text
    resolved = {"alerts": [{"status": "resolved", "labels": {"alertname": "API down"}}]}
    client.post("/alerts/grafana", json=resolved, headers=auth)
    assert fake.sent[-1].subject == "[Patterns] RESOLVED: API down"
    bad = client.post("/alerts/grafana", content=b"not json", headers=auth)
    assert bad.status_code == 422
