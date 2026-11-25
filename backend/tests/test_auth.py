from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api import auth
from app.api.main import create_app
from app.auth.accounts import AuthError, LoginThrottle
from app.auth.passwords import hash_password, verify_password
from app.config import settings
from app.db.models import AuthSession, User
from app.db.session import session_scope

OWNER = "owner@example.com"
PASSWORD = "correct horse battery"
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def client(engine, clock, monkeypatch) -> TestClient:
    monkeypatch.setattr(settings, "admin_emails", [OWNER.upper()])  # matched case-insensitively
    monkeypatch.setattr(auth, "throttle", LoginThrottle())
    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[auth.now] = clock
    return TestClient(app)


def sign_up(client, email: str, password: str = PASSWORD) -> dict:
    response = client.post("/auth/signup", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return response.json()


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def owner_token(client, engine) -> str:
    """The owner signs up, is approved directly in the database, and signs in."""
    sign_up(client, OWNER)
    with session_scope(engine) as session:
        session.scalar(select(User).where(User.email == OWNER)).status = "approved"
    response = client.post("/auth/login", json={"email": OWNER, "password": PASSWORD})
    return response.json()["token"]


# Passwords


def test_password_hashes_verify_and_are_salted():
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second
    assert verify_password(PASSWORD, first)
    assert not verify_password("wrong password!", first)


@pytest.mark.parametrize("stored", ["", "plain", "bcrypt$1$2$3$4$5", "scrypt$x$8$1$AA==$AA=="])
def test_malformed_hashes_never_verify(stored):
    assert not verify_password(PASSWORD, stored)


# Sign-up and log-in


def test_sign_up_creates_a_pending_account_that_is_signed_in(client, engine):
    body = sign_up(client, "  New.Person@Example.com ")
    assert body["account"] == {
        "email": "new.person@example.com",
        "status": "pending",
        "isAdmin": False,
        "role": "member",
        "personalFeatures": True,  # on for the tests (conftest.py); off by default
    }
    assert client.get("/auth/me", headers=headers(body["token"])).json()["status"] == "pending"
    with Session(engine) as session:
        user = session.scalar(select(User))
        assert user.password_hash.startswith("scrypt$")
        assert PASSWORD not in user.password_hash
        # Only the token's hash is stored.
        assert session.scalar(select(AuthSession.token_hash)) != body["token"]


@pytest.mark.parametrize(
    ("email", "password", "code"),
    [
        ("not-an-email", PASSWORD, "invalid_email"),
        ("a@b", PASSWORD, "invalid_email"),
        ("person@example.com", "short", "weak_password"),
        ("person@example.com", "x" * 129, "weak_password"),
    ],
)
def test_sign_up_rejects_bad_input_with_a_specific_message(client, email, password, code):
    response = client.post("/auth/signup", json={"email": email, "password": password})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_sign_up_refuses_an_email_that_exists_in_any_case(client):
    sign_up(client, "person@example.com")
    response = client.post(
        "/auth/signup", json={"email": "PERSON@example.com", "password": PASSWORD}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


def test_missing_fields_are_an_invalid_request(client):
    response = client.post("/auth/signup", json={"email": "person@example.com"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_log_in_gives_one_error_for_unknown_email_and_wrong_password(client):
    sign_up(client, "person@example.com")
    unknown = client.post("/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    wrong = client.post("/auth/login", json={"email": "person@example.com", "password": "nope" * 3})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_the_local_owner_without_a_password_cannot_log_in(client, engine):
    with session_scope(engine) as session:
        session.add(User(email="sync@example.com", status="approved"))
    response = client.post("/auth/login", json={"email": "sync@example.com", "password": PASSWORD})
    assert response.status_code == 401


def test_repeated_failures_lock_the_email_for_a_while(client, clock):
    sign_up(client, "person@example.com")
    wrong = {"email": "person@example.com", "password": "wrong password"}
    for _ in range(5):
        assert client.post("/auth/login", json=wrong).status_code == 401
    right = {"email": "person@example.com", "password": PASSWORD}
    locked = client.post("/auth/login", json=right)
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "too_many_attempts"
    clock.now += timedelta(minutes=16)
    assert client.post("/auth/login", json=right).status_code == 200


# Sessions


@pytest.mark.parametrize("value", [None, "", "Bearer", "Basic abc", "Bearer not-a-real-token"])
def test_me_needs_a_valid_bearer_token(client, value):
    response = client.get("/auth/me", headers={"Authorization": value} if value else {})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "signed_out"


def test_logging_out_ends_only_that_session(client):
    first = sign_up(client, "person@example.com")["token"]
    second = client.post(
        "/auth/login", json={"email": "person@example.com", "password": PASSWORD}
    ).json()["token"]
    assert client.post("/auth/logout", headers=headers(first)).status_code == 204
    assert client.get("/auth/me", headers=headers(first)).status_code == 401
    assert client.get("/auth/me", headers=headers(second)).status_code == 200


def test_sessions_expire(client, clock):
    token = sign_up(client, "person@example.com")["token"]
    clock.now += timedelta(days=settings.session_days, seconds=1)
    assert client.get("/auth/me", headers=headers(token)).status_code == 401


# Approval


def test_the_owner_sees_and_approves_requests(client, engine):
    token = owner_token(client, engine)
    assert client.get("/auth/me", headers=headers(token)).json()["isAdmin"] is True
    person = sign_up(client, "person@example.com")

    requests = client.get("/admin/access-requests", headers=headers(token)).json()
    assert [r["email"] for r in requests] == ["person@example.com"]

    approved = client.post(
        f"/admin/access-requests/{requests[0]['id']}/approve", headers=headers(token)
    )
    assert approved.json()["status"] == "approved"
    assert approved.json()["role"] == "member"  # approving without a role keeps a member
    assert client.get("/auth/me", headers=headers(person["token"])).json()["status"] == "approved"
    assert client.get("/admin/access-requests", headers=headers(token)).json() == []


def test_rejecting_signs_the_person_out(client, engine):
    token = owner_token(client, engine)
    person = sign_up(client, "person@example.com")
    request_id = client.get("/admin/access-requests", headers=headers(token)).json()[0]["id"]
    rejected = client.post(f"/admin/access-requests/{request_id}/reject", headers=headers(token))
    assert rejected.json()["status"] == "rejected"
    assert client.get("/auth/me", headers=headers(person["token"])).status_code == 401


def test_the_owner_approves_a_supervisor(client, engine):
    token = owner_token(client, engine)
    person = sign_up(client, "lead@example.com")
    request = client.get("/admin/access-requests", headers=headers(token)).json()[0]

    approved = client.post(
        f"/admin/access-requests/{request['id']}/approve",
        json={"role": "supervisor"},
        headers=headers(token),
    )
    assert approved.json()["role"] == "supervisor"
    assert client.get("/auth/me", headers=headers(person["token"])).json()["role"] == "supervisor"
    assert client.get("/teams", headers=headers(person["token"])).status_code == 200


def test_an_unknown_role_is_refused(client, engine):
    token = owner_token(client, engine)
    sign_up(client, "person@example.com")
    request = client.get("/admin/access-requests", headers=headers(token)).json()[0]
    response = client.post(
        f"/admin/access-requests/{request['id']}/approve",
        json={"role": "admin"},
        headers=headers(token),
    )
    assert response.status_code == 422
    assert client.get("/admin/access-requests", headers=headers(token)).json() != []


def test_only_an_approved_owner_is_an_admin(client, engine):
    # Signed up with the owner's email but not yet approved: not an admin.
    pending_owner = sign_up(client, OWNER)["token"]
    other = sign_up(client, "person@example.com")["token"]
    for token in (pending_owner, other):
        response = client.get("/admin/access-requests", headers=headers(token))
        assert response.status_code == 403


@pytest.mark.parametrize("user_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_deciding_an_unknown_request_is_not_found(client, engine, user_id):
    token = owner_token(client, engine)
    response = client.post(f"/admin/access-requests/{user_id}/approve", headers=headers(token))
    assert response.status_code == 404


def test_auth_errors_carry_a_status_code_and_message():
    error = AuthError(409, "email_taken", "An account with this email already exists.")
    assert (error.status, error.code, str(error)) == (409, "email_taken", error.message)


# Command line


def test_the_command_line_lists_and_approves_sign_ups(client, engine, monkeypatch, capsys):
    from app.auth import __main__ as cli

    monkeypatch.setattr(cli, "session_scope", lambda: session_scope(engine))
    sign_up(client, "person@example.com")

    assert cli.main(["pending"]) == 0
    assert "person@example.com" in capsys.readouterr().out
    assert cli.main(["approve", "Person@Example.com"]) == 0
    assert "approved" in capsys.readouterr().out
    assert cli.main(["pending"]) == 0
    assert "0 waiting" in capsys.readouterr().out
    assert cli.main(["reject", "nobody@example.com"]) == 1


def test_the_local_owner_claims_their_account_with_set_password(
    client, engine, monkeypatch, capsys
):
    from app.auth import __main__ as cli

    monkeypatch.setattr(cli, "session_scope", lambda: session_scope(engine))
    with session_scope(engine) as session:
        session.add(User(email="sync@example.com", status="approved"))
    login = {"email": "sync@example.com", "password": PASSWORD}
    assert client.post("/auth/login", json=login).status_code == 401

    answers = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))
    assert cli.main(["set-password", "sync@example.com"]) == 0
    assert PASSWORD not in capsys.readouterr().out
    assert client.post("/auth/login", json=login).status_code == 200


@pytest.mark.parametrize(("first", "second"), [(PASSWORD, "something else"), ("short", "short")])
def test_set_password_refuses_mismatches_and_weak_passwords(
    client, engine, monkeypatch, first, second
):
    from app.auth import __main__ as cli

    monkeypatch.setattr(cli, "session_scope", lambda: session_scope(engine))
    sign_up(client, "person@example.com")
    answers = iter([first, second])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))
    assert cli.main(["set-password", "person@example.com"]) == 1
    login = {"email": "person@example.com", "password": PASSWORD}
    assert client.post("/auth/login", json=login).status_code == 200  # unchanged


def test_setting_a_password_signs_out_every_device(client, engine, monkeypatch):
    from app.auth import __main__ as cli

    monkeypatch.setattr(cli, "session_scope", lambda: session_scope(engine))
    token = sign_up(client, "person@example.com")["token"]
    answers = iter(["a brand new password"] * 2)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(answers))
    assert cli.main(["set-password", "person@example.com"]) == 0
    assert client.get("/auth/me", headers=headers(token)).status_code == 401


# Who sees the data


@pytest.fixture
def owner_data(monkeypatch):
    from datetime import date

    from app.api import store
    from app.ingest.takeout import DailyData
    from app.synthetic import generate

    loaded = store.analyze(DailyData(frame=generate(date(2026, 7, 1), 30).frame), T0)
    monkeypatch.setattr(store, "_load", lambda: loaded)
    return loaded


DATA_PATHS = ["/data/status", "/reports/latest", "/evidence/unknown"]


@pytest.mark.parametrize("path", DATA_PATHS)
def test_data_needs_sign_in(client, owner_data, path):
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "signed_out"


@pytest.mark.parametrize("path", DATA_PATHS)
def test_pending_accounts_see_no_data(client, owner_data, path):
    token = sign_up(client, "person@example.com")["token"]
    response = client.get(path, headers=headers(token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_approved"


@pytest.mark.parametrize("path", DATA_PATHS)
def test_other_approved_accounts_never_see_the_owners_data(client, engine, owner_data, path):
    token = sign_up(client, "person@example.com")["token"]
    with session_scope(engine) as session:
        session.scalar(select(User).where(User.email == "person@example.com")).status = "approved"
    response = client.get(path, headers=headers(token))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "no_data"


def test_the_owner_sees_their_data(client, engine, owner_data):
    token = owner_token(client, engine)
    assert client.get("/data/status", headers=headers(token)).status_code == 200
    report = client.get("/reports/latest", headers=headers(token))
    assert report.status_code == 200
    evidence_id = next(iter(owner_data.evidence))
    assert client.get(f"/evidence/{evidence_id}", headers=headers(token)).status_code == 200


# Each person's own live data


def store_live(engine, email: str, start, days: int, seed: int = 0) -> None:
    from app.db.daily import save_daily
    from app.synthetic import generate

    frame = generate(start, days, seed=seed).frame
    with session_scope(engine) as session:
        user = session.scalar(select(User).where(User.email == email))
        save_daily(session, user.id, "google_health", frame)


def approve(engine, email: str) -> None:
    with session_scope(engine) as session:
        session.scalar(select(User).where(User.email == email)).status = "approved"


def test_an_approved_person_sees_their_own_live_data(client, engine, owner_data):
    from datetime import date

    token = sign_up(client, "person@example.com")["token"]
    approve(engine, "person@example.com")
    store_live(engine, "person@example.com", date(2026, 8, 1), 40)

    status = client.get("/data/status", headers=headers(token)).json()
    assert status["source"] == "google_health"
    assert status["range"] == {"start": "2026-08-01", "end": "2026-09-09"}
    assert client.get("/reports/latest", headers=headers(token)).status_code == 200


def test_two_people_never_see_each_others_data(client, engine, owner_data):
    from datetime import date

    first = sign_up(client, "first@example.com")["token"]
    second = sign_up(client, "second@example.com")["token"]
    for email in ("first@example.com", "second@example.com"):
        approve(engine, email)
    store_live(engine, "first@example.com", date(2026, 7, 1), 30, seed=1)
    store_live(engine, "second@example.com", date(2026, 9, 1), 20, seed=2)

    ranges = [
        client.get("/data/status", headers=headers(token)).json()["range"]
        for token in (first, second)
    ]
    assert ranges == [
        {"start": "2026-07-01", "end": "2026-07-30"},
        {"start": "2026-09-01", "end": "2026-09-20"},
    ]


def test_the_owner_uses_live_data_over_the_export_once_they_have_any(client, engine, owner_data):
    from datetime import date

    token = owner_token(client, engine)
    assert client.get("/data/status", headers=headers(token)).json()["source"] == "takeout"
    store_live(engine, OWNER, date(2026, 8, 1), 30)
    status = client.get("/data/status", headers=headers(token)).json()
    assert status["source"] == "google_health"  # never a mix of both
    assert status["range"]["start"] == "2026-08-01"


def test_the_owner_without_live_data_or_an_export_has_no_data(client, engine, monkeypatch):
    from app.api import store
    from app.ingest.takeout import IngestError

    def missing():
        raise IngestError("no export")

    monkeypatch.setattr(store, "_load", missing)
    token = owner_token(client, engine)
    response = client.get("/data/status", headers=headers(token))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "no_data"


def test_a_new_sync_replaces_the_cached_analysis(client, engine, owner_data):
    from datetime import date

    from app.db.models import SyncRun

    token = sign_up(client, "person@example.com")["token"]
    approve(engine, "person@example.com")
    store_live(engine, "person@example.com", date(2026, 8, 1), 30)
    before = client.get("/data/status", headers=headers(token)).json()

    store_live(engine, "person@example.com", date(2026, 8, 31), 10)
    finished = datetime(2026, 9, 10, 6, 0, tzinfo=UTC)
    with session_scope(engine) as session:
        user = session.scalar(select(User).where(User.email == "person@example.com"))
        session.add(
            SyncRun(
                user_id=user.id,
                source="google_health",
                status="succeeded",
                range_start=date(2026, 8, 31),
                range_end=date(2026, 9, 10),
                days_written=10,
                finished_at=finished,
            )
        )
    after = client.get("/data/status", headers=headers(token)).json()
    assert before["range"]["end"] == "2026-08-30"
    assert after["range"]["end"] == "2026-09-09"
    assert after["lastSync"].startswith("2026-09-10T06:00")


def test_an_invited_address_is_approved_at_sign_up_and_others_still_wait(client, monkeypatch):
    monkeypatch.setattr(
        settings, "invited_emails", ["invited.person@gmail.com", "guest@example.com"]
    )
    # Gmail ignores dots, capitals and +tags, so the same mailbox matches however it is typed.
    for email in ("Invited.Person@gmail.com", "GUEST@example.com"):
        token = sign_up(client, email)["token"]
        me = client.get("/auth/me", headers=headers(token)).json()
        assert me["status"] == "approved", email
    token = sign_up(client, "invitedperson+pilot@gmail.com")["token"]  # same Gmail mailbox
    assert client.get("/auth/me", headers=headers(token)).json()["status"] == "approved"
    token = sign_up(client, "stranger@example.com")["token"]
    assert client.get("/auth/me", headers=headers(token)).json()["status"] == "pending"


def test_dots_only_fold_for_gmail():
    from app.auth.accounts import mailbox

    assert mailbox(" A.B+x@GoogleMail.com ") == "ab@gmail.com"
    assert mailbox("a.b@example.com") == "a.b@example.com"  # other providers keep their dots
