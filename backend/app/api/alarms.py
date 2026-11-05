"""Smart alarms: what was raised for the person, their verdict on each, and their settings."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import select

from app.alarms.run import link, save_settings, settings_of
from app.api.auth import Db, Now, approved_user
from app.api.errors import ApiError
from app.api.schemas import ApiModel
from app.db.memory import note_interest
from app.db.models import Alarm, User
from app.reminders.store import utc

router = APIRouter(tags=["alarms"])
Person = Annotated[User, Depends(approved_user)]
Kind = Literal["day", "streak", "finding", "data"]
SHOWN = 30


class AlarmOut(ApiModel):
    id: str
    kind: Kind
    metric: str | None
    day: date
    title: str
    body: str
    link: str  # its evidence, or Settings for data alarms
    evidence_ids: list[str]
    status: Literal["pending", "sent", "suppressed", "expired"]
    reason: str | None  # why it was not sent
    feedback: Literal["useful", "not_useful"] | None
    created_at: datetime
    sent_at: datetime | None


class Feedback(ApiModel):
    useful: bool


class AlarmSettings(ApiModel):
    enabled: bool
    muted_kinds: list[Kind] = Field(default_factory=list)
    sensitivity: Literal["fewer", "normal", "more"]


def _out(row: Alarm) -> AlarmOut:
    return AlarmOut(
        id=str(row.id),
        kind=row.kind,
        metric=row.metric if row.kind != "data" else None,
        day=row.day,
        title=row.title,
        body=row.body,
        link=link(row),
        evidence_ids=list(row.evidence_ids or []),
        status=row.status,
        reason=row.reason,
        feedback=row.feedback,
        created_at=utc(row.created_at),
        sent_at=utc(row.sent_at),
    )


@router.get("/alarms", response_model=list[AlarmOut])
def list_alarms(db: Db, user: Person) -> list[AlarmOut]:
    """The latest alarms that reached the person, newest first."""
    rows = db.scalars(
        select(Alarm)
        .where(Alarm.user_id == user.id, Alarm.status == "sent")
        .order_by(Alarm.sent_at.desc(), Alarm.id)
        .limit(SHOWN)
    )
    return [_out(row) for row in rows]


@router.post("/alarms/{alarm_id}/feedback", response_model=AlarmOut)
def give_feedback(alarm_id: uuid.UUID, body: Feedback, db: Db, user: Person) -> AlarmOut:
    row = db.scalar(select(Alarm).where(Alarm.id == alarm_id, Alarm.user_id == user.id))
    if row is None:
        raise ApiError(404, "not_found", "No such alarm.")
    first = row.feedback is None  # changing one's mind is not a second signal
    row.feedback = "useful" if body.useful else "not_useful"
    if first:
        note_interest(db, user.id, [row.metric], row.feedback)
    return _out(row)


@router.get("/alarm-settings", response_model=AlarmSettings)
def get_alarm_settings(db: Db, user: Person) -> AlarmSettings:
    row = settings_of(db, user.id)
    return AlarmSettings(
        enabled=row.enabled, muted_kinds=list(row.muted_kinds or []), sensitivity=row.sensitivity
    )


@router.put("/alarm-settings", response_model=AlarmSettings)
def put_alarm_settings(body: AlarmSettings, db: Db, user: Person, now: Now) -> AlarmSettings:
    row = save_settings(
        db,
        user.id,
        enabled=body.enabled,
        muted_kinds=list(body.muted_kinds),
        sensitivity=body.sensitivity,
        now=now,
    )
    return AlarmSettings(
        enabled=row.enabled, muted_kinds=list(row.muted_kinds), sensitivity=row.sensitivity
    )
