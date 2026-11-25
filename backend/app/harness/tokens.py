"""Personal access tokens for the MCP server: made in the app, shown once, stored as a hash."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db.models import AccessToken, HarnessCall, User

PREFIX = "pat_"  # so a leaked token is recognisable in logs and scanners
OAUTH_PREFIX = "oat_"  # an OAuth access token (app.harness.oauth.ACCESS_PREFIX)
MAX_TOKENS = 5  # per person, so an old one is revoked before many pile up


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def make(db: Session, user: User, name: str, now: datetime) -> tuple[AccessToken, str]:
    """A new token for the person; the token itself is returned once and never stored."""
    active = db.scalars(
        select(AccessToken).where(
            AccessToken.user_id == user.id,
            AccessToken.revoked_at.is_(None),
            AccessToken.client_id.is_(None),  # OAuth sign-ins are one per assistant instead
        )
    ).all()
    if len(active) >= MAX_TOKENS:
        raise ApiError(409, "too_many_tokens", f"Revoke a token first: at most {MAX_TOKENS}.")
    token = PREFIX + secrets.token_urlsafe(32)
    row = AccessToken(
        user_id=user.id, name=name.strip()[:60], token_hash=_hash(token), created_at=now
    )
    db.add(row)
    db.flush()
    return row, token


def listing(db: Session, user: User) -> list[AccessToken]:
    return list(
        db.scalars(
            select(AccessToken)
            .where(AccessToken.user_id == user.id)
            .order_by(AccessToken.created_at.desc())
        )
    )


def revoke(db: Session, user: User, token_id: str, now: datetime) -> AccessToken:
    try:
        key = uuid.UUID(token_id)
    except ValueError:
        raise ApiError(404, "not_found", "No such token.") from None
    row = db.get(AccessToken, key)
    if row is None or row.user_id != user.id:
        raise ApiError(404, "not_found", "No such token.")
    row.revoked_at = row.revoked_at or now
    return row


def holder(db: Session, token: str, now: datetime) -> tuple[User, AccessToken] | None:
    """The approved account a live token belongs to, recording its use; None otherwise. Takes a
    pasted token or an OAuth access token (`app.harness.oauth`), which also has to be unexpired."""
    if not token.startswith((PREFIX, OAUTH_PREFIX)):
        return None
    row = db.scalar(select(AccessToken).where(AccessToken.token_hash == _hash(token)))
    if row is None or row.revoked_at is not None:
        return None
    if row.expires_at is not None:
        expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
        if expires <= now:
            return None
    user = db.get(User, row.user_id)
    if user is None or user.status != "approved":
        return None
    row.last_used_at = now
    return user, row


def activity(db: Session, token_ids: list, since: datetime) -> dict:
    """Per token, its tool calls since `since`: [(tool, calls, failed)], most used first."""
    if not token_ids:
        return {}
    rows = db.execute(
        select(
            HarnessCall.token_id,
            HarnessCall.tool,
            func.count(),
            func.sum(case((HarnessCall.ok.is_(False), 1), else_=0)),
        )
        .where(HarnessCall.token_id.in_(token_ids), HarnessCall.at >= since)
        .group_by(HarnessCall.token_id, HarnessCall.tool)
    ).all()
    out: dict = {}
    for token_id, tool, calls, failed in rows:
        out.setdefault(token_id, []).append((tool, int(calls), int(failed or 0)))
    for items in out.values():
        items.sort(key=lambda item: -item[1])
    return out
