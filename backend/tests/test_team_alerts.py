"""Alerts on a team's aggregate: raised once, closed when over, and never about a person."""

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select

from app.analysis import team as stats
from app.analysis.evidence import Evidence, Window
from app.analysis.team import ALERT_DAYS_HELD, MIN_MEMBERS, TeamAlerts, team_alerts, team_info
from app.db.models import Notification, Team, TeamAlert, User
from app.db.session import session_scope
from app.email import Email, MailError
from app.teams import alerts, memberships

NOW = datetime(2026, 10, 26, 9, tzinfo=UTC)
END = date(2026, 10, 25)


class Mail:
    def __init__(self, fails: bool = False) -> None:
        self.sent: list[Email] = []
        self.fails = fails

    def send(self, email: Email) -> None:
        if self.fails:
            raise MailError("down")
        self.sent.append(email)


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


@pytest.fixture
def team_id(engine):
    with session_scope(engine) as db:
        boss = User(email="boss@example.com", status="approved", role="supervisor")
        db.add(boss)
        db.flush()
        return memberships.create_team(db, boss, "Design", None, NOW).id


def raised(metric="sleep_minutes", direction="down", median=-32.0, kind="concern") -> Evidence:
    window = Window(start=END - timedelta(days=6), end=END)
    return Evidence(
        tool="team_alert",
        metrics=(metric,),
        windows=(window,),
        n=7,
        sufficient=True,
        stats={
            "area": "sleep",
            "direction": direction,
            "kind": kind,
            "held_days": ALERT_DAYS_HELD,
            "members": 7,
            "median_change": median,
            "members_up": 1,
            "members_down": 6,
        },
    )


def check(engine, team_id, monkeypatch, found: TeamAlerts, now=NOW) -> list[str]:
    monkeypatch.setattr(alerts, "team_alerts", lambda frames, end: found)
    monkeypatch.setattr(alerts, "_member_frames", lambda db, team, window: [])
    with session_scope(engine) as db:
        new = alerts.check_team(db, db.get(Team, team_id), END, now)
        return [a.metric for a in new]


def moving(*items) -> TeamAlerts:
    return TeamAlerts(list(items), {(e.metrics[0], e.stats["direction"]) for e in items})


def test_a_change_is_raised_once_while_it_lasts(engine, team_id, monkeypatch):
    assert check(engine, team_id, monkeypatch, moving(raised())) == ["sleep_minutes"]
    later = NOW + timedelta(days=1)
    assert check(engine, team_id, monkeypatch, moving(raised()), later) == []


def test_several_areas_are_raised_together(engine, team_id, monkeypatch):
    found = moving(raised(), raised("resting_hr", "up", 3.0))
    assert set(check(engine, team_id, monkeypatch, found)) == {"sleep_minutes", "resting_hr"}


def test_an_alert_closes_when_the_change_ends_and_stays_quiet_for_a_while(
    engine, team_id, monkeypatch
):
    check(engine, team_id, monkeypatch, moving(raised()))
    check(engine, team_id, monkeypatch, TeamAlerts([], set()), NOW + timedelta(days=5))
    with session_scope(engine) as db:
        assert db.scalar(select(TeamAlert)).resolved_at is not None
    soon = NOW + timedelta(days=8)
    assert check(engine, team_id, monkeypatch, moving(raised()), soon) == []
    later = NOW + timedelta(days=5) + alerts.COOLDOWN + timedelta(days=1)
    assert check(engine, team_id, monkeypatch, moving(raised()), later) == ["sleep_minutes"]


def test_the_other_direction_is_a_new_change(engine, team_id, monkeypatch):
    check(engine, team_id, monkeypatch, moving(raised()))
    up = raised(direction="up", median=30.0)
    assert check(engine, team_id, monkeypatch, moving(up), NOW + timedelta(days=1)) == [
        "sleep_minutes"
    ]


def test_the_supervisor_is_told_in_the_app_and_by_email_with_team_figures_only(engine, team_id):
    mail = Mail()
    with session_scope(engine) as db:
        team = db.get(Team, team_id)
        alert = TeamAlert(
            team_id=team.id,
            metric="sleep_minutes",
            direction="down",
            text=alerts.alert_text(raised()),
            evidence={},
            raised_at=NOW,
        )
        db.add(alert)
        db.flush()
        alerts.deliver(db, team, [alert], NOW, mail, "https://app.example")
        note = db.scalar(select(Notification))
        assert note.kind == "team_alert" and note.link == "/team"
        assert note.user_id == team.supervisor_id
        assert "6 of 7 people" in note.body and "member" not in note.body.lower()
    assert len(mail.sent) == 1 and mail.sent[0].to == "boss@example.com"
    assert "not any one person" in mail.sent[0].text


def test_a_mail_failure_keeps_the_alert_in_the_app(engine, team_id):
    with session_scope(engine) as db:
        team = db.get(Team, team_id)
        alert = TeamAlert(
            team_id=team.id,
            metric="steps",
            direction="down",
            text="x",
            evidence={},
            raised_at=NOW,
        )
        db.add(alert)
        db.flush()
        alerts.deliver(db, team, [alert], NOW, Mail(fails=True), "https://app.example")
        assert db.scalar(select(Notification)) is not None


def test_the_daily_pass_runs_once_and_one_team_failing_stops_no_other(engine, team_id, monkeypatch):
    monkeypatch.setattr(alerts, "_last_run", None)
    with session_scope(engine) as db:
        boss = db.scalar(select(User))
        memberships.create_team(db, boss, "Sales", None, NOW)
    calls = []

    def failing_first(db, team, end, now, ended=None):
        calls.append(team.name)
        if len(calls) == 1:
            raise ValueError("broken")
        return []

    monkeypatch.setattr(alerts, "check_team", failing_first)
    sessions = lambda: session_scope(engine)  # noqa: E731
    counts = alerts.run_due(sessions, NOW, Mail(), "https://app.example")
    assert counts["errors"] == 1 and len(calls) == 2
    assert alerts.run_due(sessions, NOW, Mail(), "https://app.example") == {}


