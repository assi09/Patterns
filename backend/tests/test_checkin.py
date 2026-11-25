"""Check-in alerts (docs/escalation.md): the rule over many synthetic people, then the flow from
consent to HR and the supervisor, and what each person may and may not see."""

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError

from app.analysis.day import with_scores
from app.api import auth
from app.api.main import create_app
from app.auth import accounts
from app.db.daily import save_daily
from app.db.models import (
    CheckinAlert,
    CheckinEvent,
    CheckinMark,
    Notification,
    Team,
    TeamMembership,
    User,
)
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


def test_days_without_a_recorded_wear_time_do_not_count_as_worn():
    """Only confirmed wear counts: other readings on a day without a wear time are not enough,
    because the rule can send a name to HR."""
    week = slice(pd.Timestamp(WEEK_START), pd.Timestamp(TODAY))
    for seed in range(20):
        data = frame(EXTREME, seed)
        unknown = data.copy()
        unknown.loc[week, "wear_minutes"] = np.nan  # sleep and heart readings stay
        assert checkin.detect(unknown, TODAY) == []
        assert checkin.detect(data.drop(columns="wear_minutes"), TODAY) == []
        three = data.copy()
        three.loc[
            pd.Timestamp(WEEK_START) : pd.Timestamp(WEEK_START + timedelta(days=2)), "wear_minutes"
        ] = np.nan
        assert checkin.detect(three, TODAY) == []  # four confirmed days are not five


def test_days_worn_reports_confirmed_wear_only():
    data = frame(EXTREME, 3)
    data.loc[pd.Timestamp(TODAY), "wear_minutes"] = np.nan
    evidence = checkin.detect(data, TODAY)
    assert evidence and all(e.stats["days_worn"] == 6 for e in evidence)


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
    # Consent is to roles, so the person reads the roles, never who holds them.
    assert alert["recipients"] == "your supervisor and the team's HR contact"
    assert "@" not in alert["recipients"]


def test_after_the_wait_hr_and_the_supervisor_are_asked_to_check_in_and_nothing_more(
    engine, client
):
    team_id = make_team(engine)
    raise_now(engine, team_id)
    assert send(engine, NOW + timedelta(minutes=59)) == 0
    assert send(engine, NOW + timedelta(minutes=61)) == 1
    for email in ("boss@example.com", "hr@example.com"):
        [note] = inbox(engine, email)
        assert note.title == "You have a check-in request"
        text = (note.title + note.body).lower()
        assert "member00" not in text  # the name only behind the role check on Check-ins
        for word in ("sleep", "hrv", "heart", "recovery", "stress", "minutes", "below", "above"):
            assert word not in text
        assert not any(ch.isdigit() for ch in text)  # no value, date or count
        seen = client.get("/checkins", headers=signed_in(client, engine, email)).json()
        assert len(seen) == 1
        assert seen[0]["person"] == "member00@example.com"
        assert "evidence" not in seen[0]


def test_nobody_else_sees_or_marks_it(engine, client):
    team_id = make_team(engine)
    raise_now(engine, team_id)
    send(engine, NOW + timedelta(minutes=61))
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
    send(engine, NOW + timedelta(minutes=61))
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
    stopped = client.post(f"/me/checkins/{alert_id}/stop", headers=me).json()
    assert stopped["status"] == "withdrawn"
    assert send(engine, NOW + timedelta(minutes=61)) == 0
    assert inbox(engine, "hr@example.com") == []
    teams = client.get("/me/teams", headers=me).json()
    assert teams[0]["checkinAlerts"] is True  # stops this alert only; the switch stays on
    again = client.post(f"/me/checkins/{alert_id}/stop", headers=me)
    assert again.status_code == 409
    other = signed_in(client, engine, "member02@example.com")
    assert client.post(f"/me/checkins/{alert_id}/stop", headers=other).status_code == 404


def test_the_person_can_send_it_now(engine, client):
    team_id = make_team(engine)
    raise_now(engine, team_id)
    me = signed_in(client, engine, "member00@example.com")
    alert_id = client.get("/me/checkins", headers=me).json()[0]["id"]
    other = signed_in(client, engine, "member02@example.com")
    assert client.post(f"/me/checkins/{alert_id}/send", headers=other).status_code == 404
    sent = client.post(f"/me/checkins/{alert_id}/send", headers=me).json()
    assert sent["status"] == "sent"
    assert len(inbox(engine, "hr@example.com")) == 1 and len(inbox(engine, "boss@example.com")) == 1
    assert client.post(f"/me/checkins/{alert_id}/send", headers=me).status_code == 409
    assert send(engine, NOW + timedelta(minutes=61)) == 0  # never twice
    assert len(inbox(engine, "hr@example.com")) == 1


