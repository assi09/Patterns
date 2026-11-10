"""The supervisor's team agent: answers checked against team evidence, never about one person,
notes it remembers, and actions that wait for approval."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.agent.llm import ScriptedLLM
from app.analysis.team import team_info
from app.api import auth, teams
from app.api.main import create_app
from app.auth import accounts
from app.db.daily import save_daily
from app.db.models import Notification, Team, TeamAction, TeamChatMessage, TeamNote, User
from app.db.session import session_scope
from app.synthetic import Step, generate
from app.teams import actions, memberships
from app.teams.agent import ABOUT_A_PERSON_REPLY, ANSWER, MEDICAL_REPLY, answer_supervisor

NOW = datetime(2026, 10, 26, 9, tzinfo=UTC)  # a Monday
TODAY = NOW.date()
SLEEP = team_info("sleep_minutes").label
PASSWORD = "correct horse battery"


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


def make_team(engine, size: int = 7, effects=()) -> str:
    start = TODAY - timedelta(days=90)
    with session_scope(engine) as db:
        boss = User(email="boss@example.com", status="approved", role="supervisor")
        db.add(boss)
        db.flush()
        team = memberships.create_team(db, boss, "Design", None, NOW)
        for i in range(size):
            person = User(email=f"member{i:02d}@example.com", status="approved")
            db.add(person)
            db.flush()
            save_daily(db, person.id, "google_health", generate(start, 89, effects, seed=i).frame)
            memberships.join(db, team, person, NOW)
        return str(team.id)


LATE = (Step("sleep_minutes", TODAY - timedelta(days=22), -75.0),)


def tool_result(messages: list[dict], key: str) -> dict:
    for message in reversed(messages):
        if message["role"] == "tool":
            content = json.loads(message["content"])
            if key in content:
                return content
    raise AssertionError(f"no {key} in the conversation")


def sleep_evidence(messages: list[dict]) -> dict:
    return next(e for e in tool_result(messages, "metrics")["metrics"] if e["metric"] == SLEEP)


def answer(summary: str, claims: list[dict]):
    return ScriptedLLM.call(ANSWER, summary=summary, claims=claims)


def ask(engine, team_id: str, question: str, turns: list):
    llm = ScriptedLLM(turns)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        reply = answer_supervisor(llm, db, team, question, TODAY, NOW)
        db.expunge_all()
    return reply, llm


def test_a_question_about_one_person_gets_a_fixed_reply_without_a_model(engine):
    team_id = make_team(engine)
    for question in ("Who is sleeping the worst?", "Is someone struggling on the team?"):
        reply, llm = ask(engine, team_id, question, [])
        assert reply.text == ABOUT_A_PERSON_REPLY and llm.requests == []


def test_a_medical_question_gets_a_fixed_reply(engine):
    reply, llm = ask(engine, make_team(engine), "Does the team have insomnia?", [])
    assert reply.text in (MEDICAL_REPLY, ABOUT_A_PERSON_REPLY) and llm.requests == []


def test_a_lasting_drop_is_answered_from_team_evidence_and_stored(engine):
    team_id = make_team(engine, effects=LATE)

    def submit(messages):
        sleep = sleep_evidence(messages)
        assert sleep["status"] == "lasting" and sleep["direction"] == "down"
        return answer(
            "Time asleep has been lower across the team for the past few weeks.",
            [
                {
                    "text": "Time asleep fell across the team.",
                    "kind": "change",
                    "metric": "sleep_minutes",
                    "direction": "down",
                    "evidence_ids": [sleep["evidence_id"]],
                }
            ],
        )

    reply, _ = ask(
        engine, team_id, "How has the team been?", [ScriptedLLM.call("team_overview"), submit]
    )
    assert reply.stop == "answered" and reply.text.startswith("Time asleep")
    assert [e.tool for e in reply.evidence] == ["team_scan"]
    with session_scope(engine) as db:
        roles = [m.role for m in db.scalars(select(TeamChatMessage).order_by("created_at"))]
    assert roles == ["supervisor", "agent"]


@pytest.mark.parametrize(
    "claim, why",
    [
        ({"text": "Time asleep rose across the team.", "direction": "up"}, "does not point up"),
        ({"text": "Two members slept far less.", "direction": "down"}, "single out"),
        ({"text": "Time asleep fell, a sign of insomnia.", "direction": "down"}, "medical"),
        ({"text": "Time asleep fell for everyone.", "direction": "down"}, "single out"),
    ],
)
def test_a_wrong_or_unsafe_claim_is_sent_back_then_dropped(engine, claim, why):
    team_id = make_team(engine, effects=LATE)

    def submit(messages):
        sleep = sleep_evidence(messages)
        return answer(
            "Here is how the team has been.",
            [
                {
                    **claim,
                    "kind": "change",
                    "metric": "sleep_minutes",
                    "evidence_ids": [sleep["evidence_id"]],
                }
            ],
        )

    reply, llm = ask(
        engine, team_id, "How is sleep?", [ScriptedLLM.call("team_overview"), submit, submit]
    )
    repair = json.loads(llm.requests[2]["messages"][-1]["content"])
    assert any(why in r for r in repair["rejected"])
    assert (
        reply.stop != "answered" and reply.evidence == []
    )  # the bad claim's evidence is not shown


def test_too_few_people_means_no_figures_at_all(engine):
    team_id = make_team(engine, size=4)

    def look(messages):
        assert "Fewer than 5" in tool_result(messages, "error")["error"]
        return answer("There are too few people with data to say anything yet.", [])

    reply, _ = ask(engine, team_id, "How is the team?", [ScriptedLLM.call("team_overview"), look])
    assert reply.stop == "answered" and reply.evidence == []


def test_the_agent_remembers_a_team_event_but_never_a_person(engine):
    team_id = make_team(engine)
    turns = [
        ScriptedLLM.call(
            "save_team_note", text="Release deadline", starts_on="2026-10-12", ends_on="2026-10-16"
        ),
        ScriptedLLM.call("save_team_note", text="Sam is off sick this week"),
        answer("Noted.", []),
    ]
    ask(engine, team_id, "We had a release deadline Oct 12 to 16.", turns)
    with session_scope(engine) as db:
        notes = db.scalars(select(TeamNote)).all()
        assert [n.text for n in notes] == ["Release deadline"]
        assert notes[0].starts_on == date(2026, 10, 12)


def test_a_proposal_waits_for_approval_and_then_reaches_every_member(engine):
    team_id = make_team(engine, size=6)
    turns = [
        ScriptedLLM.call(
            "propose_team_action",
            kind="challenge",
            title="Lights out by 23:00",
            body="For two weeks, try to be in bed by 23:00 on weeknights.",
            metric="sleep_minutes",
            days=14,
        ),
        answer("I proposed a two-week challenge for your approval.", []),
    ]
    reply, _ = ask(engine, team_id, "What could we try?", turns)
    assert [a.status for a in reply.actions] == ["proposed"]
    with session_scope(engine) as db:
        assert db.scalars(select(Notification)).all() == []  # nothing sent before approval
        team = db.get(Team, uuid.UUID(team_id))
        action = db.scalar(select(TeamAction))
        assert actions.decide(db, team, action, True, NOW) == 6
        assert action.ends_on - action.starts_on == timedelta(days=13)
        sent = db.scalars(select(Notification)).all()
        assert len(sent) == 6 and all(n.kind == "team_challenge" for n in sent)
        assert all("member" not in n.body.lower() for n in sent)


def test_a_proposal_that_singles_someone_out_is_refused(engine):
    team_id = make_team(engine)
    turns = [
        ScriptedLLM.call(
            "propose_team_action",
            kind="message",
            title="A note",
            body="Some of the team need to sleep more.",
        ),
        answer("Done.", []),
    ]
    reply, _ = ask(engine, team_id, "Send the team something?", turns)
    assert reply.actions == []
    with session_scope(engine) as db:
        assert db.scalars(select(TeamAction)).all() == []


def test_a_decision_is_made_once(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        action = TeamAction(
            team_id=team.id, kind="message", title="Hi", body="Thanks, team.", proposed_at=NOW
        )
        db.add(action)
        db.flush()
        assert actions.decide(db, team, action, False, NOW) == 0
        with pytest.raises(Exception, match="already decided"):
            actions.decide(db, team, action, True, NOW)


# The API


@pytest.fixture
def client(engine):
    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[auth.now] = lambda: NOW
    return TestClient(app), app


def signed_in(client: TestClient, engine, email: str) -> dict:
    with session_scope(engine) as db:
        user = db.scalar(select(User).where(User.email == email))
        accounts.set_password(db, user, PASSWORD)
    token = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_only_the_teams_supervisor_reaches_its_agent(engine, client):
    client, app = client
    team_id = make_team(engine)
    with session_scope(engine) as db:
        other = User(email="other@example.com", status="approved", role="supervisor")
        db.add(other)
    app.dependency_overrides[teams.team_agent_llm] = lambda: ScriptedLLM([answer("Hi.", [])])
    boss = signed_in(client, engine, "boss@example.com")
    stranger = signed_in(client, engine, "other@example.com")
    member = signed_in(client, engine, "member00@example.com")
    assert client.get(f"/teams/{team_id}/chat", headers=stranger).status_code == 404
    assert client.get(f"/teams/{team_id}/alerts", headers=member).status_code == 403
    reply = client.post(f"/teams/{team_id}/chat", headers=boss, json={"text": "Hello"}).json()
    assert [m["role"] for m in reply["messages"]] == ["supervisor", "agent"]
    note = client.post(
        f"/teams/{team_id}/notes", headers=boss, json={"text": "Offsite", "startsOn": "2026-10-20"}
    )
    assert note.status_code == 201
    unsafe = client.post(f"/teams/{team_id}/notes", headers=boss, json={"text": "He is unwell"})
    assert unsafe.status_code == 422


def test_a_good_summary_is_kept_when_one_claim_still_fails(engine):
    team_id = make_team(engine, effects=LATE)

    def submit(messages):
        sleep = sleep_evidence(messages)
        good = {
            "text": "Time asleep fell across the team.",
            "kind": "change",
            "metric": "sleep_minutes",
            "direction": "down",
            "evidence_ids": [sleep["evidence_id"]],
        }
        bad = {**good, "kind": "pattern", "text": "Mondays were shortest."}
        return answer("Time asleep has been lower across the team lately.", [good, bad])

    reply, _ = ask(
        engine, team_id, "How is the team?", [ScriptedLLM.call("team_overview"), submit, submit]
    )
    assert reply.stop == "answered_in_part" and reply.text.startswith("Time asleep")
    assert [e.tool for e in reply.evidence] == ["team_scan"]
