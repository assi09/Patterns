"""Weekly team reports: what is stored, what the supervisor sees, and what stays out."""

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from app.agent.llm import ScriptedLLM
from app.analysis.report import change_text
from app.analysis.team import MIN_MEMBERS, week_of
from app.api import auth, teams
from app.api.main import create_app
from app.auth import accounts
from app.auth.accounts import LoginThrottle
from app.db.daily import save_daily
from app.db.models import Team, TeamEvent, TeamReport, User
from app.db.session import session_scope
from app.synthetic import Step, generate
from app.teams import memberships, reports
from app.teams.__main__ import main as teams_cli
from app.teams.narrative import WRITE

NOW = datetime(2026, 10, 26, 9, tzinfo=UTC)  # a Monday
WEEK = week_of(date(2026, 10, 19))  # the last full week: 19 to 25 October
PASSWORD = "correct horse battery"


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


def team_with(engine, size: int, effects=(), sharing: tuple[int, ...] = ()) -> tuple:
    """A supervisor and `size` members with made-up live data; members in `sharing` share levels."""
    start = WEEK.start - timedelta(days=80)
    with session_scope(engine) as db:
        boss = User(email="boss@example.com", status="approved", role="supervisor")
        db.add(boss)
        db.flush()
        team = memberships.create_team(db, boss, "Design", None, NOW)
        for i in range(size):
            person = User(email=f"member{i:02d}@example.com", status="approved")
            db.add(person)
            db.flush()
            save_daily(db, person.id, "google_health", generate(start, 87, effects, seed=i).frame)
            memberships.join(db, team, person, NOW)
            if i in sharing:
                memberships.share_levels(db, person, str(team.id), True, NOW)
        return team.id, boss.id


def report_for(engine, team_id) -> TeamReport:
    with session_scope(engine) as db:
        report = reports.build_report(db, db.get(Team, team_id), WEEK, NOW)
        db.expunge(report)
        return report


def test_a_report_holds_aggregates_with_every_figure_from_its_evidence(engine):
    team_id, _ = team_with(engine, 7, (Step("sleep_minutes", WEEK.start, -70),))
    report = report_for(engine, team_id)
    assert report.status == "ready" and report.members_included == 7
    assert "time asleep fell" in report.headline.lower()  # which way, not just "changed"
    sleep = next(s for s in report.body["sections"] if s["metric"] == "sleep_minutes")
    assert sleep["status"] == "changed" and "fell" in sleep["text"]
    stats = report.evidence[sleep["evidence_id"]]["stats"]
    assert change_text("sleep_minutes", stats["median_change"]) in sleep["text"]
    assert f"{stats['members_down']} lower" in sleep["text"]
    # Nothing about anyone in particular is stored.
    stored = json.dumps([report.headline, report.body, report.evidence])
    assert "@example.com" not in stored and "member0" not in stored


def test_a_week_is_made_once(engine):
    team_id, _ = team_with(engine, 5)
    first, second = report_for(engine, team_id), report_for(engine, team_id)
    assert first.id == second.id


def test_too_few_people_with_data_withhold_the_report(engine):
    team_id, _ = team_with(engine, MIN_MEMBERS - 1)
    report = report_for(engine, team_id)
    assert report.status == "withheld" and report.evidence == {}
    assert report.body == {"sections": [], "weekdays": []}
    assert f"{MIN_MEMBERS - 1} of the {MIN_MEMBERS}" in report.headline


@pytest.mark.parametrize(
    ("metric", "value", "text"),
    [
        ("sleep_minutes", -32.4, "-32 min"),
        ("steps", 1250.0, "+1,250 steps"),
        ("bedtime_hour", 0.2, "+12 min"),
        ("strain", 1.25, "+1.2"),
        ("resting_hr", -2.0, "-2.0 bpm"),
    ],
)
def test_changes_read_in_the_metrics_units(metric, value, text):
    assert change_text(metric, value) == text


