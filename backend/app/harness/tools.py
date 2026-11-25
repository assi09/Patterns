"""What a harness may read and send through MCP, as plain functions of (db, caller).

Every function checks the caller's current role, as the app does, and returns only what the app
would show that person: a supervisor's own teams in aggregates from at least 5 people, a member's
own days. Check-in alerts are never read or written here (docs/mcp.md, docs/escalation.md).
What a harness sends is untrusted: checked against the schemas below and held as pending until
the person approves it in the app.
"""

from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.team import team_observed, week_of
from app.analysis.team_calendar import team_load
from app.db.daily import load_daily
from app.db.models import HarnessSubmission, Team, TeamAlert, TeamReport, User
from app.sync import calendar
from app.teams import memberships as teams
from app.teams import observed as observed_text
from app.teams import reports

PAST_DAYS = 60  # how far back a harness may send calendar days
AHEAD_DAYS = 14  # and how far ahead
OWN_METRICS = ("sleep_minutes", "steps", "resting_hr", "hrv_ms")


class HarnessError(ValueError):
    """Refused; the message says why and is safe to show the harness."""


# --- what a harness may send ----------------------------------------------------------------


class CalendarDayIn(BaseModel):
    """One day of a member's own meeting load, as counted by the harness from its calendar."""

    model_config = ConfigDict(extra="forbid")

    date: date
    meeting_minutes: float = Field(ge=0, le=24 * 60)
    meetings: int = Field(ge=0, le=60)
    after_hours_minutes: float = Field(ge=0, le=24 * 60)
    back_to_back: int = Field(ge=0, le=60)
    focus_minutes: float = Field(default=0, ge=0, le=24 * 60)


class TeamEventIn(BaseModel):
    """A team event the harness knows of (a launch, a deadline), for the supervisor's notes."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    starts_on: date
    ends_on: date | None = None

    @field_validator("title")
    @classmethod
    def _plain(cls, value: str) -> str:
        cleaned = " ".join(value.split())  # one line, kept as data
        if not cleaned:
            raise ValueError("A title is needed.")
        return cleaned


def _in_range(day: date, today: date) -> None:
    if not today - timedelta(days=PAST_DAYS) <= day <= today + timedelta(days=AHEAD_DAYS):
        raise HarnessError(
            f"Dates must be within the last {PAST_DAYS} days or the next {AHEAD_DAYS}: {day}."
        )


# --- who is calling -------------------------------------------------------------------------


def _supervised(db: Session, user: User, team_id: str) -> Team:
    if user.role != "supervisor":
        raise HarnessError("Only a supervisor can read or send team information.")
    try:
        team = teams.supervised_team(db, user, team_id)
    except Exception:
        raise HarnessError("No such team.") from None  # another's team looks like none
    if teams.overlap_problem(db, team):
        raise HarnessError("This team's figures are paused.")
    return team


def who_am_i(db: Session, user: User) -> dict:
    if user.role == "supervisor":
        own = db.scalars(select(Team).where(Team.supervisor_id == user.id)).all()
        return {
            "role": "supervisor",
            "teams": [
                {"team_id": str(t.id), "name": t.name, "members": teams.active_members(db, t)}
                for t in own
            ],
            "can": "read your teams' figures (from at least 5 people) and send team events",
        }
    if user.role == "member":
        joined = [team.name for _, team, _ in teams.memberships(db, user)]
        return {
            "role": "member",
            "teams": joined,
            "can": "read your own recent days and calendar counts, and send your calendar days",
        }
    return {"role": user.role, "can": "nothing through MCP"}


# --- reading --------------------------------------------------------------------------------


def team_overview(db: Session, user: User, team_id: str, today: date) -> dict:
    """The team as on its Team tab: observed readings, the latest weekly report's team figures,
    open team alerts. Aggregates only, from at least 5 people."""
    team = _supervised(db, user, team_id)
    frames = reports.member_frames(db, team, today - timedelta(days=4), today)
    observed = [observed_text.sentence(e, today) for e in team_observed(frames, today)]
    report = db.scalar(
        select(TeamReport)
        .where(TeamReport.team_id == team.id)
        .order_by(TeamReport.week_start.desc())
        .limit(1)
    )
    alerts = db.scalars(
        select(TeamAlert).where(TeamAlert.team_id == team.id, TeamAlert.resolved_at.is_(None))
    ).all()
    return {
        "team": team.name,
        "readings": observed,
        "weekly_report": None
        if report is None
        else {
            "week_start": report.week_start.isoformat(),
            "status": report.status,
            "headline": report.headline,
            "figures": [s.get("text", "") for s in (report.body or {}).get("sections", [])],
        },
        "open_alerts": [a.text for a in alerts],
        "minimum_members": teams.MIN_MEMBERS,
    }


def team_meeting_load(db: Session, user: User, team_id: str, today: date) -> dict:
    """The team's meeting load for the last full week, from at least 5 people."""
    team = _supervised(db, user, team_id)
    week = week_of(today - timedelta(days=7))
    frames = [
        frame
        for uid in teams.member_ids(db, team)
        if not (
            frame := calendar.frame_for(
                db, uid, week.start - timedelta(days=28), week.end + timedelta(days=8)
            )
        ).empty
    ]
    return {
        "week": f"{week.start.isoformat()} to {week.end.isoformat()}",
        "members_with_a_calendar": len(frames),
        "figures": [
            {"metric": e.metrics[0], "members": e.n, **e.stats}
            for e in team_load(frames, week)
            if e.sufficient
        ],
        "minimum_members": teams.MIN_MEMBERS,
    }


