"""The app's inbox: reminders that came due (and later the smart alarms), newest first."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select, update

from app.api.auth import Db, Now, approved_user
from app.api.errors import ApiError
from app.api.schemas import ApiModel
from app.db.models import Alarm, Notification, User
from app.reminders.store import utc

router = APIRouter(prefix="/notifications", tags=["notifications"])
Person = Annotated[User, Depends(approved_user)]
SHOWN = 50


class NotificationOut(ApiModel):
    id: str
    kind: str
    title: str
    body: str
    link: str | None  # a path in the app
    alarm_id: str | None  # a smart alarm, which the person may mark useful or not
    alarm_feedback: str | None  # "useful", "not_useful", or not given yet
    fact_id: str | None  # a memory the person may keep
    created_at: datetime
    read_at: datetime | None


class Inbox(ApiModel):
    items: list[NotificationOut]
    unread: int  # over all of them, not just those shown


def _out(row: Notification, feedback: str | None = None) -> NotificationOut:
    return NotificationOut(
        id=str(row.id),
        kind=row.kind,
        title=row.title,
        body=row.body,
        link=row.link,
        alarm_id=str(row.alarm_id) if row.alarm_id else None,
        alarm_feedback=feedback,
        fact_id=str(row.fact_id) if row.fact_id else None,
        created_at=utc(row.created_at),
        read_at=utc(row.read_at),
    )


@router.get("", response_model=Inbox)
def inbox(db: Db, user: Person) -> Inbox:
    rows = db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id)
        .limit(SHOWN)
    )
    unread = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    rows = list(rows)
    alarm_ids = [row.alarm_id for row in rows if row.alarm_id]
    feedback = dict(
        db.execute(select(Alarm.id, Alarm.feedback).where(Alarm.id.in_(alarm_ids))).all()
        if alarm_ids
        else []
    )
    return Inbox(items=[_out(row, feedback.get(row.alarm_id)) for row in rows], unread=unread)


@router.post("/{notification_id}/read", response_model=NotificationOut)
def read(notification_id: uuid.UUID, db: Db, user: Person, now: Now) -> NotificationOut:
    row = db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if row is None:
        raise ApiError(404, "not_found", "No such notification.")
    row.read_at = row.read_at or now
    return _out(row)


@router.post("/read-all", status_code=204)
def read_all(db: Db, user: Person, now: Now) -> Response:
    db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=now)
    )
    return Response(status_code=204)