def test_the_weekly_command_makes_and_emails_each_teams_report_once(
    engine, monkeypatch, capsys, tmp_path
):
    import app.teams.__main__ as cli

    team_with(engine, 5)
    monkeypatch.setattr(cli, "session_scope", lambda: session_scope(engine))
    monkeypatch.setattr(cli.settings, "data_dir", tmp_path)
    monkeypatch.setattr(cli.settings, "email_backend", "outbox")
    assert teams_cli(["weekly", "--week", WEEK.start.isoformat()]) == 0
    out = capsys.readouterr().out
    assert "1 reports ready, 0 withheld" in out and "1 emails written" in out
    assert len(list((tmp_path / "outbox").glob("*.html"))) == 1
    assert teams_cli(["weekly", "--week", WEEK.start.isoformat()]) == 0
    assert "0 emails written" in capsys.readouterr().out  # already sent
    assert teams_cli(["weekly", "--week", "2099-01-05"]) == 1  # not over yet
    with session_scope(engine) as db:
        assert len(db.scalars(select(TeamReport)).all()) == 1


# Through the API


@pytest.fixture
def client(engine, monkeypatch) -> TestClient:
    monkeypatch.setattr(auth, "throttle", LoginThrottle())
    monkeypatch.setattr(teams, "code_throttle", LoginThrottle(max_failures=10))
    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[auth.now] = lambda: NOW
    return TestClient(app)


