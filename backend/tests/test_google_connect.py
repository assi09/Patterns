import time
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select

from app.api import auth, chat, google
from app.api.google import GoogleParts
from app.api.main import create_app
from app.auth.accounts import LoginThrottle
from app.config import settings
from app.db.models import DailyMetric, GoogleConnection, SyncRun, User
from app.db.session import session_scope
from app.ingest.takeout import DailyData
from app.sync import connections, pull
from app.sync.connections import SignIns, Syncs, TokenBox, first_day, plan
from app.sync.google_auth import SCOPES, NotConfigured, ReconnectNeeded

TODAY = date(2026, 10, 24)
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"
HISTORY_START = date(2026, 3, 1)  # where the fake account's data begins


def credentials(refresh_token: str | None = "refresh-secret") -> Credentials:
    return Credentials(
        token="access-secret",
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client",
        client_secret="secret",
        scopes=list(SCOPES),
        expiry=datetime(2030, 1, 1),  # naive UTC, as google-auth keeps it
    )


class FakeOAuth:
    def __init__(self):
        self.exchanged: list[tuple[str, str]] = []
        self.fail = False
        self.refresh_token: str | None = "refresh-secret"

    def authorization_url(self, state: str, challenge: str) -> str:
        return f"https://accounts.example/auth?state={state}&code_challenge={challenge}"

    def exchange(self, code: str, verifier: str) -> Credentials:
        if self.fail:
            raise RuntimeError("Google refused the code")
        self.exchanged.append((code, verifier))
        return credentials(self.refresh_token)


class FakeHealth:
    """Steps exist from HISTORY_START on; the rest of the API is replaced by `fake_load`."""

    def __init__(self, token):
        self.token = token
        self.rollups: list[tuple[date, date]] = []

    def daily_rollup(self, data_type, start, end):
        self.rollups.append((start, end))
        return [{"day": "x"}] if end > HISTORY_START else []


def fake_load(health, start, end):
    days = pd.date_range(max(start, HISTORY_START), end - timedelta(days=1), name="date")
    return DailyData(frame=pd.DataFrame({"steps": [1000.0] * len(days)}, index=days))


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


@pytest.fixture
def oauth():
    return FakeOAuth()


@pytest.fixture
def box():
    return TokenBox(SecretStr(Fernet.generate_key().decode()))


@pytest.fixture
def client(engine, oauth, box, monkeypatch) -> TestClient:
    monkeypatch.setattr(auth, "throttle", LoginThrottle())
    monkeypatch.setattr(google, "sign_ins", SignIns())
    monkeypatch.setattr(google, "syncs", Syncs())
    monkeypatch.setattr(pull, "load_daily", fake_load)
    monkeypatch.setattr(settings, "app_url", "http://app.test")
    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[auth.now] = lambda: NOW
    app.dependency_overrides[chat.get_sessions] = lambda: lambda: session_scope(engine)
    app.dependency_overrides[google.get_google] = lambda: GoogleParts(oauth, box, FakeHealth)
    return TestClient(app, follow_redirects=False)


def signed_in(client, engine, email="person@example.com", approved=True) -> dict:
    token = client.post("/auth/signup", json={"email": email, "password": PASSWORD}).json()["token"]
    if approved:
        with session_scope(engine) as session:
            session.scalar(select(User).where(User.email == email)).status = "approved"
    return {"Authorization": f"Bearer {token}"}


def connect(client, headers, code="the-code", **extra):
    url = client.post("/google/connect", headers=headers).json()["url"]
    state = parse_qs(urlparse(url).query)["state"][0]
    return client.get("/google/callback", params={"state": state, "code": code, **extra}), state


def wait_for_sync():
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and google.syncs._running:
        time.sleep(0.02)
    assert not google.syncs._running


def stored_days(engine, email="person@example.com"):
    with session_scope(engine) as session:
        user = session.scalar(select(User).where(User.email == email))
        return session.execute(
            select(func.min(DailyMetric.day), func.max(DailyMetric.day), func.count()).where(
                DailyMetric.user_id == user.id
            )
        ).one()


