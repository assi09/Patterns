"""The person's reminders, their notification settings and their time zone.

`POST /reminders` is the person creating one, active at once. The agent never calls these routes:
it prepares a `proposed` reminder through its tool, and the person approves it here with `PATCH`.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import Field

from app.api.auth import Db, Now, approved_user
from app.api.features import personal_features
from app.api.schemas import ApiModel
from app.db.models import Reminder, User
from app.reminders import store
from app.reminders.schedule import Schedule, describe

router = APIRouter(tags=["reminders"])
Person = Annotated[User, Depends(approved_user)]
Channel = Literal["email", "in_app"]
HHMM = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class ReminderOut(ApiModel):
    id: str
    title: str
    message: str
    schedule: Schedule
    schedule_text: str  # "Weeknights at 22:30"
    timezone: str
    channels: list[Channel]
    status: Literal["proposed", "active", "paused", "declined", "done"]
    source: Literal["person", "agent"]
    reason: str | None  # why the agent suggested it
    evidence_id: str | None
    next_due_at: datetime | None
    version: int
    created_at: datetime


class NewReminder(ApiModel):
    title: str = Field(min_length=1, max_length=80)
    message: str = Field(default="", max_length=280)
    schedule: Schedule
    channels: list[Channel] = Field(default_factory=lambda: ["in_app", "email"], min_length=1)


class ReminderChange(ApiModel):
    version: int = Field(ge=1)
    status: Literal["active", "paused", "declined"] | None = None
    title: str | None = Field(default=None, min_length=1, max_length=80)
    message: str | None = Field(default=None, max_length=280)
    schedule: Schedule | None = None
    channels: list[Channel] | None = Field(default=None, min_length=1)


class QuietHours(ApiModel):
    start: str = HHMM
    end: str = HHMM


class NotificationSettings(ApiModel):
    quiet_hours: QuietHours | None  # for suggestions and alarms; your own reminders still come
    max_per_day: int = Field(ge=1, le=10)
    email: bool


class TimeZone(ApiModel):
    timezone: str = Field(min_length=1, max_length=64)


def response(row: Reminder) -> ReminderOut:
    schedule = store.schedule_of(row)
    return ReminderOut(
        id=str(row.id),
        title=row.title,
        message=row.message,
        schedule=schedule,
        schedule_text=describe(schedule),
        timezone=row.timezone,
        channels=row.channels,
        status=row.status,
        source=row.source,
        reason=row.reason,
        evidence_id=row.evidence_id,
        next_due_at=store.utc(row.next_due_at),
        version=row.version,
        created_at=store.utc(row.created_at),
    )


@router.get(
    "/reminders", response_model=list[ReminderOut], dependencies=[Depends(personal_features)]
)
def list_reminders(db: Db, user: Person) -> list[ReminderOut]:
    return [response(row) for row in store.listing(db, user.id)]


@router.post(
    "/reminders",
    response_model=ReminderOut,
    status_code=201,
    dependencies=[Depends(personal_features)],
)
def create_reminder(body: NewReminder, db: Db, user: Person, now: Now) -> ReminderOut:
    row = store.create(
        db,
        user,
        title=body.title,
        message=body.message,
        schedule=body.schedule,
        channels=list(body.channels),
        now=now,
    )
    return response(row)


@router.patch(
    "/reminders/{reminder_id}",
    response_model=ReminderOut,
    dependencies=[Depends(personal_features)],
)
def change_reminder(
    reminder_id: uuid.UUID, body: ReminderChange, db: Db, user: Person, now: Now
) -> ReminderOut:
    row = store.get(db, user.id, reminder_id)
    store.change(
        db,
        row,
        version=body.version,
        now=now,
        status=body.status,
        title=body.title,
        message=body.message,
        schedule=body.schedule,
        channels=list(body.channels) if body.channels is not None else None,
    )
    return response(row)


@router.delete(
    "/reminders/{reminder_id}", status_code=204, dependencies=[Depends(personal_features)]
)
def delete_reminder(reminder_id: uuid.UUID, db: Db, user: Person, now: Now) -> Response:
    store.cancel(db, store.get(db, user.id, reminder_id), now)
    return Response(status_code=204)


def _settings_response(row) -> NotificationSettings:
    quiet = QuietHours(start=row.quiet_start, end=row.quiet_end) if row.quiet_start else None
    return NotificationSettings(quiet_hours=quiet, max_per_day=row.max_per_day, email=row.email)


@router.get("/notification-settings", response_model=NotificationSettings)
def get_notification_settings(db: Db, user: Person) -> NotificationSettings:
    return _settings_response(store.notification_settings(db, user.id))


@router.put("/notification-settings", response_model=NotificationSettings)
def put_notification_settings(
    body: NotificationSettings, db: Db, user: Person, now: Now
) -> NotificationSettings:
    quiet = (body.quiet_hours.start, body.quiet_hours.end) if body.quiet_hours else None
    row = store.save_notification_settings(
        db, user.id, quiet=quiet, max_per_day=body.max_per_day, email=body.email, now=now
    )
    return _settings_response(row)


@router.put("/me/timezone", status_code=204)
def put_timezone(body: TimeZone, db: Db, user: Person, now: Now) -> Response:
    store.set_timezone(db, user, body.timezone, now)
    return Response(status_code=204)
