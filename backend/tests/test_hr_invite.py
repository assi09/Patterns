"""Inviting a team's HR contact by email (app/teams/hr.py, docs/escalation.md): the link makes
the invited address an approved HR account for that team, and nothing else does."""

import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select
from test_checkin import NOW, PASSWORD, client, engine, make_team, raise_now, signed_in  # noqa: F401

from app.api import checkins
from app.db.models import HrInvite, Team, User
from app.db.session import session_scope
from app.email import Email, MailError
from app.teams import checkin


class Outbox:
    def __init__(self, fail: bool = False):
        self.sent: list[Email] = []
        self.fail = fail

    def send(self, email: Email) -> None:
        if self.fail:
            raise MailError("Email is not set up.")
        self.sent.append(email)


@pytest.fixture
def outbox(client):  # noqa: F811
    box = Outbox()
    client.app.dependency_overrides[checkins.get_mailer] = lambda: box
    return box


def no_hr(engine, team_id):  # noqa: F811
    with session_scope(engine) as db:
        db.get(Team, uuid.UUID(team_id)).hr_id = None


def invite(client, engine, team_id, email="new.hr@example.com"):  # noqa: F811
    boss = signed_in(client, engine, "boss@example.com")
    return client.put(f"/teams/{team_id}/hr", headers=boss, json={"email": email})


def token_in(email: Email) -> str:
    link = next(word for word in email.text.split() if "/sign-up?hr=" in word)
    return parse_qs(urlparse(link).query)["hr"][0]


def test_an_address_without_an_account_gets_an_invitation(client, engine, outbox):  # noqa: F811
    team_id = make_team(engine)
    no_hr(engine, team_id)
    response = invite(client, engine, team_id)
    assert response.json() == {"email": "new.hr@example.com", "invited": True}
    [email] = outbox.sent
    assert email.to == "new.hr@example.com" and "boss@example.com" in email.text
    with session_scope(engine) as db:  # the test clock is fixed in the past; today's is real
        db.scalar(select(HrInvite)).expires_at = NOW + timedelta(days=3650)
    boss = signed_in(client, engine, "boss@example.com")
    team = client.get(f"/teams/{team_id}", headers=boss).json()
    assert team["hrInvited"] == "new.hr@example.com" and team["hrEmail"] is None
    with session_scope(engine) as db:
        stored = db.scalar(select(HrInvite))
        assert stored.token_hash != token_in(email)  # only a hash is kept


def test_signing_up_through_the_link_makes_an_approved_hr_contact(client, engine, outbox):  # noqa: F811
    team_id = make_team(engine)
    no_hr(engine, team_id)
    invite(client, engine, team_id)
    token = token_in(outbox.sent[0])
    signed = client.post(
        "/auth/signup",
        json={"email": "New.HR@example.com", "password": PASSWORD, "hrInvite": token},
    ).json()
    assert signed["account"]["status"] == "approved" and signed["account"]["role"] == "hr"
    with session_scope(engine) as db:
        assert db.get(Team, uuid.UUID(team_id)).hr_id is not None
    again = client.post(
        "/auth/signup",
        json={"email": "second@example.com", "password": PASSWORD, "hrInvite": token},
    )
    assert again.status_code == 400  # used once


@pytest.mark.parametrize(
    ("email", "token", "code"),
    [
        ("someone.else@example.com", None, "invite_other_email"),  # the link went to new.hr
        ("new.hr@example.com", "made-up", "invite_invalid"),
    ],
)
def test_a_wrong_address_or_token_creates_no_account(client, engine, outbox, email, token, code):  # noqa: F811
    team_id = make_team(engine)
    invite(client, engine, team_id)
    response = client.post(
        "/auth/signup",
        json={"email": email, "password": PASSWORD, "hrInvite": token or token_in(outbox.sent[0])},
    )
    assert response.status_code == 400 and response.json()["error"]["code"] == code
    with session_scope(engine) as db:
        assert db.scalar(select(User).where(User.email == email)) is None


def test_an_expired_invitation_does_not_work(client, engine, outbox):  # noqa: F811
    team_id = make_team(engine)
    invite(client, engine, team_id)
    with session_scope(engine) as db:
        db.scalar(select(HrInvite)).expires_at = NOW - timedelta(minutes=1)
    response = client.post(
        "/auth/signup",
        json={
            "email": "new.hr@example.com",
            "password": PASSWORD,
            "hrInvite": token_in(outbox.sent[0]),
        },
    )
    assert response.json()["error"]["code"] == "invite_invalid"


def test_a_new_invitation_replaces_the_old_one(client, engine, outbox):  # noqa: F811
    team_id = make_team(engine)
    invite(client, engine, team_id, "first@example.com")
    invite(client, engine, team_id, "second@example.com")
    response = client.post(
        "/auth/signup",
        json={
            "email": "first@example.com",
            "password": PASSWORD,
            "hrInvite": token_in(outbox.sent[0]),
        },
    )
    assert response.status_code == 400


def test_an_existing_account_that_is_not_hr_is_never_converted(client, engine, outbox):  # noqa: F811
    team_id = make_team(engine)
    response = invite(client, engine, team_id, "member02@example.com")
    assert response.status_code == 409
    assert outbox.sent == []
    with session_scope(engine) as db:
        member = db.scalar(select(User).where(User.email == "member02@example.com"))
        assert member.role == "member"