# Access and status


def test_connecting_needs_an_approved_account(client, engine):
    assert client.get("/google/status").status_code == 401
    pending = signed_in(client, engine, approved=False)
    assert client.post("/google/connect", headers=pending).status_code == 403


def test_a_new_person_is_not_connected(client, engine):
    status = client.get("/google/status", headers=signed_in(client, engine)).json()
    assert status == {
        "status": "none",
        "syncing": False,
        "lastSync": None,
        "lastError": None,
        "missingScopes": [],
    }


def test_connect_returns_googles_page_with_a_fresh_state_and_pkce(client, engine):
    headers = signed_in(client, engine)
    first = client.post("/google/connect", headers=headers).json()["url"]
    second = client.post("/google/connect", headers=headers).json()["url"]
    query = parse_qs(urlparse(first).query)
    assert len(query["state"][0]) >= 24 and len(query["code_challenge"][0]) == 43
    assert first != second


def test_the_real_sign_in_address_asks_for_offline_read_only_access():
    oauth = connections.GoogleOAuth(
        connections.OAuthClient("client-id", "client-secret"), "http://127.0.0.1:8000/cb"
    )
    query = parse_qs(urlparse(oauth.authorization_url("st", "ch")).query)
    assert query["redirect_uri"] == ["http://127.0.0.1:8000/cb"]
    assert query["access_type"] == ["offline"] and query["code_challenge_method"] == ["S256"]
    assert set(query["scope"][0].split()) == set(SCOPES)
    assert all(scope.endswith(".readonly") for scope in SCOPES)


# The callback


def test_connecting_stores_an_encrypted_token_and_syncs_the_whole_history(
    client, engine, oauth, box
):
    headers = signed_in(client, engine)
    response, _ = connect(client, headers)
    assert response.status_code == 303
    assert response.headers["location"] == "http://app.test/settings?google=connected"
    assert oauth.exchanged[0][0] == "the-code"

    with session_scope(engine) as session:
        stored = session.scalar(select(GoogleConnection))
        assert b"refresh-secret" not in stored.encrypted_token  # never in plain text
        assert box.open(stored.encrypted_token).refresh_token == "refresh-secret"
        assert stored.status == "active"

    wait_for_sync()
    first, last, count = stored_days(engine)
    assert (first, last) == (HISTORY_START, TODAY)
    assert count == (TODAY - HISTORY_START).days + 1
    status = client.get("/google/status", headers=headers).json()
    assert status["status"] == "active" and status["syncing"] is False
    assert status["lastSync"] is not None and status["lastError"] is None


def test_the_first_sync_stores_the_newest_days_first(client, engine):
    connect(client, signed_in(client, engine))
    wait_for_sync()
    with session_scope(engine) as session:
        runs = session.scalars(select(SyncRun).order_by(SyncRun.started_at)).all()
        ends = [run.range_end for run in runs]
    assert ends == sorted(ends, reverse=True) and len(runs) > 1


@pytest.mark.parametrize(
    ("params", "result"),
    [
        ({"state": "made-up", "code": "x"}, "expired"),
        ({"state": "", "code": "x"}, "expired"),
    ],
)
def test_an_unknown_state_is_refused(client, params, result):
    response = client.get("/google/callback", params=params)
    assert response.headers["location"].endswith(f"google={result}")


def test_a_state_works_once_and_expires(client, engine):
    headers = signed_in(client, engine)
    response, state = connect(client, headers)
    replay = client.get("/google/callback", params={"state": state, "code": "again"})
    assert replay.headers["location"].endswith("google=expired")

    url = client.post("/google/connect", headers=headers).json()["url"]
    old_state = parse_qs(urlparse(url).query)["state"][0]
    late = NOW + timedelta(minutes=11)
    client.app.dependency_overrides[auth.now] = lambda: late
    response = client.get("/google/callback", params={"state": old_state, "code": "x"})
    assert response.headers["location"].endswith("google=expired")


