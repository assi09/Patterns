"""Check-in alerts (docs/escalation.md): the rule over many synthetic people, then the flow from
consent to HR and the supervisor, and what each person may and may not see."""

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.analysis.day import with_scores
from app.api import auth
from app.api.main import create_app
from app.auth import accounts
from app.db.daily import save_daily
from app.db.models import CheckinAlert, CheckinEvent, CheckinMark, Notification, Team, User
from app.db.session import session_scope
from app.synthetic import LowWear, Step, generate
from app.teams import checkin, memberships

NOW = datetime(2026, 10, 26, 9, tzinfo=UTC)
TODAY = NOW.date()
PASSWORD = "correct horse battery"
WEEK_START = TODAY - timedelta(days=6)
# A sustained, extreme change in two signals over the whole last week.
EXTREME = (Step("sleep_minutes", WEEK_START, -180.0), Step("hrv_ms", WEEK_START, -30.0))


def frame(effects=(), seed=0, days=90):
    return with_scores(generate(TODAY - timedelta(days=days - 1), days, effects, seed=seed).frame)


# The rule


def test_calm_people_almost_never_raise_one():
    """Over 100 calm people and 100 weekly windows each, the rule fires on fewer than 0.5% of
    windows: under one alert per person every four years at one check a week."""
    raised = windows = 0
    for seed in range(100):
        data = frame(seed=seed, days=400)
        for end in range(60, 400, 3):
            cut = data.iloc[: end + 1]
            windows += 1
            raised += bool(checkin.detect(cut, cut.index.max().date()))
    assert windows >= 10_000
    assert raised / windows < 0.005, raised / windows


def test_a_sustained_extreme_change_is_found():
    found = sum(bool(checkin.detect(frame(EXTREME, seed), TODAY)) for seed in range(100))
    assert found >= 95, found


def test_the_evidence_names_each_signal_and_its_usual_range():
    evidence = checkin.detect(frame(EXTREME, 3), TODAY)
    metrics = {e.metrics[0] for e in evidence}
    assert {"sleep_minutes", "hrv_ms"} <= metrics
    for e in evidence:
        assert e.stats["days_far"] >= checkin.DAYS_FAR
        assert e.windows[1].end == TODAY and e.windows[1].days == 7
        assert e.windows[0].days == 28


@pytest.mark.parametrize(
    "effects",
    [
        (Step("sleep_minutes", WEEK_START, -180.0),),  # one signal only
        (Step("sleep_minutes", TODAY, -300.0), Step("hrv_ms", TODAY, -40.0)),  # one bad night
        (Step("sleep_minutes", TODAY - timedelta(days=2), -180.0),)
        + (Step("hrv_ms", TODAY - timedelta(days=2), -30.0),),  # three days, not five
    ],
)
def test_one_signal_or_a_short_spell_is_not_enough(effects):
    found = sum(bool(checkin.detect(frame(effects, seed), TODAY)) for seed in range(30))
    assert found <= 1, found


def test_a_barely_worn_week_raises_nothing():
    effects = EXTREME + (LowWear(WEEK_START, TODAY, wear_minutes=300),)
    assert not any(checkin.detect(frame(effects, seed), TODAY) for seed in range(20))


def test_old_data_raises_nothing():
    data = frame(EXTREME, 1)
    assert checkin.detect(data, TODAY + timedelta(days=3)) == []


def test_too_little_history_raises_nothing():
    assert checkin.detect(frame(EXTREME, 1, days=20), TODAY) == []


def test_no_language_model_is_involved():
    with open(checkin.__file__) as file:
        source = file.read()
    assert "llm" not in source.lower().replace("fulfil", "")
    assert "app.agent" not in source


# The flow


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


@pytest.fixture
def client(engine):
    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[auth.now] = lambda: NOW
    return TestClient(app)


def make_team(engine, consenting=(0, 2, 3, 4, 5), extreme=(0, 1)) -> str:
    """Boss supervises six members, HR is the contact. Members 0 and 1 had an extreme week;
    member 1 never agreed to check-in alerts."""
    start = TODAY - timedelta(days=89)
    with session_scope(engine) as db:
        boss = User(email="boss@example.com", status="approved", role="supervisor")
        hr = User(email="hr@example.com", status="approved", role="hr")
        db.add_all([boss, hr])
        db.flush()
        team = memberships.create_team(db, boss, "Design", None, NOW)
        team.hr_id = hr.id
        for i in range(6):
            person = User(email=f"member{i:02d}@example.com", status="approved")
            db.add(person)
            db.flush()
            effects = EXTREME if i in extreme else ()
            save_daily(db, person.id, "google_health", generate(start, 90, effects, seed=i).frame)
            membership = memberships.join(db, team, person, NOW - timedelta(days=60))
            if i in consenting:
                checkin.set_consent(db, membership, team, True, NOW - timedelta(days=60))
        return str(team.id)


