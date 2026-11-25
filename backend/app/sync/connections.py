"""Each person's Google Health connection: the web sign-in, the encrypted token, and syncing.

The browser signs in to Google and comes back to `/google/callback` on this server. Locally that is
a loopback address, which the "Desktop app" OAuth client accepts; a deployed server needs a public
HTTPS address (and a "Web application" client listing it). Tokens are stored encrypted with
`FA_TOKEN_KEY`; a database copy alone signs no one in to Google.

The first sync reads the whole history, newest days first, in chunks, so recent days show early;
later syncs reread the last few days (Google rescores sleep) through today.
"""

import base64
import hashlib
import json
import logging
import secrets
import threading
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode

from cryptography.fernet import Fernet, InvalidToken
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DailyMetric, GoogleConnection, SyncRun, User
from app.sync.client import HealthClient
from app.sync.google_auth import (
    AUTH_URI,
    SCOPES,
    NotConfigured,
    OAuthClient,
    ReconnectNeeded,
    SyncError,
    missing_scopes,
    relax_scope_check,
)
from app.sync.pull import SOURCE, pull

logger = logging.getLogger(__name__)

Sessions = Callable[[], AbstractContextManager[Session]]

STATE_TTL = timedelta(minutes=10)
CHUNK_DAYS = 120  # days per stored sync run on the first sync
RESYNC_DAYS = 3  # recent days reread on every sync
MAX_HISTORY_YEARS = 5


# Tokens


class TokenBox:
    """Encrypts and decrypts stored tokens."""

    def __init__(self, key: SecretStr | None):
        value = key.get_secret_value().strip() if key else ""
        if not value:
            raise NotConfigured(
                "Token encryption is not configured: set FA_TOKEN_KEY in .env to a key made by "
                "cryptography's Fernet.generate_key() (see .env.example)."
            )
        self._fernet = Fernet(value.encode())

    def seal(self, credentials: Credentials) -> bytes:
        return self._fernet.encrypt(credentials.to_json().encode())

    def open(self, sealed: bytes) -> Credentials:
        try:
            info = json.loads(self._fernet.decrypt(sealed))
            return Credentials.from_authorized_user_info(info)
        except (InvalidToken, ValueError, KeyError) as exc:
            raise ReconnectNeeded(
                "The stored Google sign-in cannot be read; connect again."
            ) from exc


# The sign-in


class OAuth(Protocol):
    def authorization_url(self, state: str, challenge: str) -> str: ...
    def exchange(self, code: str, verifier: str) -> Credentials: ...


@dataclass
class GoogleOAuth:
    """Google's authorization-code flow with PKCE, returning to `redirect_uri`."""

    client: OAuthClient
    redirect_uri: str
    scopes: tuple[str, ...] = SCOPES

    def authorization_url(self, state: str, challenge: str) -> str:
        params = {
            "client_id": self.client.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "prompt": "consent",  # always return a refresh token, even when connecting again
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTH_URI}?{urlencode(params)}"

    def exchange(self, code: str, verifier: str) -> Credentials:
        flow = Flow.from_client_config(
            self.client.config(), scopes=list(self.scopes), redirect_uri=self.redirect_uri
        )
        relax_scope_check()
        flow.fetch_token(code=code, code_verifier=verifier)
        return flow.credentials


@dataclass
class _Pending:
    user_id: uuid.UUID
    verifier: str
    expires: datetime
    scopes: tuple[str, ...] = SCOPES


class SignIns:
    """Sign-ins in progress, by their `state`. In memory: one server process, ten minutes each."""

    def __init__(self) -> None:
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.Lock()

    def start(
        self, oauth: OAuth, user_id: uuid.UUID, now: datetime, scopes: tuple[str, ...] = SCOPES
    ) -> str:
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        with self._lock:
            self._pending = {k: p for k, p in self._pending.items() if p.expires > now}
            self._pending[state] = _Pending(user_id, verifier, now + STATE_TTL, scopes)
        if isinstance(oauth, GoogleOAuth):
            oauth = replace(oauth, scopes=scopes)
        return oauth.authorization_url(state, challenge)

    def finish(self, state: str, now: datetime) -> _Pending | None:
        """The sign-in this state started, once only; None if unknown or expired."""
        with self._lock:
            pending = self._pending.pop(state, None)
        return pending if pending and pending.expires > now else None


def save_connection(
    session: Session, box: TokenBox, user_id: uuid.UUID, credentials: Credentials
) -> GoogleConnection:
    if not credentials.refresh_token:
        raise ReconnectNeeded("Google did not return a lasting sign-in; connect again.")
    connection = session.get(GoogleConnection, user_id) or GoogleConnection(user_id=user_id)
    connection.encrypted_token = box.seal(credentials)
    connection.scopes = sorted(credentials.granted_scopes or credentials.scopes or [])
    connection.status = "active"
    session.add(connection)
    session.flush()
    return connection


