"""Sign-up, log-in, sessions and approval, on top of the `users` and `auth_sessions` tables.

A new account is pending until the owner approves it. Pending people can sign in (the app shows
them that they are waiting) but cannot reach any data.
"""

import hashlib
import re
import secrets
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.auth.passwords import DUMMY_HASH, hash_password, verify_password
from app.config import settings
from app.db.models import AuthSession, User

MIN_PASSWORD = 10
MAX_PASSWORD = 128
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    """A request the person can fix; `message` is safe to show them."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 320 or not EMAIL.match(email):
        raise AuthError(422, "invalid_email", "Enter a valid email address.")
    return email


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(
            422, "weak_password", f"Use a password of at least {MIN_PASSWORD} characters."
        )
    if len(password) > MAX_PASSWORD:
        raise AuthError(
            422, "weak_password", f"Use a password of at most {MAX_PASSWORD} characters."
        )


def sign_up(session: Session, email: str, password: str) -> User:
    email = normalize_email(email)
    check_password(password)
    if session.scalar(select(User.id).where(User.email == email)) is not None:
        raise AuthError(409, "email_taken", "An account with this email already exists.")
    user = User(email=email, password_hash=hash_password(password), status="pending")
    if invited(email):
        user.status = "approved"  # the owner already chose them; no wait before connecting
    session.add(user)
    session.flush()
    return user


def mailbox(email: str) -> str:
    """One form per mailbox: lower case, and for Gmail without dots or a "+tag" (Gmail ignores
    both), so "Some.Person@gmail.com" matches an invite to "someperson@gmail.com"."""
    local, _, domain = email.strip().lower().partition("@")
    if domain in ("gmail.com", "googlemail.com"):
        local = local.split("+", 1)[0].replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def invited(email: str) -> bool:
    """Whether this address was invited to the pilot. Sign-up does not verify addresses, so this
    trusts that the invited addresses are not known to others: fine for a small private pilot."""
    return mailbox(email) in {mailbox(e) for e in settings.invited_emails if "@" in e}


def log_in(session: Session, email: str, password: str) -> User:
    """The user, or one error whatever was wrong, so it does not reveal who has an account."""
    wrong = AuthError(401, "invalid_credentials", "Wrong email or password.")
    try:
        email = normalize_email(email)
    except AuthError:
        raise wrong from None
    user = session.scalar(select(User).where(User.email == email))
    if user is None or user.password_hash is None:
        verify_password(password, DUMMY_HASH)
        raise wrong
    if not verify_password(password, user.password_hash):
        raise wrong
    return user


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(session: Session, user: User, now: datetime, days: int) -> str:
    """A new random token for this device; only its hash is stored."""
    token = secrets.token_urlsafe(32)
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=_token_hash(token),
            created_at=now,
            expires_at=now + timedelta(days=days),
        )
    )
    session.flush()
    return token


def user_for_token(session: Session, token: str, now: datetime) -> User | None:
    record = session.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if record is None:
        return None
    expires = record.expires_at
    if expires.tzinfo is None:  # SQLite drops the zone
        expires = expires.replace(tzinfo=now.tzinfo)
    if expires <= now:
        session.delete(record)
        return None
    return session.get(User, record.user_id)


def end_session(session: Session, token: str) -> None:
    session.execute(delete(AuthSession).where(AuthSession.token_hash == _token_hash(token)))


def pending(session: Session) -> list[User]:
    return list(
        session.scalars(select(User).where(User.status == "pending").order_by(User.created_at))
    )


def set_password(session: Session, user: User, password: str) -> None:
    """Sets or replaces the password and signs the person out everywhere.

    How the local data owner, created by the sync without a password, claims their account.
    """
    check_password(password)
    user.password_hash = hash_password(password)
    session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    session.flush()


def decide(
    session: Session, user_id: uuid.UUID, approve: bool, now: datetime, role: str = "member"
) -> User:
    """Approve or reject a sign-up; an approval also sets the role (supervisors see team pages)."""
    user = session.get(User, user_id)
    if user is None:
        raise AuthError(404, "not_found", "No such account.")
    user.status = "approved" if approve else "rejected"
    if approve:
        user.role = role
    user.decided_at = now
    if not approve:  # a rejected person is signed out everywhere
        session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    session.flush()
    return user


class LoginThrottle:
    """Refuses log-ins for an email after too many recent failures, to slow password guessing.

    Kept in memory: enough for one server process; a shared store is needed with several.
    """

    def __init__(self, max_failures: int = 5, window: timedelta = timedelta(minutes=15)):
        self.max_failures = max_failures
        self.window = window
        self._failures: dict[str, deque[datetime]] = defaultdict(deque)

    def _recent(self, key: str, now: datetime) -> deque[datetime]:
        failures = self._failures[key]
        while failures and failures[0] <= now - self.window:
            failures.popleft()
        return failures

    def check(self, email: str, now: datetime) -> None:
        if len(self._recent(email.strip().lower(), now)) >= self.max_failures:
            raise AuthError(
                429, "too_many_attempts", "Too many failed attempts. Try again in 15 minutes."
            )

    def failed(self, email: str, now: datetime) -> None:
        self._recent(email.strip().lower(), now).append(now)

    def succeeded(self, email: str) -> None:
        self._failures.pop(email.strip().lower(), None)