def signed_in(client: TestClient, engine, email: str) -> dict:
    with session_scope(engine) as db:
        user = db.scalar(select(User).where(User.email == email))
        accounts.set_password(db, user, PASSWORD)
    token = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def raise_now(engine, team_id: str, when=NOW) -> int:
    with session_scope(engine) as db:
        return checkin.raise_for_team(db, db.get(Team, uuid.UUID(team_id)), when)


def send(engine, when) -> int:
    with session_scope(engine) as db:
        return checkin.send_due(db, when)


def inbox(engine, email: str) -> list[Notification]:
    with session_scope(engine) as db:
        user = db.scalar(select(User).where(User.email == email))
        rows = db.scalars(select(Notification).where(Notification.user_id == user.id)).all()
        db.expunge_all()
        return list(rows)


def test_only_the_person_who_agreed_gets_one_and_is_told_first(engine, client):
    team_id = make_team(engine)
    assert raise_now(engine, team_id) == 1  # member 1 had the same week but never agreed
    told = inbox(engine, "member00@example.com")
    assert [n.title for n in told] == [checkin.PERSON_TITLE]
    assert inbox(engine, "boss@example.com") == [] and inbox(engine, "hr@example.com") == []

    mine = client.get("/me/checkins", headers=signed_in(client, engine, "member00@example.com"))
    [alert] = mine.json()
    assert alert["status"] == "waiting"
    assert len(alert["evidence"]) >= 2
    assert "hr@example.com" in alert["recipients"] and "boss@example.com" in alert["recipients"]


def test_after_the_wait_hr_and_the_supervisor_are_asked_to_check_in_and_nothing_more(
    engine, client
):
    team_id = make_team(engine)
    raise_now(engine, team_id)
    assert send(engine, NOW + timedelta(hours=23)) == 0
    assert send(engine, NOW + timedelta(hours=25)) == 1
    for email in ("boss@example.com", "hr@example.com"):
        [note] = inbox(engine, email)
        assert note.title == "Please check in with member00@example.com"
        text = (note.title + note.body).lower()
        for word in ("sleep", "hrv", "heart", "recovery", "stress", "minutes", "below", "above"):
            assert word not in text
        body = note.body.replace("member00@example.com", "")
        assert not any(ch.isdigit() for ch in body)  # no value, date or count
        seen = client.get("/checkins", headers=signed_in(client, engine, email)).json()
        assert len(seen) == 1
        assert seen[0]["person"] == "member00@example.com"
        assert "evidence" not in seen[0]


def test_nobody_else_sees_or_marks_it(engine, client):
    team_id = make_team(engine)
    raise_now(engine, team_id)
    send(engine, NOW + timedelta(hours=25))
    hr = signed_in(client, engine, "hr@example.com")
    alert_id = client.get("/checkins", headers=hr).json()[0]["id"]
    for email in ("member02@example.com", "member00@example.com"):
        other = signed_in(client, engine, email)
        assert client.get("/checkins", headers=other).json() == []
        response = client.post(
            f"/checkins/{alert_id}/mark", headers=other, json={"outcome": "checked_in"}
        )
        assert response.status_code == 404


def test_marks_and_every_step_are_logged(engine, client):
    team_id = make_team(engine)
    raise_now(engine, team_id)
    send(engine, NOW + timedelta(hours=25))
    hr = signed_in(client, engine, "hr@example.com")
    alert_id = client.get("/checkins", headers=hr).json()[0]["id"]
    client.post(f"/checkins/{alert_id}/open", headers=hr)
    marked = client.post(
        f"/checkins/{alert_id}/mark", headers=hr, json={"outcome": "checked_in", "note": "Talked"}
    ).json()
    assert marked["mine"] == {
        "role": "hr",
        "outcome": "checked_in",
        "markedAt": marked["mine"]["markedAt"],
    }
    boss = client.get("/checkins", headers=signed_in(client, engine, "boss@example.com")).json()
    assert boss[0]["others"][0]["outcome"] == "checked_in"
    assert boss[0]["note"] is None  # HR's note is HR's
    with session_scope(engine) as db:
        events = [
            e.event for e in db.scalars(select(CheckinEvent).order_by(CheckinEvent.created_at))
        ]
    # The test client's clock stays at NOW, so compare what was logged rather than its order.
    assert sorted(events) == sorted(["raised", "sent", "opened", "marked"])