def credentials_for(session: Session, box: TokenBox, user_id: uuid.UUID) -> Credentials:
    """Valid credentials, refreshed and stored again if needed; marks a dead sign-in."""
    connection = session.get(GoogleConnection, user_id)
    if connection is None or connection.status != "active":
        raise ReconnectNeeded("Connect Google Health first.")
    credentials = box.open(connection.encrypted_token)
    if credentials.valid:
        return credentials
    try:
        credentials.refresh(Request())
    except RefreshError as exc:
        connection.status = "reconnect_needed"
        session.commit()  # kept although the caller's session rolls back on the error
        raise ReconnectNeeded(
            "Your Google sign-in expired (in testing it lasts 7 days); connect again."
        ) from exc
    connection.encrypted_token = box.seal(credentials)
    return credentials


# Syncing


def first_day(health: HealthClient, today: date) -> date:
    """The earliest day with steps, found by stepping back in 90-day windows until one is empty."""
    earliest = today
    end = today + timedelta(days=1)
    for _ in range(MAX_HISTORY_YEARS * 4):
        start = end - timedelta(days=90)
        if not health.daily_rollup("steps", start, end):
            break
        earliest, end = start, start
    return earliest


def plan(last_stored: date | None, first: Callable[[], date], today: date) -> list[tuple]:
    """The [start, end) ranges to pull, newest first."""
    end = today + timedelta(days=1)
    if last_stored is not None:
        return [(min(last_stored - timedelta(days=RESYNC_DAYS), today), end)]
    start = first()
    ranges = []
    while end > start:
        chunk_start = max(start, end - timedelta(days=CHUNK_DAYS))
        ranges.append((chunk_start, end))
        end = chunk_start
    return ranges


class Syncs:
    """Who is syncing right now: one sync per person at a time, on its own thread."""

    def __init__(self) -> None:
        self._running: set[uuid.UUID] = set()
        self._lock = threading.Lock()

    def running(self, user_id: uuid.UUID) -> bool:
        with self._lock:
            return user_id in self._running

    def start(self, user_id: uuid.UUID, work: Callable[[], None]) -> bool:
        """Runs `work` in the background unless this person is already syncing."""
        with self._lock:
            if user_id in self._running:
                return False
            self._running.add(user_id)

        def run() -> None:
            try:
                work()
            except Exception:
                logger.exception("Sync failed")
            finally:
                with self._lock:
                    self._running.discard(user_id)

        threading.Thread(target=run, name="sync", daemon=True).start()
        return True


def sync(
    sessions: Sessions,
    box: TokenBox,
    user_id: uuid.UUID,
    health_for: Callable[[Callable[[], str]], HealthClient],
    today: date,
) -> None:
    """Pulls the person's missing days. Failures are recorded on the sync run, not raised."""
    with sessions() as session:
        user = session.get(User, user_id)
        email = user.email
        last = session.scalar(
            select(func.max(DailyMetric.day)).where(
                DailyMetric.user_id == user_id, DailyMetric.source == SOURCE
            )
        )

    def token() -> str:
        with sessions() as session:
            return credentials_for(session, box, user_id).token

    try:
        health = health_for(token)
        for start, end in plan(last, lambda: first_day(health, today), today):
            pull(sessions, health, email, start, end)
    except SyncError as exc:
        logger.warning("Sync stopped: %s", exc)


def status(session: Session, user_id: uuid.UUID) -> dict:
    connection = session.get(GoogleConnection, user_id)
    runs = select(SyncRun).where(SyncRun.user_id == user_id, SyncRun.source == SOURCE)
    latest = session.scalar(runs.order_by(SyncRun.started_at.desc()).limit(1))
    succeeded = session.scalar(
        select(func.max(SyncRun.finished_at)).where(
            SyncRun.user_id == user_id, SyncRun.source == SOURCE, SyncRun.status == "succeeded"
        )
    )
    return {
        "status": connection.status if connection else "none",
        "missing_scopes": missing_scopes(connection.scopes) if connection else [],
        "last_sync": succeeded,
        "last_error": latest.error if latest and latest.status == "failed" else None,
    }


def succeeded_since(session: Session, user_id: uuid.UUID, since: datetime) -> bool:
    """Whether a Google Health sync of this person finished successfully at or after `since`."""
    finished = session.scalar(
        select(func.max(SyncRun.finished_at)).where(
            SyncRun.user_id == user_id, SyncRun.source == SOURCE, SyncRun.status == "succeeded"
        )
    )
    if finished is None:
        return False
    if finished.tzinfo is None:  # SQLite keeps naive UTC
        finished = finished.replace(tzinfo=UTC)
    return finished >= since


def now_utc() -> datetime:
    return datetime.now(UTC)