def test_the_person_is_told_the_exact_time_one_hour_later(engine, client):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        db.scalar(select(User).where(User.email == "member00@example.com")).timezone = "Asia/Beirut"
    raise_now(engine, team_id)  # NOW is 09:00 UTC, 11:00 in Beirut
    [note] = inbox(engine, "member00@example.com")
    assert "At 12:00 (Asia/Beirut), one hour from now" in note.body
    me = signed_in(client, engine, "member00@example.com")
    [alert] = client.get("/me/checkins", headers=me).json()
    assert alert["sendAfter"].startswith("2026-10-26T10:00")


def test_the_consent_says_one_hour():
    assert "one hour later" in checkin.CONSENT_TEXT
    assert timedelta(hours=1) == checkin.WAIT


def test_repeat_syncs_neither_restart_the_hour_nor_send_twice(engine):
    make_team(engine)
    with session_scope(engine) as db:
        person = db.scalar(select(User).where(User.email == "member00@example.com"))
        person_id = person.id
        assert checkin.after_sync(db, person_id, NOW) == 1
    for later in (timedelta(minutes=20), timedelta(minutes=50)):
        with session_scope(engine) as db:
            assert checkin.after_sync(db, person_id, NOW + later) == 0
    with session_scope(engine) as db:
        [alert] = db.scalars(select(CheckinAlert)).all()
        assert alert.send_after.replace(tzinfo=UTC) == NOW + checkin.WAIT  # not restarted
    assert send(engine, NOW + timedelta(minutes=61)) == 1
    with session_scope(engine) as db:
        assert checkin.after_sync(db, person_id, NOW + timedelta(hours=2)) == 0
    assert send(engine, NOW + timedelta(hours=3)) == 0
    assert len(inbox(engine, "hr@example.com")) == 1


def test_the_database_holds_one_waiting_alert_per_person(engine):
    team_id = make_team(engine)
    raise_now(engine, team_id)
    with pytest.raises(IntegrityError), session_scope(engine) as db:
        first = db.scalar(select(CheckinAlert))
        db.add(
            CheckinAlert(
                team_id=first.team_id,
                user_id=first.user_id,
                rule=checkin.RULE,
                last_day=first.last_day,
                evidence=[],
                status="waiting",
                raised_at=NOW,
                send_after=NOW,
            )
        )
        db.flush()


@pytest.mark.parametrize("synced", [True, False])
def test_the_rule_runs_after_a_successful_sync_only(engine, monkeypatch, synced):
    from app.api import google as google_api
    from app.db.models import SyncRun

    make_team(engine)
    with session_scope(engine) as db:
        person_id = db.scalar(select(User.id).where(User.email == "member00@example.com"))

    def fake_sync(sessions, box, user_id, health_for, today):
        if synced:
            with sessions() as db:
                db.add(
                    SyncRun(
                        user_id=user_id,
                        source="google_health",
                        status="succeeded",
                        range_start=today,
                        range_end=today,
                        started_at=datetime.now(UTC),
                        finished_at=datetime.now(UTC),
                    )
                )

    monkeypatch.setattr(google_api.connections, "sync", fake_sync)
    monkeypatch.setattr(google_api.connections, "now_utc", lambda: NOW)  # the data's own today
    parts = google_api.GoogleParts(None, None, None)
    google_api.sync_health(parts, lambda: session_scope(engine), person_id, TODAY)
    with session_scope(engine) as db:
        assert len(db.scalars(select(CheckinAlert)).all()) == (1 if synced else 0)


def test_leaving_the_team_stops_it_too(engine, client):
    team_id = make_team(engine)
    raise_now(engine, team_id)
    me = signed_in(client, engine, "member00@example.com")
    assert client.post(f"/me/teams/{team_id}/leave", headers=me).status_code == 204
    assert send(engine, NOW + timedelta(minutes=61)) == 0
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
    send(engine, NOW + timedelta(minutes=61))
    with session_scope(engine) as db:
        assert [m.role for m in db.scalars(select(CheckinMark))] == ["supervisor"]


def test_an_unmarked_alert_is_shown_once_more(engine):
    team_id = make_team(engine)
    raise_now(engine, team_id)
    send(engine, NOW + timedelta(minutes=61))
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
    assert "the team's HR contact" in membership["checkinConsent"]
    assert "@" not in membership["checkinConsent"]
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
    assert ok.json() == {"email": "hr@example.com", "invited": False}
    member = client.put(
        f"/teams/{team_id}/hr", headers=boss, json={"email": "member02@example.com"}
    )
    assert member.status_code == 409 and member.json()["error"]["code"] == "not_hr"
    someone = signed_in(client, engine, "member02@example.com")
    refused = client.put(f"/teams/{team_id}/hr", headers=someone, json={"email": None})
    assert refused.status_code == 403
    assert client.put(f"/teams/{team_id}/hr", headers=boss, json={"email": None}).json() == {
        "email": None,
        "invited": False,
    }


