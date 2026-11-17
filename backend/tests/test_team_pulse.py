"""The nightly team pulse: one answer a person a day, and a supervisor sees only weekly team
figures from at least five people, each person weighed once."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.analysis.evidence import Window
from app.db.models import Pulse, Team, TeamMembership, User
from app.db.session import session_scope
from app.teams import memberships, pulse
from app.teams.agent import TeamClaim, TeamTools, check_claim

NOW = datetime(2026, 10, 26, 20, tzinfo=UTC)  # a Monday evening
TODAY = NOW.date()
WEEK = Window(start=TODAY - timedelta(days=7), end=TODAY - timedelta(days=1))
PASSWORD = "correct horse battery"


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


def team_of(engine, size: int) -> tuple[str, list[uuid.UUID]]:
    with session_scope(engine) as db:
        boss = User(email="boss@example.com", status="approved", role="supervisor")
        db.add(boss)
        db.flush()
        team = memberships.create_team(db, boss, "Design", None, NOW)
        people = []
        for i in range(size):
            person = User(email=f"member{i:02d}@example.com", status="approved")
            db.add(person)
            db.flush()
            memberships.join(db, team, person, NOW)
            people.append(person.id)
        return str(team.id), people


def answer(engine, user_id, day, rating):
    with session_scope(engine) as db:
        db.add(Pulse(user_id=user_id, day=day, rating=rating))


def test_only_todays_answer_from_1_to_5_and_only_from_someone_in_a_team(engine):
    _, people = team_of(engine, 1)
    with session_scope(engine) as db:
        assert pulse.save(db, people[0], TODAY, 4, today=TODAY).rating == 4
        assert pulse.save(db, people[0], TODAY, 2, today=TODAY).rating == 2  # changed, not added
        for day, rating in ((TODAY - timedelta(days=1), 3), (TODAY, 6), (TODAY, True)):
            with pytest.raises(pulse.PulseRejected):
                pulse.save(db, people[0], day, rating, today=TODAY)
        loner = User(email="alone@example.com", status="approved")
        db.add(loner)
        db.flush()
        assert not pulse.asked(db, loner.id)
        with pytest.raises(pulse.PulseRejected):
            pulse.save(db, loner.id, TODAY, 3, today=TODAY)
        assert len(db.scalars(select(Pulse)).all()) == 1


def test_a_week_has_a_team_figure_only_from_five_people_each_weighed_once(engine):
    team_id, people = team_of(engine, 6)
    for person in people[:4]:
        answer(engine, person, WEEK.start, 2)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        four = pulse.week_figures(db, team, WEEK)
        assert four["respondents"] == 4 and four["mean"] is None  # too few: no figure at all
    for day in range(7):  # one person answers every night, all heavy
        answer(engine, people[4], WEEK.start + timedelta(days=day), 5)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        five = pulse.week_figures(db, team, WEEK)
        # (2 + 2 + 2 + 2 + 5) / 5: their seven answers count as one person's week
        assert five["respondents"] == 5 and five["mean"] == 2.6
        db.scalar(select(TeamMembership).where(TeamMembership.user_id == people[4])).left_at = NOW
        db.flush()
        assert pulse.week_figures(db, team, WEEK)["mean"] is None  # who left no longer counts


def test_the_agent_can_cite_the_weeks_pulse(engine):
    team_id, people = team_of(engine, 5)
    for back in range(5):
        start = WEEK.start - timedelta(weeks=back)
        for person in people:
            answer(engine, person, start, 4 if back == 0 else 2)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        box = TeamTools(db, team, TODAY, NOW)
        (found,) = box.run("team_pulse", {})["pulse"]
        assert found["mean"] == 4 and found["before_mean"] == 2 and found["respondents"] == 5
        claim = TeamClaim(
            text="The team rated last week 4 out of 5, against 2 in the weeks before.",
            kind="value",
            evidence_ids=[found["evidence_id"]],
        )
        assert check_claim(claim, box.evidence) == []
        # A figure the evidence does not hold is refused ("5" would pass: there were 5 people).
        wrong = claim.model_copy(update={"text": "The team rated last week 3.2 on average."})
        assert check_claim(wrong, box.evidence)


def test_the_routes_for_members_and_for_the_supervisor(engine):
    from app.api import auth
    from app.api.main import create_app
    from app.auth import accounts

    team_id, people = team_of(engine, 5)
    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[auth.now] = lambda: NOW
    client = TestClient(app)

    def signed_in(email: str) -> dict:
        with session_scope(engine) as session:
            user = session.scalar(select(User).where(User.email == email))
            accounts.set_password(session, user, PASSWORD)
        token = client.post("/auth/login", json={"email": email, "password": PASSWORD})
        return {"Authorization": f"Bearer {token.json()['token']}"}

    member = signed_in("member00@example.com")
    today = client.get("/pulse/today", headers=member).json()
    assert today["asked"] is True and today["rating"] is None and len(today["scale"]) == 5
    saved = client.put("/pulse/today", json={"rating": 3}, headers=member).json()
    assert saved["rating"] == 3
    assert client.put("/pulse/today", json={"rating": 9}, headers=member).status_code == 422
    boss = signed_in("boss@example.com")
    weeks = client.get(f"/teams/{team_id}/pulse", headers=boss).json()
    assert weeks["minimum"] == 5 and len(weeks["weeks"]) == 5
    assert all(w["mean"] is None for w in weeks["weeks"])  # one answer, this week: nothing shown
    assert client.get(f"/teams/{team_id}/pulse", headers=member).status_code in (403, 404)
