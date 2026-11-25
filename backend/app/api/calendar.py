"""The calendar over HTTP: a person's own meeting load, and a team's under the team rules.

Connecting is `POST /google/connect` with `{"capability": "calendar"}`: the same Google sign-in
with the read-only calendar scope added (app/sync/calendar.py). A person sees their own daily
counts; a supervisor sees their own team's figures from at least 5 people, never a member's.
"""

from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.analysis.team import week_of
from app.analysis.team_calendar import team_load
from app.api import schemas
from app.api.auth import Db, Now, approved_user
from app.api.errors import ApiError
from app.api.teams import Supervisor
from app.db.models import DailyMetric, SyncRun, User
from app.sync import calendar
from app.teams import memberships as teams

router = APIRouter(tags=["calendar"])
Person = Annotated[User, Depends(approved_user)]
OWN_DAYS_BACK = 28


@router.get("/calendar/status", response_model=schemas.CalendarStatus)
def calendar_status(db: Db, user: Person) -> schemas.CalendarStatus:
    connection = calendar.connection_for(db, user.id)
    runs = select(SyncRun).where(SyncRun.user_id == user.id, SyncRun.source == calendar.SOURCE)
    latest = db.scalar(runs.order_by(SyncRun.started_at.desc()).limit(1))
    synced = db.scalar(
        select(func.max(SyncRun.finished_at)).where(
            SyncRun.user_id == user.id,
            SyncRun.source == calendar.SOURCE,
            SyncRun.status == "succeeded",
        )
    )
    days = db.scalar(
        select(func.count(func.distinct(DailyMetric.day))).where(
            DailyMetric.user_id == user.id, DailyMetric.source == calendar.SOURCE
        )
    )
    return schemas.CalendarStatus(
        connected=connection is not None and connection.status == "active",
        last_sync=synced,
        last_error=latest.error if latest and latest.status == "failed" else None,
        days=days or 0,
    )


@router.post("/calendar/disconnect", response_model=schemas.CalendarStatus)
def disconnect(db: Db, user: Person) -> schemas.CalendarStatus:
    """Forgets the calendar sign-in only; Google Health is left alone. The days already synced
    stay, as for Google Health."""
    connection = calendar.connection_for(db, user.id)
    if connection is not None:
        db.delete(connection)
        db.flush()
    return calendar_status(db, user)


@router.get("/me/calendar", response_model=list[schemas.CalendarDay])
def my_calendar(db: Db, user: Person, clock: Now) -> list[schemas.CalendarDay]:
    """The person's own daily counts: the last four weeks and what is planned ahead."""
    today = clock.date()
    start = today - timedelta(days=OWN_DAYS_BACK)
    frame = calendar.frame_for(db, user.id, start, today + timedelta(days=calendar.DAYS_AHEAD + 1))
    return [
        schemas.CalendarDay(date=stamp.date(), **{m: float(row[m]) for m in calendar.METRICS})
        for stamp, row in frame.fillna(0).iterrows()
    ]


@router.get("/teams/{team_id}/calendar", response_model=schemas.TeamCalendar)
def team_calendar(
    team_id: str, db: Db, clock: Now, user: Supervisor, week: date | None = None
) -> schemas.TeamCalendar:
    """The team's meeting load for a Monday-to-Sunday week (the last full one by default)."""
    team = teams.supervised_team(db, user, team_id)
    if teams.overlap_problem(db, team):
        raise ApiError(409, "paused", "This team's figures are paused.")
    span = week_of(week) if week else week_of(clock.date() - timedelta(days=7))
    start = span.start - timedelta(days=28)
    end = span.end + timedelta(days=8)
    frames = [
        frame
        for uid in teams.member_ids(db, team)
        if not (frame := calendar.frame_for(db, uid, start, end)).empty
    ]
    load = team_load(frames, span)
    return schemas.TeamCalendar(
        week=schemas.Window(start=span.start, end=span.end),
        connected=len(frames),
        minimum_members=teams.MIN_MEMBERS,
        metrics=[
            schemas.TeamCalendarMetric(
                metric=e.metrics[0],
                label=e.stats["label"],
                unit=e.stats["unit"],
                members=e.n,
                sufficient=e.sufficient,
                median_week=e.stats.get("median_week"),
                q1_week=e.stats.get("q1_week"),
                q3_week=e.stats.get("q3_week"),
                median_change=e.stats.get("median_change"),
                members_up=e.stats.get("members_up"),
                members_down=e.stats.get("members_down"),
                median_planned=e.stats.get("median_planned"),
                evidence_id=e.id,
            )
            for e in load
        ],
        generated_at=datetime.now(clock.tzinfo),
    )
