"""Sign-up, log-in and the owner's approval of sign-ups.

The app sends the session token as `Authorization: Bearer <token>`. Admins are the emails in
`FA_ADMIN_EMAILS`; approving someone here does not add them as a Google test user, which is
still done by hand in the Google Cloud console.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.api import schemas
from app.auth import accounts
from app.auth.accounts import AuthError, LoginThrottle
from app.config import settings
from app.db.models import User
from app.db.session import session_scope

router = APIRouter(tags=["auth"])
throttle = LoginThrottle()


def get_db() -> Iterator[Session]:
    """FastAPI dependency; tests override it with a SQLite database."""
    with session_scope() as session:
        yield session


def now() -> datetime:
    """FastAPI dependency, so tests can move the clock."""
    return datetime.now(UTC)


Db = Annotated[Session, Depends(get_db)]
Now = Annotated[datetime, Depends(now)]


def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AuthError(401, "signed_out", "Sign in to continue.")
    return token


Token = Annotated[str, Depends(bearer_token)]


def current_user(db: Db, token: Token, clock: Now) -> User:
    user = accounts.user_for_token(db, token, clock)
    if user is None:
        raise AuthError(401, "signed_out", "Your session has ended. Sign in again.")
    return user


def is_admin(user: User) -> bool:
    admins = {email.strip().lower() for email in settings.admin_emails}
    return user.status == "approved" and user.email in admins


def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    if not is_admin(user):
        raise AuthError(403, "forbidden", "Only the app's owner can do this.")
    return user


def approved_user(user: Annotated[User, Depends(current_user)]) -> User:
    if user.status != "approved":
        raise AuthError(403, "not_approved", "Your account is waiting for approval.")
    return user


def _account(user: User) -> schemas.Account:
    return schemas.Account(
        email=user.email,
        status=user.status,
        is_admin=is_admin(user),
        role=user.role,
        personal_features=settings.personal_features,
    )


@router.post("/auth/signup", response_model=schemas.SignedIn, status_code=201)
def sign_up(body: schemas.Credentials, db: Db, clock: Now) -> schemas.SignedIn:
    user = accounts.sign_up(db, body.email, body.password)
    if body.hr_invite:  # from an HR invitation link: approved as that team's HR at once
        from app.teams import hr  # here, so accounts do not depend on teams at import

        hr.accept(db, user, body.hr_invite, clock)
    token = accounts.start_session(db, user, clock, settings.session_days)
    return schemas.SignedIn(token=token, account=_account(user))


@router.post("/auth/login", response_model=schemas.SignedIn)
def log_in(body: schemas.Credentials, db: Db, clock: Now) -> schemas.SignedIn:
    throttle.check(body.email, clock)
    try:
        user = accounts.log_in(db, body.email, body.password)
    except AuthError:
        throttle.failed(body.email, clock)
        raise
    throttle.succeeded(body.email)
    token = accounts.start_session(db, user, clock, settings.session_days)
    return schemas.SignedIn(token=token, account=_account(user))


@router.post("/auth/logout", status_code=204)
def log_out(db: Db, token: Token) -> Response:
    accounts.end_session(db, token)
    return Response(status_code=204)


@router.get("/auth/me", response_model=schemas.Account)
def me(user: Annotated[User, Depends(current_user)]) -> schemas.Account:
    return _account(user)


@router.get("/admin/access-requests", response_model=list[schemas.AccessRequest])
def access_requests(db: Db, _: Annotated[User, Depends(admin_user)]) -> list:
    return [
        schemas.AccessRequest(id=str(user.id), email=user.email, requested_at=user.created_at)
        for user in accounts.pending(db)
    ]


def _decide(
    db: Session, user_id: str, approve: bool, clock: datetime, role: str = "member"
) -> schemas.Account:
    try:
        key = uuid.UUID(user_id)
    except ValueError:
        raise AuthError(404, "not_found", "No such account.") from None
    return _account(accounts.decide(db, key, approve, clock, role))


@router.post("/admin/access-requests/{user_id}/approve", response_model=schemas.Account)
def approve(
    user_id: str,
    db: Db,
    clock: Now,
    _: Annotated[User, Depends(admin_user)],
    body: schemas.Approval | None = None,
) -> schemas.Account:
    return _decide(db, user_id, True, clock, (body or schemas.Approval()).role)


@router.post("/admin/access-requests/{user_id}/reject", response_model=schemas.Account)
def reject(
    user_id: str, db: Db, clock: Now, _: Annotated[User, Depends(admin_user)]
) -> schemas.Account:
    return _decide(db, user_id, False, clock)
