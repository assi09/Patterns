"""Approving what a harness sent: nothing it sends changes data until its person says yes."""

import uuid
from datetime import date, datetime

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db.daily import save_daily
from app.db.models import HarnessSubmission, Team, TeamNote, User
from app.sync.calendar import HARNESS_SOURCE, METRICS
from app.teams import agent as team_agent


def pending(db: Session, user: User) -> list[HarnessSubmission]:
    """What is waiting for this person: their own sends (calendar days, team events)."""
    return list(
        db.scalars(
            select(HarnessSubmission)
            .where(HarnessSubmission.user_id == user.id, HarnessSubmission.status == "pending")
            .order_by(HarnessSubmission.created_at.desc())
        )
    )


def _own_pending(db: Session, user: User, submission_id: str) -> HarnessSubmission:
    try:
        key = uuid.UUID(submission_id)
    except ValueError:
        raise ApiError(404, "not_found", "Nothing like that is waiting.") from None
    # Locked and re-read, so two taps at once cannot both apply it (PostgreSQL row lock).
    row = db.scalar(
        select(HarnessSubmission)
        .where(HarnessSubmission.id == key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.user_id != user.id:
        raise ApiError(404, "not_found", "Nothing like that is waiting.")
    if row.status != "pending":
        raise ApiError(409, "already_decided", "This was already approved or declined.")
    return row


def approve(db: Session, user: User, submission_id: str, now: datetime) -> HarnessSubmission:
    row = _own_pending(db, user, submission_id)
    if row.kind == "calendar_days":
        days = row.payload["days"]
        index = pd.DatetimeIndex([pd.Timestamp(d["date"]) for d in days], name="date")
        frame = pd.DataFrame(
            [{m: float(d.get(m, 0)) for m in METRICS if m != "out_of_office"} for d in days],
            index=index,
        )
        save_daily(db, user.id, HARNESS_SOURCE, frame)
    elif row.kind == "team_event":
        team = db.get(Team, row.team_id)
        if team is None or team.supervisor_id != user.id or user.role != "supervisor":
            raise ApiError(409, "not_supervisor", "You no longer supervise this team.")
        event = row.payload
        # The same screen as a note written in the app: the team agent's model reads notes.
        if problem := team_agent._unsafe(event["title"], note=True):
            raise ApiError(422, "unsafe_note", f"Not saved: {problem}")
        db.add(
            TeamNote(
                team_id=team.id,
                text=event["title"][:300],
                starts_on=date.fromisoformat(event["starts_on"]),
                ends_on=date.fromisoformat(event["ends_on"]) if event.get("ends_on") else None,
                created_at=now,
            )
        )
    row.status, row.decided_at = "approved", now
    return row


def decline(db: Session, user: User, submission_id: str, now: datetime) -> HarnessSubmission:
    row = _own_pending(db, user, submission_id)
    row.status, row.decided_at = "declined", now
    return row