def test_hr_sees_no_team_reports(engine, client):
    team_id = make_team(engine)
    hr = signed_in(client, engine, "hr@example.com")
    assert client.get(f"/teams/{team_id}", headers=hr).status_code == 403


def test_numbers_are_finite():
    for e in checkin.detect(frame(EXTREME, 5), TODAY):
        assert all(np.isfinite(v) for v in e.stats.values() if isinstance(v, float))


# Leaving the role


def replace_hr(engine, team_id: str, new_email: str = "new.hr@example.com") -> None:
    with session_scope(engine) as db:
        new = User(email=new_email, status="approved", role="hr")
        db.add(new)
        db.flush()
        db.get(Team, uuid.UUID(team_id)).hr_id = new.id


def demote_hr(engine, team_id: str) -> None:
    with session_scope(engine) as db:
        db.scalar(select(User).where(User.email == "hr@example.com")).role = "member"


@pytest.mark.parametrize("leave", [replace_hr, demote_hr])
def test_a_former_hr_contact_loses_access_at_once_and_gets_no_reminder(engine, client, leave):
    """Regression: an alert is sent, then HR changes. The former contact can no longer list,
    open or mark it, even with its id from before, and is not reminded; their delivery record
    stays for the audit, and the supervisor keeps full access."""
    team_id = make_team(engine)
    raise_now(engine, team_id)
    assert send(engine, NOW + timedelta(minutes=61)) == 1
    old = signed_in(client, engine, "hr@example.com")
    [before] = client.get("/checkins", headers=old).json()
    alert_id = before["id"]

    leave(engine, team_id)

    assert client.get("/checkins", headers=old).json() == []
    assert client.post(f"/checkins/{alert_id}/open", headers=old).status_code == 404
    marked = client.post(f"/checkins/{alert_id}/mark", headers=old, json={"outcome": "checked_in"})
    assert marked.status_code == 404

    with session_scope(engine) as db:
        assert checkin.remind_due(db, NOW + timedelta(days=5)) == 1  # the supervisor is reminded
    assert len(inbox(engine, "hr@example.com")) == 1  # only the first delivery, no reminder
    assert len(inbox(engine, "boss@example.com")) == 2

    with session_scope(engine) as db:
        former = db.scalar(select(User).where(User.email == "hr@example.com"))
        record = db.scalar(select(CheckinMark).where(CheckinMark.user_id == former.id))
        assert record is not None and record.role == "hr" and record.outcome is None
        acted = db.scalars(select(CheckinEvent).where(CheckinEvent.actor_id == former.id)).all()
        assert acted == []  # nothing they tried after leaving was logged as done

    boss = signed_in(client, engine, "boss@example.com")
    assert len(client.get("/checkins", headers=boss).json()) == 1
    assert (
        client.post(
            f"/checkins/{alert_id}/mark", headers=boss, json={"outcome": "checked_in"}
        ).status_code
        == 200
    )


def test_changing_who_is_hr_needs_no_fresh_consent(engine):
    team_id = make_team(engine)
    replace_hr(engine, team_id)
    with session_scope(engine) as db:
        consenting = db.scalars(
            select(TeamMembership).where(TeamMembership.checkin_alerts.is_(True))
        ).all()
        assert len(consenting) == 5  # nobody's consent was reset
    assert raise_now(engine, team_id) == 1
    send(engine, NOW + timedelta(minutes=61))
    assert [n.title for n in inbox(engine, "new.hr@example.com")] == ["You have a check-in request"]
    assert inbox(engine, "hr@example.com") == []


# A former recipient never learns the name


@pytest.mark.parametrize(
    ("demoted", "still_told"),
    [("hr@example.com", "boss@example.com"), ("boss@example.com", "hr@example.com")],
)
def test_someone_demoted_during_the_hour_receives_nothing(engine, client, demoted, still_told):
    """Regression: the timer sent to the account saved on the team without checking that it still
    held its role, so a demoted HR contact or supervisor got the request."""
    team_id = make_team(engine)
    raise_now(engine, team_id)
    with session_scope(engine) as db:
        db.scalar(select(User).where(User.email == demoted)).role = "member"
    assert send(engine, NOW + timedelta(minutes=61)) == 1
    assert inbox(engine, demoted) == []
    assert [n.title for n in inbox(engine, still_told)] == ["You have a check-in request"]
    with session_scope(engine) as db:
        gone = db.scalar(select(User).where(User.email == demoted))
        assert db.scalar(select(CheckinMark).where(CheckinMark.user_id == gone.id)) is None
    assert client.get("/checkins", headers=signed_in(client, engine, demoted)).json() == []


