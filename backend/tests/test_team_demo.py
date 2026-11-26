"""The made-up demo team (app/teams/demo.py): calendar days as a sync stores them, busier in the
week the report covers, and never on weekends."""

from datetime import date, timedelta

from app.teams.demo import MEETING_RISE, _calendar_days

TODAY = date(2026, 11, 26)
BUSY = date(2026, 11, 16)


def test_calendar_days_are_counts_up_to_yesterday_and_empty_at_weekends():
    days = _calendar_days(TODAY - timedelta(days=120), TODAY, BUSY, seed=0)
    assert days.index[-1].date() == TODAY - timedelta(days=1)
    assert set(days.columns) == {
        "meeting_minutes",
        "meetings",
        "after_hours_minutes",
        "back_to_back",
        "focus_minutes",
        "out_of_office",
    }
    weekend = days[days.index.weekday >= 5]
    assert (weekend["meetings"] == 0).all() and (weekend["meeting_minutes"] == 0).all()
    assert (days >= 0).all().all()


def test_the_report_week_is_busier_for_most_members():
    busier = 0
    for seed in range(20):
        days = _calendar_days(TODAY - timedelta(days=120), TODAY, BUSY, seed)
        week = days.loc[str(BUSY) : str(BUSY + timedelta(days=6)), "meetings"].sum()
        usual = days.loc[: str(BUSY - timedelta(days=1)), "meetings"].sum() / (
            (BUSY - (TODAY - timedelta(days=120))).days / 7
        )
        busier += week > usual
    assert MEETING_RISE > 1 and busier >= 17


# The labelled demo team for presentations


import pytest  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from test_team_briefing import NOW as BRIEF_NOW  # noqa: E402
from test_team_briefing import engine  # noqa: E402, F401

from app.agent.llm import ScriptedLLM  # noqa: E402
from app.db.models import Team, TeamMembership, User  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.teams import demo, memberships, reports  # noqa: E402
from app.teams.briefing import brief  # noqa: E402


def presenter(engine):  # noqa: F811
    with session_scope(engine) as db:
        boss = User(email="lead@example.org", status="approved", role="supervisor")
        db.add(boss)
        db.flush()
        return boss.id


def test_a_demo_team_must_be_labelled_and_is_never_an_existing_team(engine):  # noqa: F811
    boss_id = presenter(engine)
    with session_scope(engine) as db:
        boss = db.get(User, boss_id)
        with pytest.raises(demo.DemoTeamError, match="synthetic"):
            demo.create_demo_team(
                db, boss, "Design", 6, "demo-a", False, BRIEF_NOW.date(), BRIEF_NOW
            )
        team, added = demo.create_demo_team(
            db, boss, "Demo (synthetic)", 6, "demo-a", True, BRIEF_NOW.date(), BRIEF_NOW
        )
        assert added.created == 6 and memberships.active_members(db, team) == 6
        with pytest.raises(demo.DemoTeamError, match="already has"):
            demo.create_demo_team(
                db, boss, "Demo (synthetic)", 6, "demo-b", False, BRIEF_NOW.date(), BRIEF_NOW
            )


def test_the_rehearsed_demo_gives_a_finding_its_calendar_and_one_change_to_approve(engine):  # noqa: F811
    boss_id = presenter(engine)
    with session_scope(engine) as db:
        boss = db.get(User, boss_id)
        team, _ = demo.create_demo_team(
            db, boss, "Demo (synthetic)", 8, "demo-a", True, BRIEF_NOW.date(), BRIEF_NOW
        )
        week = reports.last_full_week(BRIEF_NOW.date())
        report = reports.build_report(db, team, week, BRIEF_NOW)
        brief(ScriptedLLM([]), db, team, report, BRIEF_NOW.date(), BRIEF_NOW, 0.1)
        items = report.body["briefing"]["items"]
    kinds = [i["kind"] for i in items]
    assert "change" in kinds and "calendar" in kinds and "proposal" in kinds
    [proposal] = [i for i in items if i["kind"] == "proposal"]
    assert "evening boundary" in proposal["text"] and "after hours rose" in proposal["text"]


def test_a_team_too_small_shows_no_figures(engine):  # noqa: F811
    boss_id = presenter(engine)
    with session_scope(engine) as db:
        boss = db.get(User, boss_id)
        team, _ = demo.create_demo_team(
            db, boss, "Too few (synthetic)", 3, "demo-few", False, BRIEF_NOW.date(), BRIEF_NOW
        )
        report = reports.build_report(db, team, reports.last_full_week(BRIEF_NOW.date()), BRIEF_NOW)
        assert report.status == "withheld"


def test_removing_takes_the_team_and_its_made_up_accounts_and_never_a_real_team(engine):  # noqa: F811
    from sqlalchemy import event

    # SQLite cascades deletes only with foreign keys on; PostgreSQL, as deployed, always does.
    @event.listens_for(engine, "connect")
    def _fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    boss_id = presenter(engine)
    with session_scope(engine) as db:
        boss = db.get(User, boss_id)
        team, _ = demo.create_demo_team(
            db, boss, "Demo (synthetic)", 5, "demo-a", False, BRIEF_NOW.date(), BRIEF_NOW
        )
        assert demo.remove_demo_team(db, team) == 5
    with session_scope(engine) as db:
        assert db.scalar(select(func.count()).select_from(Team)) == 0
        assert db.scalar(select(func.count()).select_from(TeamMembership)) == 0
        assert db.scalar(select(User).where(User.email.like("demo-a%"))) is None
        assert db.get(User, boss_id) is not None  # the presenter stays
        boss = db.get(User, boss_id)
        team, _ = demo.create_demo_team(
            db, boss, "Demo (synthetic)", 5, "demo-b", False, BRIEF_NOW.date(), BRIEF_NOW
        )
        real = User(email="someone@realcompany.com", status="approved")
        db.add(real)
        db.flush()
        memberships.join(db, team, real, BRIEF_NOW)
        with pytest.raises(demo.DemoTeamError, match="real members"):
            demo.remove_demo_team(db, team)


def test_the_command_needs_a_flag_on_a_deployed_database(monkeypatch, capsys):
    from app.teams import __main__ as cli

    monkeypatch.setattr(cli.settings, "database_url", "postgresql://u:p@db.example.net/x")
    code = cli.main(["demo-team", "--supervisor", "a@b.c", "--name", "Demo (synthetic)"])
    assert code == 1 and "--on-production" in capsys.readouterr().err


def test_two_demo_teams_never_share_made_up_members(engine):  # noqa: F811
    boss_id = presenter(engine)
    with session_scope(engine) as db:
        boss = db.get(User, boss_id)
        first, _ = demo.create_demo_team(
            db, boss, "Demo (synthetic)", 8, "demo-member", True, BRIEF_NOW.date(), BRIEF_NOW
        )
        # The same prefix would reuse demo-member-1..3 and overwrite their data.
        with pytest.raises(demo.DemoTeamError, match="already exist"):
            demo.create_demo_team(
                db, boss, "Few (synthetic)", 3, "demo-member", False, BRIEF_NOW.date(), BRIEF_NOW
            )
        assert db.scalar(select(func.count()).select_from(Team)) == 1
        # Made some other way, a member shared with another team stops the removal.
        second = memberships.create_team(db, boss, "Few (synthetic)", None, BRIEF_NOW)
        shared = db.scalar(select(User).where(User.email == "demo-member-1@example.com"))
        memberships.join(db, second, shared, BRIEF_NOW)
        with pytest.raises(demo.DemoTeamError, match="another team"):
            demo.remove_demo_team(db, second)
        assert memberships.active_members(db, first) == 8
