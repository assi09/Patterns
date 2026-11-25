"""Review and confirmation endpoints. The model can propose; only this path can execute."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from google.auth.exceptions import GoogleAuthError
from pydantic import Field
from sqlalchemy.orm import Session

from app.actions import store
from app.actions.measure import measure, with_measurement
from app.actions.provider import GoogleWriter, Writer
from app.actions.schemas import WRITE_SCOPES, Log, LogModel, Measured
from app.api.auth import Db, Now, approved_user
from app.api.errors import ApiError
from app.api.features import personal_features
from app.api.google import get_google
from app.api.schemas import ApiModel
from app.config import settings
from app.db.models import GoogleConnection, HealthAction, User
from app.sync.client import HealthClient
from app.sync.connections import credentials_for
from app.sync.google_auth import SyncError

router = APIRouter(prefix="/actions", tags=["actions"], dependencies=[Depends(personal_features)])
Person = Annotated[User, Depends(approved_user)]


class NewDraft(LogModel):
    request_key: uuid.UUID
    log: Log


class Version(LogModel):
    version: int = Field(ge=1, strict=True)


class RevisedDraft(Version):
    log: Log


class Action(ApiModel):
    id: str
    version: int
    status: Literal[
        "draft", "executing", "succeeded", "failed", "unknown", "cancelled", "undoing", "undone"
    ]
    log: Log
    error: str | None
    pending_operation: Literal["create", "delete"] | None
    created_at: str
    updated_at: str


def response(row: HealthAction) -> Action:
    def timestamp(value: datetime) -> str:
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()

    return Action(
        id=str(row.id),
        version=row.version,
        status=row.status,
        log=row.payload,
        error=row.error,
        pending_operation=row.pending_operation,
        created_at=timestamp(row.created_at),
        updated_at=timestamp(row.updated_at),
    )


def measure_workout(
    db: Session, user_id: uuid.UUID, start: datetime, end: datetime, exercise_type: str
) -> Measured:
    """The tracker's data for a workout's interval; "unavailable" without a working sign-in."""
    try:
        token = credentials_for(db, get_google().box, user_id).token
    except (ApiError, SyncError, GoogleAuthError):
        return Measured(status="unavailable")
    return measure(HealthClient(lambda: token, max_retries=1), start, end, exercise_type)


def get_writer(db: Session, user_id: uuid.UUID, kind: str) -> Writer:
    if not settings.google_writes_enabled:
        raise ApiError(
            503,
            "writes_disabled",
            "Google Health logging is not available yet. Your draft is kept.",
        )
    connection = db.get(GoogleConnection, user_id)
    if connection is None or connection.status != "active":
        raise ApiError(409, "not_connected", "Connect Google Health before confirming a log.")
    if WRITE_SCOPES[kind] not in connection.scopes:
        raise ApiError(
            403, "write_scope_needed", "Google has not granted permission for this log type."
        )
    try:
        credentials = credentials_for(db, get_google().box, user_id)
    except (SyncError, GoogleAuthError):
        raise ApiError(
            409, "reconnect_needed", "Reconnect Google Health before confirming a log."
        ) from None
    return GoogleWriter(credentials.token)


@router.get("", response_model=list[Action])
def list_actions(db: Db, user: Person) -> list[Action]:
    return [response(row) for row in store.history(db, user.id)]


@router.get("/{action_id}", response_model=Action)
def get_action(action_id: uuid.UUID, db: Db, user: Person) -> Action:
    return response(store.get(db, user.id, action_id))


@router.post("", response_model=Action, status_code=201)
def propose(body: NewDraft, db: Db, user: Person, clock: Now) -> Action:
    return response(
        store.propose(
            db,
            user.id,
            body.request_key,
            with_measurement(
                body.log.model_dump(mode="json", by_alias=True),
                lambda start, end, kind: measure_workout(db, user.id, start, end, kind),
            ),
            clock,
        )
    )


@router.post("/{action_id}/revise", response_model=Action)
def revise(action_id: uuid.UUID, body: RevisedDraft, db: Db, user: Person, clock: Now) -> Action:
    return response(
        store.revise(
            db,
            user.id,
            action_id,
            body.version,
            # Saving a workout again reads the tracker again: a new time, or data synced since.
            with_measurement(
                body.log.model_dump(mode="json", by_alias=True),
                lambda start, end, kind: measure_workout(db, user.id, start, end, kind),
            ),
            clock,
        )
    )


@router.post("/{action_id}/cancel", response_model=Action)
def cancel(action_id: uuid.UUID, body: Version, db: Db, user: Person, clock: Now) -> Action:
    return response(store.cancel(db, user.id, action_id, body.version, clock))


@router.post("/{action_id}/confirm", response_model=Action)
def confirm(action_id: uuid.UUID, body: Version, db: Db, user: Person, clock: Now) -> Action:
    row = store.get(db, user.id, action_id)
    if row.version == body.version and row.status == "succeeded":
        return response(row)
    # Resolve ownership and eligibility before credentials or any provider traffic.
    if row.version != body.version or row.status != "draft":
        raise ApiError(409, "stale_action", "Review the current draft before confirming it.")
    writer = get_writer(db, user.id, row.kind)
    return response(store.execute(db, user.id, action_id, body.version, writer, clock))


@router.post("/{action_id}/undo", response_model=Action)
def undo(action_id: uuid.UUID, body: Version, db: Db, user: Person, clock: Now) -> Action:
    row = store.get(db, user.id, action_id)
    if row.version == body.version and row.status == "undone":
        return response(row)
    if row.version != body.version or row.status != "succeeded":
        raise ApiError(409, "stale_action", "Only a confirmed Google record can be undone.")
    writer = get_writer(db, user.id, row.kind)
    return response(store.execute(db, user.id, action_id, body.version, writer, clock, undo=True))