def test_nothing_runs_before_the_morning_syncs(engine, monkeypatch):
    monkeypatch.setattr(alerts, "_last_run", None)
    early = NOW.replace(hour=2)
    assert alerts.run_due(lambda: session_scope(engine), early, Mail(), "x") == {}
    assert alerts._last_run is None


def plain_member(rng, shift: float = 0.0) -> pd.DataFrame:
    days = 60
    index = pd.date_range(END - timedelta(days=days - 1), periods=days, freq="D")
    values = rng.normal(420, 40, days)
    values[-10:] += shift * 40
    return pd.DataFrame({"sleep_minutes": values}, index=index)


def test_fewer_people_than_the_floor_give_no_alert():
    rng = np.random.default_rng(1)
    frames = [plain_member(rng, -2.0) for _ in range(MIN_MEMBERS - 1)]
    assert team_alerts(frames, END) == TeamAlerts([], set())


def test_a_large_change_held_for_days_is_raised_with_aggregates_only():
    rng = np.random.default_rng(2)
    found = team_alerts([plain_member(rng, -2.0) for _ in range(12)], END)
    assert [e.metrics[0] for e in found.raised] == ["sleep_minutes"]
    assert set(found.raised[0].stats) == {
        "area",
        "direction",
        "kind",
        "held_days",
        "members",
        "median_change",
        "members_up",
        "members_down",
    }


def test_the_supervisor_reads_physical_stress_signs_not_stress():
    assert team_info("stress_score").label == "Physical stress signs"
    assert stats.team_info("sleep_minutes").label != "Physical stress signs"


# What deserves an alert, and how it is told


def test_a_change_must_be_big_and_broad_enough_as_well_as_real():
    from app.analysis.team import worthwhile

    big = {
        "median_change": -45.0,
        "median_standardized_change": -0.9,
        "members": 10,
        "members_up": 2,
        "members_down": 8,
    }
    assert worthwhile("sleep_minutes", big, "down")
    assert not worthwhile("sleep_minutes", big | {"median_change": -12.0}, "down")  # floor
    assert not worthwhile("sleep_minutes", big | {"median_standardized_change": -0.2}, "down")
    assert not worthwhile("sleep_minutes", big | {"members_up": 5, "members_down": 5}, "down")
    assert not worthwhile("sleep_minutes", big, "up")  # the median says otherwise


def test_concerns_and_good_news_are_told_apart():
    from app.analysis.team import kind_of

    assert kind_of("sleep_minutes", "down") == "concern"
    assert kind_of("resting_hr", "up") == "concern"
    assert kind_of("steps", "up") == "improvement"
    assert kind_of("strain", "up") == "change" and kind_of("bedtime_hour", "down") == "change"


def test_a_real_but_tiny_change_in_a_large_team_is_not_raised():
    """With 30 people a 12-minute drop is real; it is not worth a supervisor's attention."""
    rng = np.random.default_rng(4)
    found = team_alerts([plain_member(rng, -0.3) for _ in range(30)], END)
    assert found.raised == []


def test_good_news_waits_for_the_report_and_an_ended_concern_says_so(engine, team_id):
    mail = Mail()
    with session_scope(engine) as db:
        team = db.get(Team, team_id)
        good = TeamAlert(
            team_id=team.id,
            metric="steps",
            direction="up",
            kind="improvement",
            text="Steps rose.",
            evidence={},
            raised_at=NOW,
        )
        over = TeamAlert(
            team_id=team.id,
            metric="sleep_minutes",
            direction="down",
            kind="concern",
            text="Sleep fell.",
            evidence={},
            raised_at=NOW,
        )
        db.add_all([good, over])
        db.flush()
        alerts.deliver(db, team, [good], NOW, mail, "https://app.example", ended=[over])
        told = [(n.title, n.body) for n in db.scalars(select(Notification))]
    assert mail.sent == []  # nothing urgent: no email
    assert told == [("Design: back to usual", "The team's time asleep is back to usual.")]


def test_sleep_and_recovery_concerns_together_are_one_story(engine, team_id):
    mail = Mail()
    with session_scope(engine) as db:
        team = db.get(Team, team_id)
        rows = [
            TeamAlert(
                team_id=team.id,
                metric=m,
                direction=d,
                kind="concern",
                text=f"{m} moved.",
                evidence={},
                raised_at=NOW,
            )
            for m, d in (("sleep_minutes", "down"), ("resting_hr", "up"))
        ]
        db.add_all(rows)
        db.flush()
        alerts.deliver(db, team, rows, NOW, mail, "https://app.example")
    assert mail.sent[0].subject == "Design: sleep and recovery moved together"


def test_an_alert_names_the_note_it_lined_up_with(engine, team_id, monkeypatch):
    from app.db.models import TeamNote

    with session_scope(engine) as db:
        db.add(
            TeamNote(
                team_id=team_id,
                text="Release deadline",
                starts_on=END - timedelta(days=9),
                created_at=NOW,
            )
        )
        db.add(
            TeamNote(
                team_id=team_id, text="Offsite", starts_on=END - timedelta(days=40), created_at=NOW
            )
        )
    found = TeamAlerts([raised()], {("sleep_minutes", "down")})
    assert check(engine, team_id, monkeypatch, found) == ["sleep_minutes"]
    with session_scope(engine) as db:
        text = db.scalar(select(TeamAlert.text))
    assert "lined up with your note: Release deadline" in text and "Offsite" not in text
