"""Standalone weekly briefing, dated event warnings, privacy and delivery."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select

from app.agent.llm import ScriptedLLM
from app.analysis.team import team_info
from app.db.daily import save_daily
from app.db.models import Team, TeamAction, TeamChatMessage, TeamNote, TeamReport, User
from app.db.session import session_scope
from app.synthetic import Step, generate
from app.teams import memberships, reports
from app.teams.agent import TeamTools
from app.teams.briefing import brief
from app.teams.email import compose

NOW = datetime(2026, 10, 26, 9, tzinfo=UTC)  # a Monday
TODAY = NOW.date()
WEEK = reports.last_full_week(TODAY)
SLEEP = team_info("sleep_minutes").label
LATE = (Step("sleep_minutes", TODAY - timedelta(days=22), -75.0),)


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


def make_team(engine, size: int = 7, effects=LATE) -> str:
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


def run(engine, team_id: str, turns: list):
    llm = ScriptedLLM(turns)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        report = reports.build_report(db, team, WEEK, NOW)
        found = brief(llm, db, team, report, TODAY, NOW, 0.1)
        db.expunge_all()
    return found, llm


@pytest.mark.parametrize("mode", ["valid", "unknown_id", "free_text", "offline"])
def test_weekly_highlights_only_use_this_reports_evidence(engine, mode):
    team_id = make_team(engine, effects=LATE + (Step("steps", TODAY - timedelta(days=22), -5000),))
    with session_scope(engine) as db:
        db.add(
            TeamChatMessage(
                team_id=uuid.UUID(team_id),
                role="supervisor",
                text="followup sentinel",
                created_at=NOW,
            )
        )

    def choose(messages):
        assert len(messages) == 2 and "followup sentinel" not in str(messages)
        findings = json.loads(messages[1]["content"])
        first = findings[0]["evidence_id"]
        answer = {
            "valid": json.dumps([first]),
            "unknown_id": json.dumps([first, "bad"]),
            "free_text": "Can you clarify?",
        }[mode]
        return ScriptedLLM.say(answer)

    found, llm = run(engine, team_id, [] if mode == "offline" else [choose])
    assert len(llm.requests) == 1 and llm.requests[0]["tools"] == []
    assert found.stop == ("selected" if mode == "valid" else "ranked_fallback")
    with session_scope(engine) as db:
        report = db.scalar(select(TeamReport))
        planted = {
            row["metric"]: report.evidence[row["evidence_id"]]["stats"]["direction"]
            for row in report.body["priorities"]
        }
        assert planted["sleep_minutes"] == planted["steps"] == "down"
        expected = report.body["priorities"][: 1 if mode == "valid" else 3]
        summary = " ".join(row["text"] for row in expected)
        briefing = report.body["briefing"]
        assert briefing["summary"] == summary
        assert [item["evidence_ids"] for item in briefing["items"]] == [
            [row["evidence_id"]] for row in expected
        ]
        assert all(row["evidence_id"] in report.evidence for row in expected)
        team = db.get(Team, uuid.UUID(team_id))
        assert summary in compose(team, report, "boss@example.com", "https://app.example").text


def test_once_a_week_and_never_for_a_withheld_report(engine):
    team_id = make_team(engine)
    turns = []
    run(engine, team_id, turns)
    again, llm = run(engine, team_id, turns)
    assert again is None and llm.requests == []
    with session_scope(engine) as db:
        assert len(db.scalars(select(TeamChatMessage)).all()) == 1

    small = make_small_team(engine)
    none, llm = run(engine, small, turns)
    assert none is None and llm.requests == []


def make_small_team(engine) -> str:
    with session_scope(engine) as db:
        boss = db.scalar(select(User).where(User.email == "boss@example.com"))
        team = memberships.create_team(db, boss, "Tiny", None, NOW)
        return str(team.id)


def test_the_agent_can_find_a_challenge_that_ended_and_how_it_went(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        db.add(
            TeamAction(
                team_id=team.id,
                kind="challenge",
                title="Lights out by 23:00",
                body="Two weeks of earlier nights.",
                metric="sleep_minutes",
                starts_on=TODAY - timedelta(days=20),
                ends_on=TODAY - timedelta(days=7),
                status="approved",
                proposed_at=NOW - timedelta(days=21),
            )
        )
        db.flush()
        box = TeamTools(db, team, TODAY, NOW)
        (listed,) = box.run("team_actions", {})["actions"]
        assert listed["ended"] is True and listed["status"] == "approved"
        result = box.run("action_result", {"action_id": listed["action_id"]})
        assert result["result"][0]["tool"] == "team_change"


def test_the_weekly_command_briefs_and_still_emails_when_the_agent_fails(
    engine, monkeypatch, capsys, tmp_path
):
    import app.teams.__main__ as cli

    make_team(engine)
    turns = []
    monkeypatch.setattr(cli, "session_scope", lambda: session_scope(engine))
    monkeypatch.setattr(cli.settings, "data_dir", tmp_path)
    monkeypatch.setattr(cli.settings, "email_backend", "outbox")
    monkeypatch.setattr(cli.OpenAILLM, "from_settings", lambda *a, **k: ScriptedLLM(turns))
    assert cli.main(["weekly", "--week", WEEK.start.isoformat(), "--agent"]) == 0
    out = capsys.readouterr()
    assert "1 briefed by the team agent" in out.out
    (email,) = (tmp_path / "outbox").glob("*.html")
    assert "From your team agent" in email.read_text()


def test_the_supervisor_reads_the_briefing_with_the_report(engine, monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import auth
    from app.api.main import create_app
    from app.auth import accounts

    team_id = make_team(engine)
    run(engine, team_id, [])
    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[auth.now] = lambda: NOW
    client = TestClient(app)
    with session_scope(engine) as session:
        boss = session.scalar(select(User).where(User.email == "boss@example.com"))
        accounts.set_password(session, boss, "correct horse battery")
    token = client.post(
        "/auth/login", json={"email": "boss@example.com", "password": "correct horse battery"}
    ).json()["token"]
    body = client.get(
        f"/teams/{team_id}/reports/{WEEK.start}", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert body["briefing"]["summary"].startswith("Time asleep has been lower")
    assert body["briefing"]["items"][0]["metric"] == "sleep_minutes"
    assert body["briefing"]["proposals"] == 0
    for item in body["briefing"]["items"]:
        assert item["evidenceIds"] and all(key in body["evidence"] for key in item["evidenceIds"])


def test_what_past_notes_were_followed_by_and_which_are_coming_up(engine):
    from app.teams.agent import _team_change_moved

    release = TODAY - timedelta(days=40)
    team_id = make_team(engine, effects=(Step("sleep_minutes", release, -75.0),))
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        for text, start in (
            ("Release 1.0", release),
            ("Offsite", TODAY - timedelta(days=70)),  # nothing happened after it
            ("Release 2.0", TODAY + timedelta(days=10)),
            ("Planning week", TODAY + timedelta(days=60)),  # too far ahead to count
        ):
            db.add(TeamNote(team_id=team.id, text=text, starts_on=start, created_at=NOW))
        db.flush()
        box = TeamTools(db, team, TODAY, NOW)
        found = box.run("note_aftermath", {})
        assert [n["note"] for n in found["coming_up"]] == ["Release 2.0"]
        after = {p["note"]["note"]: p["team_after"] for p in found["past"]}
        sleep_after_release = next(e for e in after["Release 1.0"] if e["metric"] == SLEEP)
        record = box.evidence[sleep_after_release["evidence_id"]]
        assert "p_value_adjusted" in record.stats  # corrected with the other tests
        assert _team_change_moved(record) and record.stats["median_change"] < 0
        sleep_after_offsite = next(e for e in after["Offsite"] if e["metric"] == SLEEP)
        assert not _team_change_moved(box.evidence[sleep_after_offsite["evidence_id"]])


def _crunch_team(engine, moved: bool) -> str:

    release = TODAY - timedelta(days=40)
    effects = (
        (
            Step("sleep_minutes", release, -75.0),
            Step("sleep_minutes", release + timedelta(days=14), 75.0),
        )
        if moved
        else ()
    )
    team_id = make_team(engine, effects=effects)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        db.add(TeamNote(team_id=team.id, text="Release 1.0", starts_on=release, created_at=NOW))
        db.add(
            TeamNote(
                team_id=team.id,
                text="Release 2.0",
                starts_on=TODAY + timedelta(days=10),
                created_at=NOW,
            )
        )
    return team_id


@pytest.mark.parametrize("judged_alike", [True, False])
def test_a_coming_note_is_warned_about_from_what_a_past_one_was_followed_by(engine, judged_alike):
    team_id = _crunch_team(engine, moved=True)
    alike = ScriptedLLM.say("yes" if judged_alike else "no")
    found, llm = run(engine, team_id, [alike])
    with session_scope(engine) as db:
        briefing = db.scalar(select(TeamReport)).body.get("briefing")
    assert found is not None
    summary = briefing["summary"]
    asked = llm.requests[-1]["messages"][1]["content"]
    assert "Release 2.0" in asked and "Release 1.0" in asked  # only the notes, nothing else
    if judged_alike:
        assert "Release 2.0 is on" in summary and "time asleep changed by a median -" in summary
        assert any(item["kind"] == "ahead" for item in briefing["items"])
    else:
        assert "Release 2.0" not in summary


def test_no_warning_and_no_question_when_nothing_followed_the_past_note(engine):
    team_id = _crunch_team(engine, moved=False)
    found, llm = run(engine, team_id, [])
    assert found is not None and "Release 2.0" not in found.text
    assert not any("Coming:" in str(r["messages"]) for r in llm.requests)


def test_note_matcher_outage_leaves_the_weekly_report_readable(engine):
    team_id = _crunch_team(engine, moved=True)
    found, llm = run(engine, team_id, [])
    assert found and "Release 2.0" not in found.text
    assert any("Coming:" in str(r["messages"]) for r in llm.requests)


def test_completed_event_warning_survives_a_later_matcher_outage(engine):
    team_id = _crunch_team(engine, moved=True)
    with session_scope(engine) as db:
        db.add(
            TeamNote(
                team_id=uuid.UUID(team_id),
                text="Another release",
                starts_on=TODAY + timedelta(days=16),
                created_at=NOW,
            )
        )
    found, _ = run(engine, team_id, [ScriptedLLM.say("yes")])
    assert found is not None
    with session_scope(engine) as db:
        report = db.scalar(select(TeamReport))
        warnings = [item for item in report.body["briefing"]["items"] if item["kind"] == "ahead"]
        assert len(warnings) == 1
        cited = [report.evidence[key] for key in warnings[0]["evidence_ids"]]
        assert sum(e["tool"] == "team_note" for e in cited) == 2
        assert any(e["tool"] == "team_change" for e in cited)
        assert any(step.get("error") == "LLMError" for step in found.trace)
