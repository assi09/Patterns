"""Sentry error reports: off without a DSN, and nothing personal in what is sent.

Events go to a transport that keeps them in memory; no network is used. All values are made up.
"""

import json
import logging

import pytest
import sentry_sdk
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from app import observability
from app.api import main as api_main
from app.config import Settings

SECRET_VALUE = "resting heart rate 52"
EMAIL = "made-up-person@example.com"
TOKEN = "made-up-session-token"


class Kept(Transport):
    """Keeps every event instead of sending it."""

    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        for item in envelope.items:
            if item.type == "event":
                self.events.append(item.payload.json)


@pytest.fixture
def kept():
    transport = Kept()
    settings = Settings(sentry_dsn="https://public@sentry.example.invalid/1", _env_file=None)
    assert observability.init_sentry(settings, transport=transport)
    yield transport
    sentry_sdk.get_client().close()
    sentry_sdk.init()  # an inactive client again, for the other tests


def test_nothing_starts_without_a_dsn():
    assert not observability.init_sentry(Settings(_env_file=None))
    assert not sentry_sdk.get_client().is_active()


def _failing_app() -> FastAPI:
    app = FastAPI()

    @app.post("/boom")
    def boom(body: dict) -> dict:
        reading = body["reading"]
        raise ValueError(f"{SECRET_VALUE} for {reading}")

    @app.get("/logged")
    def logged() -> dict:
        try:
            raise RuntimeError(EMAIL)
        except RuntimeError:
            logging.getLogger("app.sync").exception("Sync failed for %s", EMAIL)
        return {"ok": True}

    return app


def test_an_unhandled_error_is_reported_without_personal_data(kept):
    client = TestClient(_failing_app(), raise_server_exceptions=False)
    response = client.post(
        f"/boom?email={EMAIL}",
        json={"reading": "hrv 41 ms"},
        headers={"Authorization": f"Bearer {TOKEN}", "Cookie": f"session={TOKEN}"},
    )
    sentry_sdk.flush()
    assert response.status_code == 500

    assert len(kept.events) == 1
    event = kept.events[0]
    exception = event["exception"]["values"][-1]
    assert exception["type"] == "ValueError"
    assert exception["value"] == observability.REMOVED
    frames = exception["stacktrace"]["frames"]
    assert any(frame.get("function") == "boom" for frame in frames)
    assert all("vars" not in frame for frame in frames)

    sent = json.dumps(event)
    for private in (SECRET_VALUE, "hrv 41", EMAIL, TOKEN, "Bearer"):
        assert private not in sent
    assert "user" not in event


def test_an_error_log_is_reported_as_its_template_only(kept):
    client = TestClient(_failing_app(), raise_server_exceptions=False)
    assert client.get("/logged").status_code == 200
    sentry_sdk.flush()

    assert len(kept.events) == 1
    event = kept.events[0]
    assert event["logentry"]["message"] == "Sync failed for %s"
    assert "params" not in event["logentry"]
    assert EMAIL not in json.dumps(event)


def test_scrub_keeps_the_shape_and_drops_the_rest():
    event = {
        "exception": {
            "values": [
                {
                    "type": "KeyError",
                    "value": SECRET_VALUE,
                    "stacktrace": {
                        "frames": [{"function": "f", "lineno": 3, "vars": {"hr": "52"}}]
                    },
                }
            ]
        },
        "threads": {"values": [{"stacktrace": {"frames": [{"vars": {"x": 1}}]}}]},
        "logentry": {"message": "Failed for %s", "params": [EMAIL], "formatted": EMAIL},
        "message": f"Failed for {EMAIL}",
        "request": {
            "url": "https://api.example.invalid/days/2026-01-02",
            "data": {"text": SECRET_VALUE},
            "query_string": "code=abc",
            "cookies": {"session": TOKEN},
            "headers": {"Authorization": f"Bearer {TOKEN}", "User-Agent": "test"},
        },
        "user": {"email": EMAIL},
        "breadcrumbs": {"values": [{"message": SECRET_VALUE}]},
        "extra": {"value": SECRET_VALUE},
    }
    scrubbed = observability.scrub(event)

    exception = scrubbed["exception"]["values"][0]
    assert exception["type"] == "KeyError"
    assert exception["value"] == observability.REMOVED
    assert exception["stacktrace"]["frames"] == [{"function": "f", "lineno": 3}]
    assert scrubbed["threads"]["values"][0]["stacktrace"]["frames"] == [{}]
    assert scrubbed["logentry"] == {"message": "Failed for %s"}
    assert scrubbed["message"] == "Failed for %s"
    assert scrubbed["request"] == {
        "url": "https://api.example.invalid/days/2026-01-02",
        "headers": {"User-Agent": "test"},
    }
    for key in ("user", "breadcrumbs", "extra"):
        assert key not in scrubbed


def test_scrub_accepts_an_event_with_nothing_to_remove():
    assert observability.scrub({"level": "error"}) == {"level": "error"}


def test_the_api_starts_sentry_when_it_is_created(monkeypatch):
    started = []
    monkeypatch.setattr(api_main, "init_sentry", lambda settings: started.append(settings))
    api_main.create_app()
    assert started == [api_main.settings]