def test_saying_no_on_googles_page_connects_nothing(client, engine):
    response, _ = connect(client, signed_in(client, engine), code="", error="access_denied")
    assert response.headers["location"].endswith("google=cancelled")
    with session_scope(engine) as session:
        assert session.scalar(select(GoogleConnection)) is None


@pytest.mark.parametrize("problem", ["exchange", "no_refresh_token"])
def test_a_failed_exchange_connects_nothing(client, engine, oauth, problem):
    if problem == "exchange":
        oauth.fail = True
    else:
        oauth.refresh_token = None
    response, _ = connect(client, signed_in(client, engine))
    assert response.headers["location"].endswith("google=failed")
    with session_scope(engine) as session:
        assert session.scalar(select(GoogleConnection)) is None


def test_the_connection_goes_to_whoever_started_it(client, engine):
    first = signed_in(client, engine, "first@example.com")
    signed_in(client, engine, "second@example.com")
    connect(client, first)
    wait_for_sync()
    with session_scope(engine) as session:
        owner = session.scalar(select(GoogleConnection)).user_id
        assert session.get(User, owner).email == "first@example.com"
    assert stored_days(engine, "second@example.com")[2] == 0


# Syncing again and disconnecting


def test_syncing_needs_a_connection(client, engine):
    response = client.post("/google/sync", headers=signed_in(client, engine))
    assert response.status_code == 409 and response.json()["error"]["code"] == "not_connected"


def test_a_later_sync_rereads_only_the_last_days(client, engine):
    headers = signed_in(client, engine)
    connect(client, headers)
    wait_for_sync()
    response = client.post("/google/sync", headers=headers, json={"force": True})
    assert response.status_code == 202
    wait_for_sync()
    with session_scope(engine) as session:
        latest = session.scalar(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1))
    assert latest.range_start == TODAY - timedelta(days=connections.RESYNC_DAYS)


def sync_runs(engine) -> int:
    with session_scope(engine) as session:
        return len(session.scalars(select(SyncRun)).all())


def test_the_apps_automatic_syncs_start_at_most_one_every_ten_minutes(client, engine):
    headers = signed_in(client, engine)
    connect(client, headers)
    wait_for_sync()
    age(engine, timedelta(0))  # runs start on the real clock; requests use the test's NOW
    first = sync_runs(engine)  # the first sync writes one run per chunk of history
    # Opening the app again right after it: answered, but nothing new starts.
    response = client.post("/google/sync", headers=headers)
    assert response.status_code == 202 and response.json()["syncing"] is False
    assert sync_runs(engine) == first
    # "Sync now" in Settings always starts one.
    client.post("/google/sync", headers=headers, json={"force": True})
    wait_for_sync()
    assert sync_runs(engine) == first + 1
    age(engine, timedelta(0))
    # Once the last attempt is older than ten minutes, opening the app syncs again.
    age(engine, google.RESYNC_AFTER + timedelta(minutes=1))
    client.post("/google/sync", headers=headers)
    wait_for_sync()
    assert sync_runs(engine) == first + 2


def test_a_failed_sync_is_not_retried_on_every_refresh(client, engine):
    headers = signed_in(client, engine)
    connect(client, headers)
    wait_for_sync()
    age(engine, timedelta(0))
    first = sync_runs(engine)
    with session_scope(engine) as session:
        for run in session.scalars(select(SyncRun)):
            run.status, run.error = "failed", "Google did not answer."
    client.post("/google/sync", headers=headers)
    assert sync_runs(engine) == first


def age(engine, by: timedelta) -> None:
    """Makes every sync run look as if it started `by` before the test's clock."""
    with session_scope(engine) as session:
        for run in session.scalars(select(SyncRun)):
            run.started_at = NOW - by


def test_disconnecting_forgets_the_sign_in_but_keeps_the_data(client, engine):
    headers = signed_in(client, engine)
    connect(client, headers)
    wait_for_sync()
    status = client.post("/google/disconnect", headers=headers).json()
    assert status["status"] == "none"
    assert stored_days(engine)[2] > 0


