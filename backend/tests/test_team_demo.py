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
from app.db.models import DemoAccount, DemoTeam, Team, TeamMembership, User  # noqa: E402
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
    # Beside a sleep drop lasting three weeks, the calendar line must not say nothing changed
    # (seen on production, 2026-11-26: the week itself was steady against the week before).
    [change] = [i for i in items if i["kind"] == "change"]
    [calendar_line] = [i for i in items if i["kind"] == "calendar"]
    assert "3 weeks" in change["text"]
    assert calendar_line["text"].startswith("In the same week, the team's calendars were busier")
    assert "no clear change" not in calendar_line["text"]


def test_a_team_too_small_shows_no_figures(engine):  # noqa: F811
    boss_id = presenter(engine)
    with session_scope(engine) as db:
        boss = db.get(User, boss_id)
        team, _ = demo.create_demo_team(
            db, boss, "Too few (synthetic)", 3, "demo-few", False, BRIEF_NOW.date(), BRIEF_NOW
        )
        report = reports.build_report(db, team, reports.last_full_week(BRIEF_NOW.date()), BRIEF_NOW)
        assert report.status == "withheld"


def _cascading(engine) -> None:  # noqa: F811
    from sqlalchemy import event

    # SQLite cascades deletes only with foreign keys on; PostgreSQL, as deployed, always does.
    @event.listens_for(engine, "connect")
    def _fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")


def _make(db, boss_id, name: str, count: int, prefix: str):
    boss = db.get(User, boss_id)
    team, _ = demo.create_demo_team(
        db, boss, name, count, prefix, False, BRIEF_NOW.date(), BRIEF_NOW
    )
    return team


def test_removing_deletes_what_the_command_made_even_a_member_who_left(engine):  # noqa: F811
    _cascading(engine)
    boss_id = presenter(engine)
    with session_scope(engine) as db:
        team = _make(db, boss_id, "Demo (synthetic)", 5, "demo-a")
        gone = db.scalar(select(User).where(User.email == "demo-a-5@example.com"))
        memberships.leave(db, gone, str(team.id), BRIEF_NOW)
        assert demo.remove_demo_team(db, team) == 5
    with session_scope(engine) as db:
        assert db.scalar(select(func.count()).select_from(Team)) == 0
        assert db.scalar(select(func.count()).select_from(TeamMembership)) == 0
        assert db.scalar(select(func.count()).select_from(DemoAccount)) == 0
        assert db.scalar(select(func.count()).select_from(DemoTeam)) == 0
        assert db.scalar(select(User).where(User.email.like("demo-a%"))) is None
        assert db.get(User, boss_id) is not None  # the presenter stays


def test_removal_never_touches_an_account_the_command_did_not_make(engine):  # noqa: F811
    # Review, 2026-11-26: an email that only looks made up ("demo...", "...example.com") is not
    # proof; removal goes by the ids recorded when the team was made.
    _cascading(engine)
    boss_id = presenter(engine)
    with session_scope(engine) as db:
        team = _make(db, boss_id, "Demo (synthetic)", 5, "demo-b")
        lookalike = User(email="demo-user@myexample.com", status="approved")
        db.add(lookalike)
        db.flush()
        memberships.join(db, team, lookalike, BRIEF_NOW)
        memberships.leave(db, lookalike, str(team.id), BRIEF_NOW)  # even one who has left
        with pytest.raises(demo.DemoTeamError, match="did not make joined"):
            demo.remove_demo_team(db, team)
        # A team labelled synthetic by hand is not one the command made.
        boss = db.get(User, boss_id)
        by_hand = memberships.create_team(db, boss, "Look (synthetic)", None, BRIEF_NOW)
        memberships.join(db, by_hand, lookalike, BRIEF_NOW)
        with pytest.raises(demo.DemoTeamError, match="did not make this team"):
            demo.remove_demo_team(db, by_hand)
        lookalike_id = lookalike.id
    with session_scope(engine) as db:
        assert db.get(User, lookalike_id) is not None
        assert db.scalar(select(func.count()).select_from(Team)) == 2
        assert db.scalar(select(func.count()).select_from(DemoAccount)) == 5


def test_the_command_needs_a_flag_on_a_deployed_database(monkeypatch, capsys):
    from app.teams import __main__ as cli

    monkeypatch.setattr(cli.settings, "database_url", "postgresql://u:p@db.example.net/x")
    code = cli.main(["demo-team", "--supervisor", "a@b.c", "--name", "Demo (synthetic)"])
    assert code == 1 and "--on-production" in capsys.readouterr().err


def test_two_demo_teams_never_share_made_up_members(engine):  # noqa: F811
    _cascading(engine)
    boss_id = presenter(engine)
    with session_scope(engine) as db:
        boss = db.get(User, boss_id)
        first = _make(db, boss_id, "Demo (synthetic)", 8, "demo-member")
        # The same prefix would reuse demo-member-1..3 and overwrite their data.
        with pytest.raises(demo.DemoTeamError, match="already exist"):
            _make(db, boss_id, "Few (synthetic)", 3, "demo-member")
        few = _make(db, boss_id, "Few (synthetic)", 3, "demo-few")
        # A made-up member who joined another team stops the removal of their demo team.
        other = memberships.create_team(db, boss, "Design", None, BRIEF_NOW)
        shared = db.scalar(select(User).where(User.email == "demo-member-1@example.com"))
        memberships.join(db, other, shared, BRIEF_NOW)
        with pytest.raises(demo.DemoTeamError, match="another team"):
            demo.remove_demo_team(db, first)
        # Removing one demo team leaves the other whole.
        assert demo.remove_demo_team(db, few) == 3
        first_id = first.id
    with session_scope(engine) as db:
        assert memberships.active_members(db, db.get(Team, first_id)) == 8
