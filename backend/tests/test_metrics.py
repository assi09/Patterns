"""The operations page: totals over the pilot's people for admins only, with nothing that names a
person or repeats what they wrote. Built on the pilot report's own made-up data."""

from datetime import UTC, datetime, time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from test_pilot_report import SECRET, SINCE, UNTIL, engine, pilot  # noqa: F401 (fixtures)

from app.api import metrics as ops
from app.db.models import Spend, User
from app.db.session import session_scope

NOW = datetime.combine(UNTIL, time(20), UTC)
DAYS = (UNTIL - SINCE).days + 1


def test_the_page_counts_the_pilot_and_leaves_the_owner_out(pilot, engine):  # noqa: F811
    with session_scope(engine) as db:
        first = db.scalar(select(User).where(User.email == "first@example.com"))
        owner = db.scalar(select(User).where(User.email == "owner@example.com"))
        db.add(Spend(user_id=first.id, kind="answer", cost_usd=0.03, at=NOW - timedelta(hours=1)))
        db.add(Spend(user_id=owner.id, kind="answer", cost_usd=0.5, at=NOW - timedelta(hours=1)))
    with session_scope(engine) as db:
        found = ops.metrics(db, NOW, DAYS, include_admins=False)
    approved = db.scalars(select(User).where(User.status == "approved")).all()
    assert found["people"]["approved"] == len(approved) - 1  # everyone but the owner
    assert len(found["days"]) == DAYS
    assert (
        sum(d["answers"] for d in found["days"])
        == found["chat"]["answers"] + found["chat"]["untraced_answers"]
    )
    last = found["days"][-1]
    assert last["day"] == UNTIL.isoformat() and last["cost_usd"] == 0.03  # the owner's 0.5 is not
    spend = found["spend"]
    assert spend["today_usd"] == 0.53  # the daily cap counts everyone, the owner too
    assert spend["highest_person_today_usd"] == 0.03
    assert "per_person" not in found["chat"]
    with_owner = ops.metrics(db, NOW, DAYS, include_admins=True)
    assert with_owner["chat"]["answers"] == found["chat"]["answers"] + 1


def test_nothing_on_the_page_names_a_person_or_repeats_their_words(pilot, engine):  # noqa: F811
    with session_scope(engine) as db:
        text = str(ops.metrics(db, NOW, DAYS, include_admins=True))
    for secret in ("@example.com", SECRET, "person 1"):
        assert secret not in text


def test_only_admins_see_it(pilot, engine, monkeypatch):  # noqa: F811
    from app.api import auth
    from app.api.main import create_app
    from app.auth import accounts

    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[auth.now] = lambda: NOW
    client = TestClient(app)

    def headers(email):
        with session_scope(engine) as session:
            user = session.scalar(select(User).where(User.email == email))
            user.status = "approved"
            accounts.set_password(session, user, "correct horse battery")
        token = client.post(
            "/auth/login", json={"email": email, "password": "correct horse battery"}
        ).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    member = client.get("/admin/metrics", headers=headers("first@example.com"))
    assert member.status_code == 403
    page = client.get(f"/admin/metrics?days={DAYS}", headers=headers("owner@example.com"))
    assert page.status_code == 200 and page.json()["period"]["days"] == DAYS
    body = page.json()
    assert "successRate" in body["chat"] and "todayCapUsd" in body["spend"]
    assert "failed_checks" in body["chat"]["outcomes"]  # data keys are left as they are
    assert (
        client.get("/admin/metrics?days=99", headers=headers("owner@example.com")).status_code
        == 422
    )