def test_an_expired_google_sign_in_asks_to_connect_again(client, engine, box, monkeypatch):
    headers = signed_in(client, engine)
    connect(client, headers)
    wait_for_sync()

    def refuse(self, request):
        raise RefreshError("invalid_grant")

    with session_scope(engine) as session:
        user = session.scalar(select(User))
        stale = credentials()
        stale.expiry = datetime(2020, 1, 1)
        session.get(GoogleConnection, user.id).encrypted_token = box.seal(stale)
    monkeypatch.setattr(Credentials, "refresh", refuse)

    with session_scope(engine) as session, pytest.raises(ReconnectNeeded):
        connections.credentials_for(session, box, session.scalar(select(User)).id)
    status = client.get("/google/status", headers=headers).json()
    assert status["status"] == "reconnect_needed"


# The pieces


def test_the_first_sync_plan_covers_the_history_in_chunks_newest_first():
    ranges = plan(None, lambda: date(2026, 1, 1), TODAY)
    assert ranges[0][1] == TODAY + timedelta(days=1)
    assert ranges[-1][0] == date(2026, 1, 1)
    assert all(newer[0] == older[1] for newer, older in zip(ranges, ranges[1:], strict=False))
    assert all((end - start).days <= connections.CHUNK_DAYS for start, end in ranges)


def test_a_later_sync_plan_rereads_recent_days_through_today():
    assert plan(date(2026, 10, 20), lambda: pytest.fail("no search needed"), TODAY) == [
        (date(2026, 10, 17), TODAY + timedelta(days=1))
    ]


def test_finding_the_first_day_stops_at_an_empty_window_or_the_cap():
    health = FakeHealth(None)
    assert first_day(health, TODAY) <= HISTORY_START
    assert first_day(health, TODAY) > HISTORY_START - timedelta(days=90)

    class Endless(FakeHealth):
        def daily_rollup(self, data_type, start, end):
            self.rollups.append((start, end))
            return [{}]

    endless = Endless(None)
    first_day(endless, TODAY)
    assert len(endless.rollups) == connections.MAX_HISTORY_YEARS * 4


def test_tokens_need_a_key_and_the_right_one(box):
    with pytest.raises(NotConfigured):
        TokenBox(None)
    sealed = box.seal(credentials())
    other = TokenBox(SecretStr(Fernet.generate_key().decode()))
    with pytest.raises(ReconnectNeeded):
        other.open(sealed)


def test_a_partly_granted_sign_in_is_accepted(monkeypatch):
    """Google lets people untick permissions; oauthlib then raises unless told to accept it."""
    import os

    from google_auth_oauthlib.flow import Flow

    monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)
    seen = {}

    def fetch(self, **kwargs):
        seen["relaxed"] = os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")

    monkeypatch.setattr(Flow, "fetch_token", fetch)
    monkeypatch.setattr(Flow, "credentials", property(lambda self: credentials()))
    oauth = connections.GoogleOAuth(
        connections.OAuthClient("client-id", "client-secret"), "http://127.0.0.1:8000/cb"
    )
    oauth.exchange("code", "verifier")
    assert seen["relaxed"] == "1"


def test_a_sync_refused_before_any_day_is_shown_as_failed(engine, box):
    """Regression: when Google refused the first request (here: a sign-in carrying a scope the
    Health API does not allow), nothing was recorded, so the app kept saying the data was on its
    way. Now a failed run says why."""
    from app.sync.client import ApiError

    class Refused:
        def __init__(self, token):
            pass

        def daily_rollup(self, data_type, start, end):
            raise ApiError("Google Health denied access (disallowed OAuth scope).", 403)

    with session_scope(engine) as session:
        person = User(email="p@example.com", status="approved")
        session.add(person)
        session.flush()
        connections.save_connection(session, box, person.id, credentials())
        person_id = person.id
    connections.sync(lambda: session_scope(engine), box, person_id, Refused, TODAY)
    with session_scope(engine) as session:
        run = session.scalar(select(SyncRun).where(SyncRun.user_id == person_id))
        assert run.status == "failed" and "denied access" in run.error
        shown = connections.status(session, person_id)
    assert "denied access" in shown["last_error"]