def signed_in(client, engine, email: str, role: str = "member") -> dict:
    with session_scope(engine) as db:
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            client.post("/auth/signup", json={"email": email, "password": PASSWORD})
            user = db.scalar(select(User).where(User.email == email))
        user.status, user.role = "approved", role
        accounts.set_password(db, user, PASSWORD)
    token = client.post("/auth/login", json={"email": email, "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_the_supervisor_reads_the_report_with_only_shared_levels(client, engine):
    team_id, _ = team_with(engine, 6, sharing=(3, 1))
    boss = signed_in(client, engine, "boss@example.com", "supervisor")
    made = client.post(f"/teams/{team_id}/reports", json={}, headers=boss)
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["week"] == {"start": "2026-10-19", "end": "2026-10-25"}
    assert body["minimumMembers"] == MIN_MEMBERS and body["generatedBy"] == "template"
    assert all(s["evidenceId"] in body["evidence"] for s in body["sections"])
    # Only the two who share, alphabetically, each with the four levels.
    assert [row["member"] for row in body["levels"]] == [
        "member01@example.com",
        "member03@example.com",
    ]
    assert set(body["levels"][0]["levels"]) == {
        "recovery_score",
        "sleep_minutes",
        "strain",
        "stress_score",
    }
    listed = client.get(f"/teams/{team_id}/reports", headers=boss).json()
    assert [r["week"]["start"] for r in listed] == ["2026-10-19"]
    again = client.get(f"/teams/{team_id}/reports/2026-10-22", headers=boss)  # any day of it
    assert again.status_code == 200
    with session_scope(engine) as db:
        viewed = db.scalars(select(TeamEvent).where(TeamEvent.event == "levels_viewed")).all()
        assert len(viewed) == 2


def test_a_member_who_stops_sharing_disappears_from_past_weeks(client, engine):
    team_id, _ = team_with(engine, 5, sharing=(0,))
    boss = signed_in(client, engine, "boss@example.com", "supervisor")
    client.post(f"/teams/{team_id}/reports", json={}, headers=boss)
    member = signed_in(client, engine, "member00@example.com")
    client.post(f"/me/teams/{team_id}/levels", json={"share": False}, headers=member)
    past = client.get(f"/teams/{team_id}/reports/2026-10-19", headers=boss).json()
    assert past["levels"] == []


def test_reports_are_for_the_teams_supervisor_and_full_weeks_only(client, engine):
    team_id, _ = team_with(engine, 5)
    boss = signed_in(client, engine, "boss@example.com", "supervisor")
    this_week = client.post(f"/teams/{team_id}/reports", json={"week": "2026-10-27"}, headers=boss)
    assert this_week.json()["error"]["code"] == "week_not_over"
    missing = client.get(f"/teams/{team_id}/reports/2026-09-07", headers=boss)
    assert missing.status_code == 404
    other = signed_in(client, engine, "other@example.com", "supervisor")
    assert client.get(f"/teams/{team_id}/reports", headers=other).status_code == 404
    member = signed_in(client, engine, "member00@example.com")
    assert client.post(f"/teams/{team_id}/reports", json={}, headers=member).status_code == 403


# The model-written prose


def writing_from_payload(messages):
    """A scripted model that writes one sound paragraph per change in what it was given."""
    items = json.loads(messages[-1]["content"].split("\n\n", 1)[1])
    paragraphs = []
    for item in items:
        if item.get("changed"):
            down = item["median_change"].startswith("-")
            paragraphs.append(
                {
                    "text": f"{item['label']} {'fell' if down else 'rose'} across the team: "
                    f"median change {item['median_change']}.",
                    "kind": "change",
                    "metric": item["metric"],
                    "direction": "down" if down else "up",
                    "evidence_ids": [item["evidence_id"]],
                }
            )
    return ScriptedLLM.call(
        WRITE, cost_usd=0.004, headline="The team slept less this week.", paragraphs=paragraphs
    )


def test_a_model_written_report_keeps_the_figures_and_records_its_cost(engine):
    team_id, _ = team_with(engine, 6, (Step("sleep_minutes", WEEK.start, -70),))
    with session_scope(engine) as db:
        report = reports.build_report(
            db, db.get(Team, team_id), WEEK, NOW, ScriptedLLM([writing_from_payload])
        )
        assert report.generated_by == "model" and report.cost_usd == pytest.approx(0.004)
        assert report.headline == "The team slept less this week."
        assert report.body["narrative"] and report.body["sections"]  # prose over the figures


def test_a_report_whose_prose_fails_its_checks_stays_templated(engine):
    team_id, _ = team_with(engine, 6, (Step("sleep_minutes", WEEK.start, -70),))
    careless = ScriptedLLM.call(
        WRITE,
        headline="One member is struggling.",
        paragraphs=[
            {"text": "Sleep is fine.", "kind": "pattern", "metric": "x", "evidence_ids": ["x"]}
        ],
    )
    with session_scope(engine) as db:
        report = reports.build_report(
            db, db.get(Team, team_id), WEEK, NOW, ScriptedLLM([careless, careless])
        )
        assert report.generated_by == "template" and "narrative" not in report.body
        assert report.body["narrative_problems"]
        assert "struggling" not in report.headline


def test_the_api_serves_the_prose_when_it_is_switched_on(client, engine, monkeypatch):
    team_id, _ = team_with(engine, 6, (Step("sleep_minutes", WEEK.start, -70),))
    monkeypatch.setattr(teams, "report_writer", lambda: ScriptedLLM([writing_from_payload]))
    boss = signed_in(client, engine, "boss@example.com", "supervisor")
    body = client.post(f"/teams/{team_id}/reports", json={}, headers=boss).json()
    assert body["generatedBy"] == "model"
    assert body["narrative"] and all(
        set(p["evidenceIds"]) <= set(body["evidence"]) for p in body["narrative"]
    )


def test_made_up_members_fill_a_team_for_a_ready_report(engine, monkeypatch, capsys):
    from app.teams import __main__ as cli

    with session_scope(engine) as db:
        boss = User(email="boss@example.com", status="approved", role="supervisor")
        db.add(boss)
        db.flush()
        code = memberships.create_team(db, boss, "Design", None, NOW).invite_code
    monkeypatch.setattr(cli, "session_scope", lambda: session_scope(engine))
    monkeypatch.setattr(cli, "datetime", type("Clock", (), {"now": staticmethod(lambda _: NOW)}))

    assert cli.main(["demo-members", code, "--count", "6", "--sharing", "2"]) == 0
    assert "6 made-up members created, 6 joined, 2 sharing" in capsys.readouterr().out
    # Again: the same people, their data replaced, nobody joined twice.
    assert cli.main(["demo-members", code, "--count", "6", "--sharing", "2"]) == 0
    assert "0 made-up members created, 0 joined" in capsys.readouterr().out

    with session_scope(engine) as db:
        team = db.scalar(select(Team))
        assert memberships.active_members(db, team) == 6
    report = report_for(engine, team.id)
    assert report.status == "ready" and report.members_included == 6
    sleep = next(s for s in report.body["sections"] if s["metric"] == "sleep_minutes")
    assert sleep["status"] == "changed"
    stress = next(s for s in report.body["sections"] if s["metric"] == "stress_score")
    assert "not enough" not in stress["text"].lower()
    with session_scope(engine) as db:
        shared = reports.shared_levels(db, db.get(Team, team.id), WEEK)
    assert len(shared) == 2


@pytest.mark.parametrize(
    ("argv", "url"),
    [
        (["demo-members", "NOPE2345"], "sqlite:///local.db"),
        (["demo-members", "ANY", "--count", "0"], "sqlite:///local.db"),
        (["demo-members", "ANY"], "postgresql://u:p@db.example.net:5432/app"),
    ],
)
def test_made_up_members_are_refused_where_they_do_not_belong(engine, monkeypatch, argv, url):
    from app.teams import __main__ as cli

    monkeypatch.setattr(cli, "session_scope", lambda: session_scope(engine))
    monkeypatch.setattr(cli.settings, "database_url", url)
    assert cli.main(argv) == 1
    with session_scope(engine) as db:
        assert db.scalar(select(User)) is None


# What the report leads with


def test_a_lasting_concern_leads_with_the_note_it_lined_up_with(engine):
    from app.db.models import TeamNote

    began = WEEK.start - timedelta(days=14)  # three weeks running by the report's week
    team_id, _ = team_with(engine, 8, (Step("sleep_minutes", began, -70),))
    with session_scope(engine) as db:
        db.add(
            TeamNote(
                team_id=team_id,
                text="Release crunch",
                starts_on=began - timedelta(days=3),
                created_at=NOW,
            )
        )
    report = report_for(engine, team_id)
    first = report.body["priorities"][0]
    assert (first["metric"], first["kind"], first["status"]) == (
        "sleep_minutes",
        "concern",
        "lasting",
    )
    assert first["text"].startswith("Time asleep has been lower for 3 weeks running")
    assert "lined up with your note: Release crunch" in first["text"]
    assert report.headline.startswith("Needs attention: Time asleep has been lower")
    assert first["evidence_id"] in report.evidence


def test_good_news_comes_after_concerns_and_a_quiet_week_says_so(engine):
    from app.teams.reports import headline_from, priorities  # noqa: F401

    found = [
        {"kind": "improvement", "status": "new", "text": "Steps rose this week: x."},
        {"kind": "concern", "status": "new", "text": "Time asleep fell this week: x."},
        {"kind": "concern", "status": "lasting", "text": "HRV has been lower for 2 weeks: x."},
        {"kind": "change", "status": "lasting", "text": "Strain has been higher for 3 weeks: x."},
    ]
    from app.teams.reports import KIND_ORDER, STATUS_ORDER

    ordered = sorted(found, key=lambda f: (KIND_ORDER[f["kind"]], STATUS_ORDER[f["status"]]))
    assert [f["text"][:4] for f in ordered] == ["HRV ", "Time", "Stra", "Step"]
    assert (
        headline_from(ordered) == "Needs attention: HRV has been lower for 2 weeks (3 more below)."
    )
    assert headline_from([]) is None


def test_a_steady_team_has_no_priorities(engine):
    team_id, _ = team_with(engine, 7)
    report = report_for(engine, team_id)
    assert report.body["priorities"] == [] and report.body["challenges"] == []


def test_an_ended_challenge_says_whether_it_moved_its_metric(engine):
    from app.db.models import TeamAction

    team_id, _ = team_with(engine, 8, (Step("sleep_minutes", WEEK.start - timedelta(days=7), 60),))
    with session_scope(engine) as db:
        db.add(
            TeamAction(
                team_id=team_id,
                kind="challenge",
                title="Lights out by 23:00",
                body="b",
                metric="sleep_minutes",
                status="approved",
                starts_on=WEEK.start - timedelta(days=7),
                ends_on=WEEK.end,
                proposed_at=NOW,
            )
        )
    (row,) = report_for(engine, team_id).body["challenges"]
    assert row["text"].startswith("Lights out by 23:00: time asleep rose during it")