def test_a_gmail_alias_is_its_own_account(client, engine, outbox):  # noqa: F811
    """ "+hr" and "+member" addresses of one mailbox are separate accounts here."""
    team_id = make_team(engine)
    with session_scope(engine) as db:
        db.add(User(email="lead@gmail.com", status="approved", role="supervisor"))
        db.add(User(email="lead+hr@gmail.com", status="approved", role="hr"))
    assert invite(client, engine, team_id, "lead+hr@gmail.com").json() == {
        "email": "lead+hr@gmail.com",
        "invited": False,
    }


def test_when_email_fails_the_supervisor_is_told(client, engine):  # noqa: F811
    client.app.dependency_overrides[checkins.get_mailer] = lambda: Outbox(fail=True)
    team_id = make_team(engine)
    response = invite(client, engine, team_id)
    assert response.status_code == 502


def test_recipients_are_emailed_without_the_persons_name(engine):  # noqa: F811
    team_id = make_team(engine)
    raise_now(engine, team_id)
    box = Outbox()
    with session_scope(engine) as db:
        checkin.send_due(db, NOW + timedelta(hours=25), box, "https://app.example")
    assert sorted(e.to for e in box.sent) == ["boss@example.com", "hr@example.com"]
    for email in box.sent:
        assert "member00" not in email.text + email.subject + email.html
        assert "https://app.example/checkins" in email.text


def test_a_failed_notice_email_does_not_stop_the_alert(engine):  # noqa: F811
    team_id = make_team(engine)
    raise_now(engine, team_id)
    with session_scope(engine) as db:
        assert checkin.send_due(db, NOW + timedelta(hours=25), Outbox(fail=True), "x") == 1


def test_the_current_hr_contact_stays_until_the_replacement_accepts(client, engine, outbox):  # noqa: F811
    """Inviting a replacement changes nothing until they sign up through the link; then the
    former contact loses list, open and mark access at once and gets no reminder, and the new
    one has access."""
    team_id = make_team(engine)  # hr@example.com is the HR contact
    raise_now(engine, team_id)
    with session_scope(engine) as db:
        checkin.send_due(db, NOW + timedelta(minutes=61))
    old = signed_in(client, engine, "hr@example.com")
    [alert] = client.get("/checkins", headers=old).json()

    assert invite(client, engine, team_id, "next.hr@example.com").json()["invited"] is True
    with session_scope(engine) as db:  # still the old contact while the invitation waits
        team = db.get(Team, uuid.UUID(team_id))
        assert db.get(User, team.hr_id).email == "hr@example.com"
    assert len(client.get("/checkins", headers=old).json()) == 1
    assert client.post(f"/checkins/{alert['id']}/open", headers=old).status_code == 200

    signed = client.post(
        "/auth/signup",
        json={
            "email": "next.hr@example.com",
            "password": PASSWORD,
            "hrInvite": token_in(outbox.sent[-1]),
        },
    ).json()
    new = {"Authorization": f"Bearer {signed['token']}"}

    assert client.get("/checkins", headers=old).json() == []
    assert client.post(f"/checkins/{alert['id']}/open", headers=old).status_code == 404
    marked = client.post(
        f"/checkins/{alert['id']}/mark", headers=old, json={"outcome": "checked_in"}
    )
    assert marked.status_code == 404
    box = Outbox()
    with session_scope(engine) as db:
        assert checkin.remind_due(db, NOW + timedelta(days=5), box, "https://app.example") == 1
    assert [e.to for e in box.sent] == ["boss@example.com"]  # not the former contact
    # The new contact holds the role for new alerts; this one was sent before they joined.
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        assert db.get(User, team.hr_id).email == "next.hr@example.com"
        assert checkin.current_holder(db, team, "hr") == team.hr_id
    assert client.get("/checkins", headers=new).status_code == 200


def test_an_invitation_only_makes_its_own_team_hr(client, engine, outbox):  # noqa: F811
    team_id = make_team(engine)
    invite(client, engine, team_id, "only.this@example.com")
    client.post(
        "/auth/signup",
        json={
            "email": "only.this@example.com",
            "password": PASSWORD,
            "hrInvite": token_in(outbox.sent[-1]),
        },
    )
    with session_scope(engine) as db:
        user = db.scalar(select(User).where(User.email == "only.this@example.com"))
        teams = db.scalars(select(Team).where(Team.hr_id == user.id)).all()
        assert [str(t.id) for t in teams] == [team_id]


def test_send_now_emails_the_recipients_without_the_name(client, engine):  # noqa: F811
    box = Outbox()
    client.app.dependency_overrides[checkins.get_mailer] = lambda: box
    team_id = make_team(engine)
    raise_now(engine, team_id)
    me = signed_in(client, engine, "member00@example.com")
    alert_id = client.get("/me/checkins", headers=me).json()[0]["id"]
    assert client.post(f"/me/checkins/{alert_id}/send", headers=me).status_code == 200
    assert sorted(e.to for e in box.sent) == ["boss@example.com", "hr@example.com"]
    assert all("member00" not in e.subject + e.text + e.html for e in box.sent)
    assert all(e.subject == "You have a check-in request" for e in box.sent)
