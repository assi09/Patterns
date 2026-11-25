"""OAuth sign-in for MCP assistants (docs/mcp.md), for those that cannot take a pasted token:
claude.ai and Claude Desktop connectors, and Codex's `codex mcp login`.

The assistant registers itself (RFC 7591), sends the person to /authorize, and we send them on to
the app's /connect page. There they sign in if needed and press Allow or Deny; only Allow makes a
one-time code, which the assistant trades (with PKCE) for an access token and a refresh token.
The grant is an `AccessToken` row like a pasted token, so it shows in Settings with its activity,
can be revoked there, and reaches exactly what a pasted token would. Every secret is stored as a
SHA-256 hash; access tokens last an hour, refresh tokens 30 days, and both rotate on each refresh.
The SDK's handlers check redirect URIs, PKCE and client authentication; this module stores state.
"""

import secrets
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db.models import AccessToken as TokenRow
from app.db.models import OAuthClient, OAuthRequest, User
from app.harness.tokens import _hash

Sessions = Callable[[], AbstractContextManager[Session]]

SCOPE = "patterns"  # one scope: what the person may see and send, as with a pasted token
ACCESS_PREFIX = "oat_"
REFRESH_PREFIX = "ort_"
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)
REQUEST_TTL = timedelta(minutes=10)  # from /authorize to Allow
CODE_TTL = timedelta(minutes=5)  # from Allow to the token exchange
REGISTRATIONS_PER_HOUR = 200  # registering is open to anyone, so it is capped
CAN_CONNECT = ("supervisor", "member")  # HR and admins have no MCP tools


def _now() -> datetime:
    # The wall clock throughout, also for the Allow page: the SDK checks code expiry against it.
    return datetime.now(UTC)


def _aware(moment: datetime | None) -> datetime | None:
    # SQLite gives naive datetimes back; they were written in UTC.
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def client_name(info: dict) -> str:
    """The name the assistant gave itself, as shown to the person: its own claim, never trusted."""
    return (info.get("client_name") or "An assistant").strip()[:40] or "An assistant"


class PatternsOAuth:
    """The SDK's `OAuthAuthorizationServerProvider`, on our database."""

    def __init__(self, sessions: Sessions, app_url: str):
        self.sessions = sessions
        self.app_url = app_url.rstrip("/")

    # --- clients ---------------------------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self.sessions() as db:
            row = db.get(OAuthClient, client_id[:64])
            return None if row is None else OAuthClientInformationFull.model_validate(row.info)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        with self.sessions() as db:
            recent = db.scalar(
                select(func.count())
                .select_from(OAuthClient)
                .where(OAuthClient.created_at >= _now() - timedelta(hours=1))
            )
            full = recent >= REGISTRATIONS_PER_HOUR
            if not full:
                info = client_info.model_dump(mode="json", exclude_none=True)
                db.add(OAuthClient(client_id=client_info.client_id, info=info, created_at=_now()))
        # The SDK's errors are frozen dataclasses, which cannot pass through a `with` block that
        # sets their traceback, so each is raised once the session is closed.
        if full:
            raise RegistrationError("invalid_client_metadata", "Too many registrations.")

    # --- authorization ---------------------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        with self.sessions() as db:
            row = OAuthRequest(
                client_id=client.client_id,
                params=params.model_dump(mode="json"),
                created_at=_now(),
                expires_at=_now() + REQUEST_TTL,
            )
            db.add(row)
            db.flush()
            return f"{self.app_url}/connect?request={row.id}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        with self.sessions() as db:
            row = db.scalar(
                select(OAuthRequest).where(OAuthRequest.code_hash == _hash(authorization_code))
            )
            if (
                row is None
                or row.client_id != client.client_id
                or row.used_at is not None
                or _aware(row.code_expires_at) <= _now()
            ):
                return None
            p = row.params
            return AuthorizationCode(
                code=authorization_code,
                scopes=p.get("scopes") or [SCOPE],
                expires_at=_aware(row.code_expires_at).timestamp(),
                client_id=row.client_id,
                code_challenge=p["code_challenge"],
                redirect_uri=p["redirect_uri"],
                redirect_uri_provided_explicitly=p["redirect_uri_provided_explicitly"],
                resource=p.get("resource"),
                subject=str(row.user_id),
            )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        with self.sessions() as db:
            outcome = self._grant(db, client, authorization_code)
        if isinstance(outcome, TokenError):
            raise outcome
        return outcome

    def _grant(
        self, db: Session, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken | TokenError:
        # Used once: of two exchanges at the same time, only one updates the row.
        used = db.execute(
            update(OAuthRequest)
            .where(
                OAuthRequest.code_hash == _hash(authorization_code.code),
                OAuthRequest.used_at.is_(None),
            )
            .values(used_at=_now())
        )
        if used.rowcount != 1:
            return TokenError("invalid_grant", "This code was already used.")
        user = db.get(User, uuid.UUID(authorization_code.subject))
        if user is None or user.status != "approved":
            return TokenError("invalid_grant", "This account cannot connect.")
        # One connection per assistant: signing in again replaces the last one.
        db.execute(
            update(TokenRow)
            .where(
                TokenRow.user_id == user.id,
                TokenRow.client_id == client.client_id,
                TokenRow.revoked_at.is_(None),
            )
            .values(revoked_at=_now())
        )
        access, refresh = _pair()
        db.add(
            TokenRow(
                user_id=user.id,
                name=client_name(client.model_dump()),
                token_hash=_hash(access),
                created_at=_now(),
                client_id=client.client_id,
                expires_at=_now() + ACCESS_TTL,
                refresh_hash=_hash(refresh),
                refresh_expires_at=_now() + REFRESH_TTL,
            )
        )
        return _token(access, refresh)

    # --- refreshing and revoking -----------------------------------------------------------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        with self.sessions() as db:
            row = _live(db, TokenRow.refresh_hash == _hash(refresh_token))
            if row is None or row.client_id != client.client_id:
                return None
            if _aware(row.refresh_expires_at) <= _now():
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=row.client_id,
                scopes=[SCOPE],
                expires_at=int(_aware(row.refresh_expires_at).timestamp()),
                subject=str(row.user_id),
            )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        access, refresh = _pair()
        with self.sessions() as db:
            # Both rotate; an old refresh token no longer matches anything.
            rotated = db.execute(
                update(TokenRow)
                .where(
                    TokenRow.refresh_hash == _hash(refresh_token.token),
                    TokenRow.client_id == client.client_id,
                    TokenRow.revoked_at.is_(None),
                )
                .values(
                    token_hash=_hash(access),
                    expires_at=_now() + ACCESS_TTL,
                    refresh_hash=_hash(refresh),
                    refresh_expires_at=_now() + REFRESH_TTL,
                )
            )
            ok = rotated.rowcount == 1
        if not ok:
            raise TokenError("invalid_grant", "This refresh token is no longer valid.")
        return _token(access, refresh)

    async def load_access_token(self, token: str) -> AccessToken | None:
        with self.sessions() as db:
            row = _live(db, TokenRow.token_hash == _hash(token))
            if row is None or row.client_id is None or _aware(row.expires_at) <= _now():
                return None
            return AccessToken(
                token=token,
                client_id=row.client_id,
                scopes=[SCOPE],
                expires_at=int(_aware(row.expires_at).timestamp()),
                subject=str(row.user_id),
            )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        with self.sessions() as db:
            digest = _hash(token.token)
            db.execute(
                update(TokenRow)
                .where(
                    (TokenRow.token_hash == digest) | (TokenRow.refresh_hash == digest),
                    TokenRow.revoked_at.is_(None),
                )
                .values(revoked_at=_now())
            )