def test_a_former_hr_contact_cannot_read_the_name_in_their_inbox(engine, client):
    """Regression: the inbox kept the original notification, which named the person."""
    team_id = make_team(engine)
    raise_now(engine, team_id)
    send(engine, NOW + timedelta(minutes=61))
    replace_hr(engine, team_id)
    old = signed_in(client, engine, "hr@example.com")
    shown = client.get("/notifications", headers=old)
    assert shown.status_code == 200 and shown.json()["items"]  # their inbox still works
    assert "member00" not in shown.text
    assert client.get("/checkins", headers=old).json() == []


def test_leaving_the_team_withdraws_at_once_and_send_now_refuses(engine, client):
    """Regression: leaving left the alert waiting until its hour ended, and Send now on an old
    screen still sent it to the former supervisor."""
    team_id = make_team(engine)
    raise_now(engine, team_id)
    me = signed_in(client, engine, "member00@example.com")
    alert_id = client.get("/me/checkins", headers=me).json()[0]["id"]
    assert client.post(f"/me/teams/{team_id}/leave", headers=me).status_code == 204
    with session_scope(engine) as db:
        assert db.scalar(select(CheckinAlert.status)) == "withdrawn"  # before any timer runs
    assert client.post(f"/me/checkins/{alert_id}/send", headers=me).status_code == 409
    assert inbox(engine, "boss@example.com") == [] and inbox(engine, "hr@example.com") == []


def test_send_now_rechecks_membership_and_consent(engine, client):
    """Even if a waiting alert survived a lapse in consent, Send now checks again and sends
    nothing."""
    team_id = make_team(engine)
    raise_now(engine, team_id)
    me = signed_in(client, engine, "member00@example.com")
    alert_id = client.get("/me/checkins", headers=me).json()[0]["id"]
    with session_scope(engine) as db:  # consent off without the usual withdrawal
        person = db.scalar(select(User).where(User.email == "member00@example.com"))
        db.scalar(
            select(TeamMembership).where(TeamMembership.user_id == person.id)
        ).checkin_alerts = False
    refused = client.post(f"/me/checkins/{alert_id}/send", headers=me)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "not_in_team"
    assert inbox(engine, "boss@example.com") == [] and inbox(engine, "hr@example.com") == []
    assert send(engine, NOW + timedelta(minutes=1)) == 0
    with session_scope(engine) as db:
        assert db.scalar(select(CheckinAlert.status)) == "waiting"  # its hour is not up yet
    assert send(engine, NOW + timedelta(minutes=61)) == 0  # when it is, withdrawn and unsent
    with session_scope(engine) as db:
        assert db.scalar(select(CheckinAlert.status)) == "withdrawn"
    assert inbox(engine, "boss@example.com") == [] and inbox(engine, "hr@example.com") == []


def test_a_supervisor_demoted_after_sending_loses_access_at_once(engine, client):
    """Regression: later access checked only the team assignment for supervisors, so a demoted
    supervisor still assigned to the team could open and mark the named alert and be reminded.
    Delivery and access now use one rule (`current_holder`)."""
    team_id = make_team(engine)
    raise_now(engine, team_id)
    send(engine, NOW + timedelta(minutes=61))
    boss = signed_in(client, engine, "boss@example.com")
    alert_id = client.get("/checkins", headers=boss).json()[0]["id"]
    with session_scope(engine) as db:  # demoted; still assigned as the team's supervisor
        demoted = db.scalar(select(User).where(User.email == "boss@example.com"))
        demoted.role = "member"
        assert db.get(Team, uuid.UUID(team_id)).supervisor_id == demoted.id

    assert client.get("/checkins", headers=boss).json() == []
    assert client.post(f"/checkins/{alert_id}/open", headers=boss).status_code == 404
    marked = client.post(f"/checkins/{alert_id}/mark", headers=boss, json={"outcome": "checked_in"})
    assert marked.status_code == 404

    with session_scope(engine) as db:
        assert checkin.remind_due(db, NOW + timedelta(days=5)) == 1  # HR is reminded
    assert len(inbox(engine, "boss@example.com")) == 1  # the first notice only, no reminder
    assert len(inbox(engine, "hr@example.com")) == 2
    with session_scope(engine) as db:
        record = db.scalar(select(CheckinMark).where(CheckinMark.role == "supervisor"))
        assert record is not None and record.outcome is None  # the delivery record stays


def test_delivery_and_access_use_the_same_rule(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        for email, role in (("boss@example.com", "supervisor"), ("hr@example.com", "hr")):
            user = db.scalar(select(User).where(User.email == email))
            mark = CheckinMark(alert_id=uuid.uuid4(), user_id=user.id, role=role)
            for account_role in ("member", "supervisor", "hr"):
                user.role = account_role
                delivered = (user.id, role) in checkin._recipients(db, team)
                assert delivered == checkin.holds_role(db, mark, team) == (account_role == role)
