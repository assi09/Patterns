"""Teams: who may create and see them, joining with consent, leaving, and sharing levels."""

import uuid
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.api import auth, teams
from app.api.main import create_app
from app.auth.__main__ import main as auth_cli
from app.auth.accounts import LoginThrottle
from app.db.models import TeamEvent, TeamMembership, User
from app.db.session import session_scope
from app.teams import memberships

PASSWORD = "correct horse battery"


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


@pytest.fixture
def client(engine, monkeypatch) -> TestClient:
    monkeypatch.setattr(auth, "throttle", LoginThrottle())
    monkeypatch.setattr(teams, "code_throttle", LoginThrottle(max_failures=10))
    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[auth.now] = lambda: datetime(2026, 10, 26, 9, tzinfo=UTC)
    return TestClient(app)


def person(client, engine, email: str, role: str = "member", approved: bool = True) -> dict:
    token = client.post("/auth/signup", json={"email": email, "password": PASSWORD}).json()["token"]
    with session_scope(engine) as session:
        user = session.scalar(select(User).where(User.email == email))
        user.status = "approved" if approved else "pending"
        user.role = role
    return {"Authorization": f"Bearer {token}"}


def new_team(client, headers, name: str = "Design") -> dict:
    response = client.post("/teams", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def join(client, headers, code: str) -> dict:
    response = client.post(
        "/teams/join",
        json={"code": code, "consentVersion": memberships.CONSENT_VERSION},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# Who may do what


def test_only_approved_supervisors_create_and_list_teams(client, engine):
    member = person(client, engine, "member@example.com")
    assert client.post("/teams", json={"name": "X"}, headers=member).json()["error"]["code"] == (
        "not_supervisor"
    )
    assert client.get("/teams", headers=member).status_code == 403
    pending = person(client, engine, "pending@example.com", "supervisor", approved=False)
    assert client.post("/teams", json={"name": "X"}, headers=pending).status_code == 403
    assert client.get("/teams").status_code == 401

    boss = person(client, engine, "boss@example.com", "supervisor")
    team = new_team(client, boss)
    assert team["members"] == 0 and team["minimumMembers"] == memberships.MIN_MEMBERS
    assert len(team["inviteCode"]) == memberships.CODE_LENGTH
    assert [t["id"] for t in client.get("/teams", headers=boss).json()] == [team["id"]]
    assert client.get("/auth/me", headers=boss).json()["role"] == "supervisor"


def test_a_supervisor_cannot_see_another_supervisors_team(client, engine):
    first = person(client, engine, "first@example.com", "supervisor")
    second = person(client, engine, "second@example.com", "supervisor")
    team = new_team(client, first)
    for path in (f"/teams/{team['id']}", "/teams/not-a-uuid"):
        assert client.get(path, headers=second).json()["error"]["code"] == "not_found"
    rotated = client.post(f"/teams/{team['id']}/invite-code", headers=second)
    assert rotated.status_code == 404
    assert client.get("/teams", headers=second).json() == []


def test_a_team_shows_how_many_people_are_in_it_and_never_who(client, engine):
    boss = person(client, engine, "boss@example.com", "supervisor")
    team = new_team(client, boss)
    for i in range(3):
        join(client, person(client, engine, f"p{i}@example.com"), team["inviteCode"])
    body = client.get(f"/teams/{team['id']}", headers=boss).json()
    assert body["members"] == 3
    assert "example.com" not in str(body).replace("boss@example.com", "")


# Joining


def test_joining_shows_what_it_means_first_and_needs_the_current_consent(client, engine):
    boss = person(client, engine, "boss@example.com", "supervisor")
    code = new_team(client, boss, "Design")["inviteCode"]
    member = person(client, engine, "member@example.com")

    preview = client.post("/teams/preview", json={"code": code}, headers=member).json()
    assert preview["team"] == "Design" and preview["supervisor"] == "boss@example.com"
    assert str(memberships.MIN_MEMBERS) in preview["consent"]
    assert preview["consentVersion"] == memberships.CONSENT_VERSION

    stale = client.post("/teams/join", json={"code": code, "consentVersion": "old"}, headers=member)
    assert stale.json()["error"]["code"] == "consent_changed"

    joined = join(client, member, code.lower()[:4] + "-" + code.lower()[4:])  # typed loosely
    assert joined["team"] == "Design" and joined["shareLevels"] is False
    (listed,) = client.get("/me/teams", headers=member).json()
    # SQLite reads times back without their zone; compare everything else.
    assert {**listed, "joinedAt": None} == {**joined, "joinedAt": None}
    again = client.post(
        "/teams/join",
        json={"code": code, "consentVersion": memberships.CONSENT_VERSION},
        headers=member,
    )
    assert again.json()["error"]["code"] == "already_member"


def test_a_supervisor_cannot_join_their_own_team(client, engine):
    boss = person(client, engine, "boss@example.com", "supervisor")
    code = new_team(client, boss)["inviteCode"]
    response = client.post(
        "/teams/join",
        json={"code": code, "consentVersion": memberships.CONSENT_VERSION},
        headers=boss,
    )
    assert response.json()["error"]["code"] == "own_team"


def test_wrong_codes_are_refused_and_guessing_is_slowed(client, engine):
    member = person(client, engine, "member@example.com")
    for _ in range(10):
        wrong = client.post("/teams/preview", json={"code": "NOPE1234"}, headers=member)
        assert wrong.json()["error"]["code"] == "unknown_code"
    blocked = client.post("/teams/preview", json={"code": "NOPE1234"}, headers=member)
    assert blocked.status_code == 429


def test_a_rotated_code_stops_working_and_members_stay(client, engine):
    boss = person(client, engine, "boss@example.com", "supervisor")
    team = new_team(client, boss)
    member = person(client, engine, "member@example.com")
    join(client, member, team["inviteCode"])
    rotated = client.post(f"/teams/{team['id']}/invite-code", headers=boss).json()
    assert rotated["inviteCode"] != team["inviteCode"] and rotated["members"] == 1
    late = person(client, engine, "late@example.com")
    old = client.post("/teams/preview", json={"code": team["inviteCode"]}, headers=late)
    assert old.status_code == 404


# Leaving and sharing levels


def test_sharing_levels_is_a_separate_consent_and_can_be_turned_off(client, engine):
    boss = person(client, engine, "boss@example.com", "supervisor")
    team = new_team(client, boss)
    member = person(client, engine, "member@example.com")
    joined = join(client, member, team["inviteCode"])
    path = f"/me/teams/{team['id']}/levels"

    unread = client.post(path, json={"share": True}, headers=member)
    assert unread.json()["error"]["code"] == "consent_changed"
    on = client.post(
        path, json={"share": True, "consentVersion": joined["levelsConsentVersion"]}, headers=member
    ).json()
    assert on["shareLevels"] is True
    off = client.post(path, json={"share": False}, headers=member).json()
    assert off["shareLevels"] is False


def test_leaving_ends_membership_and_sharing_and_keeps_a_record(client, engine):
    boss = person(client, engine, "boss@example.com", "supervisor")
    team = new_team(client, boss)
    member = person(client, engine, "member@example.com")
    joined = join(client, member, team["inviteCode"])
    client.post(
        f"/me/teams/{team['id']}/levels",
        json={"share": True, "consentVersion": joined["levelsConsentVersion"]},
        headers=member,
    )
    assert client.post(f"/me/teams/{team['id']}/leave", headers=member).status_code == 204
    assert client.get("/me/teams", headers=member).json() == []
    assert client.get(f"/teams/{team['id']}", headers=boss).json()["members"] == 0
    assert client.post(f"/me/teams/{team['id']}/leave", headers=member).status_code == 404
    # Joining again is allowed, as a new membership.
    join(client, member, team["inviteCode"])

    with session_scope(engine) as session:
        rows = session.scalars(select(TeamMembership).order_by(TeamMembership.joined_at)).all()
        assert [r.left_at is None for r in rows] == [False, True]
        assert rows[0].share_levels is False
        events = [
            e.event for e in session.scalars(select(TeamEvent).order_by(TeamEvent.created_at))
        ]
    assert events.count("joined") == 2 and "left" in events and "levels_shared" in events
    assert events[0] == "created"


def test_a_member_cannot_change_a_team_they_are_not_in(client, engine):
    boss = person(client, engine, "boss@example.com", "supervisor")
    team = new_team(client, boss)
    outsider = person(client, engine, "outsider@example.com")
    for path in (f"/me/teams/{team['id']}/leave", "/me/teams/not-a-uuid/leave"):
        assert client.post(path, headers=outsider).status_code == 404
    shared = client.post(f"/me/teams/{team['id']}/levels", json={"share": False}, headers=outsider)
    assert shared.status_code == 404


# The owner's command line


def test_the_owner_sets_roles_from_the_command_line(engine, monkeypatch, capsys):
    import app.auth.__main__ as cli

    monkeypatch.setattr(cli, "session_scope", lambda: session_scope(engine))
    with session_scope(engine) as session:
        session.add(User(email="lead@example.com", status="approved"))
        session.add(User(email="new@example.com", status="pending"))
    assert auth_cli(["set-role", "lead@example.com", "supervisor"]) == 0
    assert auth_cli(["set-role", "new@example.com", "supervisor"]) == 1  # not approved
    assert auth_cli(["set-role", "nobody@example.com", "supervisor"]) == 1
    with session_scope(engine) as session:
        roles = dict(session.execute(select(User.email, User.role)).all())
    assert roles == {"lead@example.com": "supervisor", "new@example.com": "member"}


# One supervisor, several teams: they must differ by at least five people, or not at all


def _people(db, count: int) -> list[User]:
    people = []
    for _ in range(count):
        person = User(email=f"p{uuid.uuid4().hex[:8]}@example.com", status="approved")
        db.add(person)
        people.append(person)
    db.flush()
    return people


def _team_of(db, boss, name, people):
    from datetime import UTC, datetime

    from app.teams import memberships

    team = memberships.create_team(db, boss, name, None, datetime.now(UTC))
    for person in people:
        memberships.join(db, team, person, datetime.now(UTC))
    return team


@pytest.mark.parametrize(
    "layout, paused",
    [
        ([range(0, 5), range(5, 10)], [False, False]),  # two halves
        ([range(0, 10), range(0, 5), range(5, 10)], [False, False, False]),  # all, and each half
        ([range(0, 7), range(1, 7)], [True, True]),  # differ by one person
        ([range(0, 8), range(3, 10)], [True, True]),  # 3 and 2 people apart
    ],
)
def test_a_supervisors_teams_must_differ_by_five_or_not_at_all(engine, layout, paused):
    from app.teams.memberships import overlap_problem

    with session_scope(engine) as db:
        boss = User(email="lead@example.com", status="approved", role="supervisor")
        db.add(boss)
        db.flush()
        people = _people(db, 10)
        made = [_team_of(db, boss, f"T{i}", [people[j] for j in r]) for i, r in enumerate(layout)]
        assert [overlap_problem(db, t) is not None for t in made] == paused


def test_another_supervisors_team_is_not_compared(engine):
    from app.teams.memberships import overlap_problem

    with session_scope(engine) as db:
        one = User(email="one@example.com", status="approved", role="supervisor")
        two = User(email="two@example.com", status="approved", role="supervisor")
        db.add_all([one, two])
        db.flush()
        people = _people(db, 7)
        mine = _team_of(db, one, "Mine", people)
        _team_of(db, two, "Theirs", people[1:])
        assert overlap_problem(db, mine) is None
