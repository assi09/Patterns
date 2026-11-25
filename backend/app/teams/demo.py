"""Made-up team members for trying a team end to end on a local database.

A real report needs at least five members with weeks of Fitbit data; before real people join,
these stand in for them. Every value comes from `app.synthetic` (no one's real data), every
account is an @example.com address that cannot sign in, and their time asleep drops in the last
full week so the report has a change to show. They also get made-up calendar days (counts only,
as a calendar sync stores them), with more meetings that same week, so the team's meeting load
has something to show too. Running it again replaces their data.
"""

import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.team import week_of
from app.auth.passwords import hash_password
from app.db.daily import save_daily
from app.db.models import Team, TeamMembership, User
from app.sync import calendar
from app.synthetic import Step, generate
from app.teams import memberships
from app.teams.reports import SOURCE

DOMAIN = "example.com"
MEETING_RISE = 1.6  # times the usual meetings, in the last full week
HISTORY_DAYS = 120
SLEEP_DROP = -60  # minutes, in the last full week


@dataclass(frozen=True)
class DemoMembers:
    created: int
    joined: int
    sharing: int


def add_demo_members(
    db: Session, team: Team, count: int, sharing: int, today: date, now: datetime
) -> DemoMembers:
    """`count` made-up members in `team` with history up to yesterday; the first `sharing` of
    them share their weekly levels."""
    week = week_of(today - timedelta(days=7))
    start = today - timedelta(days=HISTORY_DAYS)
    created = joined = 0
    for i in range(count):
        email = f"demo-member-{i + 1}@{DOMAIN}"
        person = db.scalar(select(User).where(User.email == email))
        if person is None:
            # A random password nobody is told: these accounts exist only to hold data.
            password = hash_password(secrets.token_urlsafe(32))
            person = User(email=email, password_hash=password, status="approved")
            db.add(person)
            db.flush()
            created += 1
        drop = (Step("sleep_minutes", week.start, SLEEP_DROP),)
        frame = generate(start, HISTORY_DAYS, drop, seed=1000 + i).frame
        # The sync's heart rate zones and still heart rate, made up too, so strain and stress
        # have their inputs; zones split each day's Active Zone Minutes (moderate + 2 x higher).
        rng = np.random.default_rng(2000 + i)
        azm = frame["active_zone_minutes"].clip(lower=0)
        frame["hr_zone_light_minutes"] = rng.normal(180, 40, len(frame)).clip(0).round()
        frame["hr_zone_moderate_minutes"] = (azm * 0.6).round()
        frame["hr_zone_vigorous_minutes"] = (azm * 0.17).round()
        frame["hr_zone_peak_minutes"] = (azm * 0.03).round()
        frame["still_minutes"] = rng.normal(480, 60, len(frame)).round()
        frame["still_hr_above_resting"] = rng.normal(9, 3, len(frame)).round(1)
        save_daily(db, person.id, SOURCE, frame)
        save_daily(db, person.id, calendar.SOURCE, _calendar_days(start, today, week.start, i))
        member = db.scalar(
            select(TeamMembership).where(
                TeamMembership.team_id == team.id,
                TeamMembership.user_id == person.id,
                TeamMembership.left_at.is_(None),
            )
        )
        if member is None:
            # A week before the report, as if they had joined then.
            memberships.join(db, team, person, now - timedelta(days=14))
            joined += 1
        memberships.share_levels(db, person, str(team.id), i < sharing, now)
    return DemoMembers(created, joined, min(sharing, count))


def _calendar_days(start: date, today: date, busy_week: date, seed: int) -> pd.DataFrame:
    """Made-up daily meeting counts up to yesterday: weekdays only, busier in `busy_week`."""
    rng = np.random.default_rng(3000 + seed)
    days = pd.date_range(start, today - timedelta(days=1), freq="D")
    rows = []
    for day in days:
        workday = day.weekday() < 5
        rise = MEETING_RISE if busy_week <= day.date() < busy_week + timedelta(days=7) else 1.0
        meetings = int(rng.poisson(4 * rise)) if workday else 0
        rows.append(
            {
                "meeting_minutes": float(meetings * rng.integers(25, 50)),
                "meetings": float(meetings),
                "after_hours_minutes": float(rng.poisson(15 * (rise - 0.9))) if workday else 0.0,
                "back_to_back": float(max(0, meetings - 2 - rng.integers(0, 2))),
                "focus_minutes": float(max(0, 240 - meetings * 30)) if workday else 0.0,
                "out_of_office": 0.0,
            }
        )
    return pd.DataFrame(rows, index=days)