def test_the_person_can_stop_it_while_it_waits(engine, client):
    team_id = make_team(engine)
    raise_now(engine, team_id)
    me = signed_in(client, engine, "member00@example.com")
    alert_id = client.get("/me/checkins", headers=me).json()[0]["id"]
    stopped = client.post(f"/me/checkins/{alert_id}/withdraw", headers=me).json()
    assert stopped["status"] == "withdrawn"
    assert send(engine, NOW + timedelta(hours=25)) == 0
    assert inbox(engine, "hr@example.com") == []
    teams = client.get("/me/teams", headers=me).json()
    assert teams[0]["checkinAlerts"] is False
    again = client.post(f"/me/checkins/{alert_id}/withdraw", headers=me)
    assert again.status_code == 409


def test_leaving_the_team_stops_it_too(engine, client):
    team_id = make_team(engine)
    raise_now(engine, team_id)
    me = signed_in(client, engine, "member00@example.com")
    assert client.post(f"/me/teams/{team_id}/leave", headers=me).status_code == 204
    assert send(engine, NOW + timedelta(hours=25)) == 0
    with session_scope(engine) as db:
        assert db.scalar(select(CheckinAlert.status)) == "withdrawn"


def test_one_alert_per_four_weeks(engine):
    team_id = make_team(engine)
    assert raise_now(engine, team_id) == 1
    assert raise_now(engine, team_id, NOW + timedelta(days=1)) == 0


def test_without_an_hr_contact_only_the_supervisor_gets_it(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        db.get(Team, uuid.UUID(team_id)).hr_id = None
    raise_now(engine, team_id)
    send(engine, NOW + timedelta(hours=25))
    with session_scope(engine) as db:
        assert [m.role for m in db.scalars(select(CheckinMark))] == ["supervisor"]


def test_an_unmarked_alert_is_shown_once_more(engine):
    team_id = make_team(engine)
    raise_now(engine, team_id)
    send(engine, NOW + timedelta(hours=25))
    with session_scope(engine) as db:
        assert checkin.remind_due(db, NOW + timedelta(days=2)) == 0
        assert checkin.remind_due(db, NOW + timedelta(days=5)) == 1
        assert checkin.remind_due(db, NOW + timedelta(days=9)) == 0
    assert len(inbox(engine, "hr@example.com")) == 2


def test_consent_needs_the_current_text(engine, client):
    team_id = make_team(engine, consenting=())
    me = signed_in(client, engine, "member03@example.com")
    stale = client.post(
        f"/me/teams/{team_id}/checkin", headers=me, json={"share": True, "consentVersion": "old"}
    )
    assert stale.status_code == 409
    [membership] = client.get("/me/teams", headers=me).json()
    assert "hr@example.com" in membership["checkinConsent"]
    on = client.post(
        f"/me/teams/{team_id}/checkin",
        headers=me,
        json={"share": True, "consentVersion": membership["checkinConsentVersion"]},
    )
    assert on.json()["checkinAlerts"] is True


def test_the_supervisor_names_an_hr_account_and_nothing_else(engine, client):
    team_id = make_team(engine)
    boss = signed_in(client, engine, "boss@example.com")
    ok = client.put(f"/teams/{team_id}/hr", headers=boss, json={"email": "HR@example.com"})
    assert ok.json() == {"email": "hr@example.com"}
    member = client.put(
        f"/teams/{team_id}/hr", headers=boss, json={"email": "member02@example.com"}
    )
    assert member.status_code == 404
    someone = signed_in(client, engine, "member02@example.com")
    refused = client.put(f"/teams/{team_id}/hr", headers=someone, json={"email": None})
    assert refused.status_code == 403
    assert client.put(f"/teams/{team_id}/hr", headers=boss, json={"email": None}).json() == {
        "email": None
    }


def test_hr_sees_no_team_reports(engine, client):
    team_id = make_team(engine)
    hr = signed_in(client, engine, "hr@example.com")
    assert client.get(f"/teams/{team_id}", headers=hr).status_code == 403


def test_numbers_are_finite():
    for e in checkin.detect(frame(EXTREME, 5), TODAY):
        assert all(np.isfinite(v) for v in e.stats.values() if isinstance(v, float))