def _pair() -> tuple[str, str]:
    return ACCESS_PREFIX + secrets.token_urlsafe(32), REFRESH_PREFIX + secrets.token_urlsafe(32)


def _token(access: str, refresh: str) -> OAuthToken:
    return OAuthToken(
        access_token=access,
        token_type="Bearer",
        expires_in=int(ACCESS_TTL.total_seconds()),
        scope=SCOPE,
        refresh_token=refresh,
    )


def _live(db: Session, condition) -> TokenRow | None:
    return db.scalar(select(TokenRow).where(condition, TokenRow.revoked_at.is_(None)))


# --- the app's Allow page --------------------------------------------------------------------


def _request(db: Session, request_id: str, lock: bool = False) -> OAuthRequest:
    try:
        key = uuid.UUID(request_id)
    except ValueError:
        raise ApiError(404, "not_found", "This sign-in link is not valid.") from None
    query = select(OAuthRequest).where(OAuthRequest.id == key)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(query)
    if row is None:
        raise ApiError(404, "not_found", "This sign-in link is not valid.")
    return row


def _open(row: OAuthRequest, now: datetime) -> None:
    if row.decided_at is not None:
        raise ApiError(409, "already_decided", "This sign-in was already answered.")
    if _aware(row.expires_at) <= now:
        raise ApiError(410, "expired", "This sign-in has expired. Start again from the assistant.")


def describe(db: Session, request_id: str) -> dict:
    """What the Allow page shows: who is asking, by their own name, and where the answer goes,
    which is the part an impostor cannot fake."""
    row = _request(db, request_id)
    _open(row, _now())
    client = db.get(OAuthClient, row.client_id)
    return {
        "client_name": client_name(client.info if client else {}),
        "redirect_host": urlparse(row.params["redirect_uri"]).hostname or "",
        "expires_at": _aware(row.expires_at),
    }


def decide(db: Session, user: User, request_id: str, allow: bool) -> str:
    """Allow or Deny, once; returns the URL to send the browser back to the assistant."""
    now = _now()
    row = _request(db, request_id, lock=True)
    _open(row, now)
    if allow and user.role not in CAN_CONNECT:
        raise ApiError(403, "cannot_connect", "Only supervisors and members can connect one.")
    row.decided_at = now
    p = row.params
    if not allow:
        return construct_redirect_uri(
            p["redirect_uri"], error="access_denied", state=p.get("state")
        )
    code = secrets.token_urlsafe(32)
    row.user_id = user.id
    row.code_hash = _hash(code)
    row.code_expires_at = now + CODE_TTL
    return construct_redirect_uri(p["redirect_uri"], code=code, state=p.get("state"))