def my_recent_days(db: Session, user: User, today: date, days: int = 7) -> list[dict]:
    """The caller's own last days: sleep, steps, resting heart rate and HRV."""
    days = max(1, min(days, 28))
    frame = load_daily(
        db, user.id, "google_health", today - timedelta(days=days - 1), today + timedelta(days=1)
    )
    out = []
    for stamp, row in frame.iterrows():
        out.append(
            {"date": stamp.date().isoformat()}
            | {
                m: (None if m not in row or row[m] != row[m] else round(float(row[m]), 1))
                for m in OWN_METRICS
            }
        )
    return out


def my_calendar_days(db: Session, user: User, today: date, days: int = 14) -> list[dict]:
    days = max(1, min(days, 60))
    frame = calendar.frame_for(
        db, user.id, today - timedelta(days=days - 1), today + timedelta(days=1)
    )
    return [
        {"date": stamp.date().isoformat()} | {k: float(v) for k, v in row.dropna().items()}
        for stamp, row in frame.iterrows()
    ]


# --- sending, held as pending ---------------------------------------------------------------


def _hold(
    db: Session, user: User, kind: str, payload: dict, team: Team | None, token_id, now: datetime
) -> dict:
    row = HarnessSubmission(
        user_id=user.id,
        team_id=team.id if team else None,
        token_id=token_id,
        kind=kind,
        payload=payload,
        status="pending",
        created_at=now,
    )
    db.add(row)
    db.flush()
    return {
        "submission_id": str(row.id),
        "status": "pending",
        "note": "Held until approved in the Patterns app; nothing changes before that.",
    }


def send_calendar_days(
    db: Session, user: User, days: list[CalendarDayIn], token_id, now: datetime
) -> dict:
    """A member's own calendar days, counted by the harness; held for them to approve."""
    if user.role != "member":
        raise HarnessError("Only a member sends their own calendar days.")
    if not days or len(days) > PAST_DAYS + AHEAD_DAYS + 1:
        raise HarnessError(f"Send between 1 and {PAST_DAYS + AHEAD_DAYS + 1} days.")
    seen = set()
    for day in days:
        _in_range(day.date, now.date())
        if day.date in seen:
            raise HarnessError(f"{day.date} appears twice.")
        seen.add(day.date)
    payload = {"days": [d.model_dump(mode="json") for d in days]}
    return _hold(db, user, "calendar_days", payload, None, token_id, now)


def send_team_event(
    db: Session, user: User, team_id: str, event: TeamEventIn, token_id, now: datetime
) -> dict:
    """A team event for the supervisor's notes; held for them to approve."""
    team = _supervised(db, user, team_id)
    _in_range(event.starts_on, now.date())
    if event.ends_on is not None:
        _in_range(event.ends_on, now.date())
        if event.ends_on < event.starts_on:
            raise HarnessError("The event ends before it starts.")
    return _hold(db, user, "team_event", event.model_dump(mode="json"), team, token_id, now)
