"""Connecting a person's Google Health account from the app, and syncing it.

`POST /google/connect` returns Google's sign-in address; the browser comes back to
`GET /google/callback`, which stores the encrypted token, starts the first sync and sends the
browser back to the app. `POST /google/sync` refreshes the data; `GET /google/status` reports it.

The app calls `POST /google/sync` by itself whenever it is opened, comes back to the front or is
pulled to refresh, so syncing is nothing people think about. The server keeps that cheap: a sync
starts only when none is running and the last one began over `RESYNC_AFTER` ago, unless the person
asked for it with `force` (Settings' "Sync now").
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from app.actions.schemas import WRITE_SCOPES
from app.api import schemas
from app.api.auth import Db, Now, approved_user
from app.api.chat import Sessions, get_sessions
from app.api.errors import ApiError
from app.config import settings
from app.db.models import GoogleConnection, SyncRun, User
from app.sync import calendar, connections
from app.sync.client import HealthClient
from app.sync.connections import OAuth, SignIns, Syncs, TokenBox
from app.sync.google_auth import SCOPES, OAuthClient, SyncError
from app.teams import checkin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/google", tags=["google"])

sign_ins = SignIns()
syncs = Syncs()

# How soon the app's automatic syncs may start another one. Counted from the last attempt, not the
# last success, so a failing sync is not retried on every refresh.
RESYNC_AFTER = timedelta(minutes=10)


@dataclass(frozen=True)
class GoogleParts:
    oauth: OAuth
    box: TokenBox
    health_for: Callable[[Callable[[], str]], HealthClient]


@lru_cache(maxsize=1)
def _google() -> GoogleParts:
    try:
        client = OAuthClient.from_settings(settings.google_client_id, settings.google_client_secret)
        box = TokenBox(settings.token_key)
    except SyncError as exc:
        logger.warning("Connecting Google Health is not available: %s", exc)
        raise ApiError(
            503, "google_unavailable", "Connecting Google Health is not set up yet."
        ) from exc
    oauth = connections.GoogleOAuth(client, f"{settings.public_url.rstrip('/')}/google/callback")
    return GoogleParts(oauth, box, HealthClient)


def get_google() -> GoogleParts:
    """FastAPI dependency; tests override it with a fake Google."""
    return _google()


Google = Annotated[GoogleParts, Depends(get_google)]
Person = Annotated[User, Depends(approved_user)]


def _status(db, user: User) -> schemas.GoogleStatus:
    return schemas.GoogleStatus(**connections.status(db, user.id), syncing=syncs.running(user.id))


def _start_sync(google: GoogleParts, sessions: Sessions, user: User, today: date) -> None:
    syncs.start(user.id, lambda: sync_everything(google, sessions, user.id, today))


def sync_everything(google: GoogleParts, sessions: Sessions, user_id, today: date) -> None:
    """Everything that follows a person's sync, in order, each step guarded so one failing never
    stops the next: Google Health; then, if that sync succeeded, the check-in rule for every team
    they agreed to it for (app/teams/checkin.py); then their calendar, if they allowed it
    (app/sync/calendar.py)."""
    started = connections.now_utc()
    try:
        connections.sync(sessions, google.box, user_id, google.health_for, today)
    except Exception:
        logger.exception("The Google Health sync failed")
    try:
        with sessions() as db:
            if connections.succeeded_since(db, user_id, started):
                checkin.after_sync(db, user_id, connections.now_utc())
    except Exception:
        logger.exception("Checking the check-in rule after a sync failed")
    try:
        calendar.sync_person(sessions, google.box, user_id, today, settings.timezone)
    except Exception:
        logger.exception("The calendar sync failed")


@router.get("/status", response_model=schemas.GoogleStatus)
def google_status(db: Db, user: Person) -> schemas.GoogleStatus:
    return _status(db, user)


class ConnectOptions(schemas.ApiModel):
    capability: Literal["food_logging", "workout_logging", "calendar"]


@router.post("/connect", response_model=schemas.ConnectStart)
def connect(
    user: Person, google: Google, clock: Now, db: Db, body: ConnectOptions | None = None
) -> schemas.ConnectStart:
    scopes = set(SCOPES)
    connection = db.get(GoogleConnection, user.id)
    if body is not None and body.capability == "calendar":
        # The calendar gets a sign-in of its own, with that permission only: Google's Health
        # API refuses a token that also carries it (app/sync/calendar.py).
        return schemas.ConnectStart(
            url=sign_ins.start(google.oauth, user.id, clock, (calendar.SCOPE,))
        )
    if connection is not None:  # a reconnect keeps the write permissions allowed before
        scopes.update(set(connection.scopes) & set(WRITE_SCOPES.values()))
    if body is not None:
        scopes.add(WRITE_SCOPES["food" if body.capability == "food_logging" else "workout"])
    return schemas.ConnectStart(
        url=sign_ins.start(google.oauth, user.id, clock, tuple(sorted(scopes)))
    )


@router.get("/callback", include_in_schema=False)
def callback(
    db: Db,
    google: Google,
    clock: Now,
    sessions: Annotated[Sessions, Depends(get_sessions)],
    state: str = "",
    code: str = "",
    error: str = "",
) -> RedirectResponse:
    """Where Google sends the browser back. The `state` ties it to the person who started it."""

    def back(result: str) -> RedirectResponse:
        query = urlencode({"google": result})
        return RedirectResponse(f"{settings.app_url.rstrip('/')}/settings?{query}", status_code=303)

    pending = sign_ins.finish(state, clock)
    if pending is None:
        return back("expired")
    if error or not code:
        return back("cancelled")  # the person said no on Google's page
    try:
        oauth = google.oauth
        if isinstance(oauth, connections.GoogleOAuth):
            oauth = replace(oauth, scopes=pending.scopes)
        credentials = oauth.exchange(code, pending.verifier)
        if tuple(pending.scopes or ()) == (calendar.SCOPE,):
            calendar.save_connection(db, google.box, pending.user_id, credentials)
        else:
            connections.save_connection(db, google.box, pending.user_id, credentials)
    except Exception:
        logger.exception("Connecting Google Health failed")
        return back("failed")
    db.commit()  # stored before the sync thread reads it
    user = db.get(User, pending.user_id)
    _start_sync(google, sessions, user, clock.date())
    return back("connected")


@router.post("/sync", response_model=schemas.GoogleStatus, status_code=202)
def sync_now(
    db: Db,
    user: Person,
    google: Google,
    clock: Now,
    sessions: Annotated[Sessions, Depends(get_sessions)],
    force: Annotated[bool, Body(embed=True)] = False,
) -> schemas.GoogleStatus:
    connection = db.get(GoogleConnection, user.id)
    if connection is None or connection.status != "active":
        raise ApiError(409, "not_connected", "Connect Google Health first.")
    if force or not _recent(db, user, clock):
        _start_sync(google, sessions, user, clock.date())
    return _status(db, user)


def _recent(db, user: User, now: datetime) -> bool:
    """Whether a sync started for this person within `RESYNC_AFTER`."""
    started = db.scalar(
        select(func.max(SyncRun.started_at)).where(
            SyncRun.user_id == user.id, SyncRun.source == connections.SOURCE
        )
    )
    if started is None:
        return False
    if started.tzinfo is None:  # SQLite returns naive times; they are stored in UTC
        started = started.replace(tzinfo=UTC)
    return now - started < RESYNC_AFTER


@router.post("/disconnect", response_model=schemas.GoogleStatus)
def disconnect(db: Db, user: Person) -> schemas.GoogleStatus:
    """Forgets the sign-in. The days already synced stay, so the history is kept."""
    connection = db.get(GoogleConnection, user.id)
    if connection is not None:
        db.delete(connection)
        db.flush()
    return _status(db, user)
