# ruff: noqa: F811 (the fixtures imported from test_team_agent)
"""Observed team figures: shown from the first sync once 5 members have a reading, never a change
from usual (that still needs each member's history), and only to the team's supervisor."""

import uuid
from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from test_team_agent import NOW, TODAY, client, engine, signed_in  # noqa: F401

from app.analysis.team import MIN_MEMBERS, team_observed, team_statistics, week_of
from app.db.daily import save_daily
from app.db.models import Team, User
from app.db.session import session_scope
from app.teams import memberships
from app.teams.observed import sentence


def two_days(sleep: float, steps: float, wear: float = 900.0) -> pd.DataFrame:
    """A brand-new Fitbit: last night's sleep and yesterday's steps, nothing earlier."""
    days = pd.date_range(TODAY - timedelta(days=1), TODAY, name="date")
    return pd.DataFrame(
        {
            "sleep_minutes": [sleep, sleep],
            "steps": [steps, np.nan],  # today's steps are not over yet
            "wear_minutes": [wear, wear],
            "resting_hr": [60.0, 60.0],
            "hrv_ms": [45.0, 45.0],
        },
        index=days,
    )


def new_team(engine, sleeps: list[float]) -> str:
    with session_scope(engine) as db:
        boss = User(email="boss@example.com", status="approved", role="supervisor")
        db.add(boss)
        db.flush()
        team = memberships.create_team(db, boss, "Design", None, NOW)
        for i, sleep in enumerate(sleeps):
            person = User(email=f"member{i:02d}@example.com", status="approved")
            db.add(person)
            db.flush()
            save_daily(db, person.id, "google_health", two_days(sleep, 8000.0 + 100 * i))
            memberships.join(db, team, person, NOW)
        return str(team.id)


SLEEPS = [400.0, 410.0, 430.0, 440.0, 450.0, 460.0]  # median 435: 7 h 15 min


def test_figures_show_from_the_first_days_without_history():
    frames = [two_days(s, 8000.0 + 100 * i) for i, s in enumerate(SLEEPS)]
    found = {e.metrics[0]: e for e in team_observed(frames, TODAY)}
    sleep = found["sleep_minutes"]
    assert sleep.n == 6 and sleep.stats["median"] == 435.0
    assert sleep.windows[0].end == TODAY  # last night
    assert sentence(sleep, TODAY) == "Median sleep last night: 7 h 15 min, based on 6 members."
    steps = found["steps"]
    assert steps.windows[0].end == TODAY - timedelta(days=1)  # the last whole day
    assert sentence(steps, TODAY) == "Median steps yesterday: 8,250, based on 6 members."
    resting = found["resting_hr"]  # Fitbit's daily value: named by its date, not "last night"
    assert sentence(resting, TODAY) == (
        f"Median resting heart rate on {TODAY:%b} {TODAY.day}: 60 bpm, based on 6 members."
    )
    assert "last night" in sentence(found["hrv_ms"], TODAY)  # measured while asleep


def test_never_from_fewer_than_five_people():
    frames = [two_days(s, 8000.0) for s in SLEEPS[: MIN_MEMBERS - 1]]
    assert team_observed(frames, TODAY) == []


def test_a_metric_with_too_few_readings_is_left_out_alone():
    frames = [two_days(s, 8000.0) for s in SLEEPS]
    for frame in frames[2:]:
        frame["hrv_ms"] = np.nan  # only two people have HRV
    metrics = {e.metrics[0] for e in team_observed(frames, TODAY)}
    assert "hrv_ms" not in metrics and "sleep_minutes" in metrics


def test_the_latest_night_with_enough_people_is_used_and_named():
    frames = [two_days(s, 8000.0) for s in SLEEPS]
    for frame in frames[:3]:
        frame.loc[pd.Timestamp(TODAY), "sleep_minutes"] = np.nan  # three have not synced today
    sleep = next(e for e in team_observed(frames, TODAY) if e.metrics[0] == "sleep_minutes")
    assert sleep.windows[0].end == TODAY - timedelta(days=1)
    assert sentence(sleep, TODAY).startswith("Median sleep the night to ")


def test_nothing_older_than_three_days():
    frames = [two_days(s, 8000.0) for s in SLEEPS]
    assert team_observed(frames, TODAY + timedelta(days=5)) == []


def test_barely_worn_days_do_not_count_for_activity():
    frames = [two_days(s, 8000.0, wear=300.0) for s in SLEEPS]  # under 10 hours worn
    assert "steps" not in {e.metrics[0] for e in team_observed(frames, TODAY)}


def test_observed_figures_never_claim_a_change():
    frames = [two_days(s, 8000.0) for s in SLEEPS]
    for e in team_observed(frames, TODAY):
        text = sentence(e, TODAY).lower()
        for word in ("usual", "fell", "rose", "lower", "higher", "change", "than"):
            assert word not in text
        assert set(e.stats) == {"median", "kind"}


def test_the_supervisor_sees_them_at_once_and_nobody_else(engine, client):
    client, _ = client
    team_id = new_team(engine, SLEEPS)
    boss = signed_in(client, engine, "boss@example.com")
    body = client.get(f"/teams/{team_id}/observed", headers=boss).json()
    texts = [f["text"] for f in body["figures"]]
    assert "Median sleep last night: 7 h 15 min, based on 6 members." in texts
    assert "member0" not in str(body)
    member = signed_in(client, engine, "member00@example.com")
    assert client.get(f"/teams/{team_id}/observed", headers=member).status_code == 403
    with session_scope(engine) as db:
        other = User(email="other@example.com", status="approved", role="supervisor")
        db.add(other)
    other = signed_in(client, engine, "other@example.com")
    assert client.get(f"/teams/{team_id}/observed", headers=other).status_code == 404


def test_a_change_from_usual_still_needs_each_members_history():
    """The same new team has figures at once, but no metric can say it changed: the weekly
    change needs 14 earlier days per member, unchanged."""
    frames = [two_days(s, 8000.0 + 100 * i) for i, s in enumerate(SLEEPS)]
    assert team_observed(frames, TODAY)  # figures now
    result = team_statistics(frames, week_of(TODAY))
    assert result.changes and not any(e.sufficient for e in result.changes)
    assert result.changed == []


def test_a_paused_team_shows_no_figures(engine, client):
    client, _ = client
    team_id = new_team(engine, SLEEPS)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        boss = db.scalar(select(User).where(User.email == "boss@example.com"))
        overlap = memberships.create_team(db, boss, "Design squad", None, NOW)
        for i in range(2):  # shares people but differs by fewer than 5: paused
            person = db.scalar(select(User).where(User.email == f"member{i:02d}@example.com"))
            memberships.join(db, overlap, person, NOW)
        assert memberships.overlap_problem(db, team)
    boss_headers = signed_in(client, engine, "boss@example.com")
    assert client.get(f"/teams/{team_id}/observed", headers=boss_headers).json()["figures"] == []
