"""A team's HR contact: invited by the supervisor, signed up through the emailed link.

HR receives check-in alerts with the supervisor and sees nothing else (docs/escalation.md). Sign-up
does not verify addresses, so the invitation does it: the link carries a one-time token that only
the invited address received, and signing up with it and that address makes the account an
approved HR account for that team. An existing account that is not HR is never converted quietly.
"""

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.auth.accounts import AuthError, normalize_email
from app.db.models import HrInvite, Team, User
from app.email import Email, Mailer, MailError

logger = logging.getLogger(__name__)

INVITE_DAYS = 7


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _account(db: Session, email: str) -> User | None:
    # The exact address, not the Gmail mailbox: "+hr" and "+member" aliases are separate accounts.
    return db.scalar(select(User).where(User.email == email))


def pending(db: Session, team: Team, now: datetime | None = None) -> HrInvite | None:
    """The team's invitation still waiting for its person, if any."""
    now = now or datetime.now(UTC)
    return db.scalar(
        select(HrInvite)
        .where(
            HrInvite.team_id == team.id,
            HrInvite.accepted_at.is_(None),
            HrInvite.expires_at > now,
        )
        .order_by(HrInvite.created_at.desc())
    )


def invite_email(team: Team, supervisor: User, to: str, link: str) -> Email:
    text = (
        f"{supervisor.email} named you as the HR contact for their team {team.name} in "
        "Patterns.\n\n"
        "Patterns shows a team's weekly figures to its supervisor. When a team member who chose to "
        "turn on check-in alerts has a sustained, extreme change in their own data, you and the "
        "supervisor are asked to check in with them. You see their name only, never their data.\n\n"
        f"Create your HR account (the link works for {INVITE_DAYS} days, for this address only):\n"
        f"{link}\n\nIf you did not expect this, ignore this email."
    )
    html = "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in text.split("\n\n"))
    return Email(to=to, subject=f"Become the HR contact for {team.name}", text=text, html=html)


def set_contact(
    db: Session,
    team: Team,
    supervisor: User,
    email: str | None,
    now: datetime,
    mailer: Mailer,
    app_url: str,
) -> tuple[str | None, bool]:
    """Names, invites or removes the team's HR contact; returns (email, invited)."""
    db.execute(delete(HrInvite).where(HrInvite.team_id == team.id, HrInvite.accepted_at.is_(None)))
    if email is None or not email.strip():
        team.hr_id = None
        return None, False
    try:
        email = normalize_email(email)
    except AuthError:
        raise ApiError(422, "invalid_email", "Enter an email address.") from None
    existing = _account(db, email)
    if existing is not None:
        if existing.role != "hr" or existing.status != "approved":
            raise ApiError(
                409,
                "not_hr",
                "This person already has a Patterns account that is not an HR account. Ask the "
                "app's owner to make it one, or use another address.",
            )
        team.hr_id = existing.id
        return existing.email, False
    token = secrets.token_urlsafe(32)
    db.add(
        HrInvite(
            team_id=team.id,
            email=email,
            token_hash=_hash(token),
            invited_by=supervisor.id,
            created_at=now,
            expires_at=now + timedelta(days=INVITE_DAYS),
        )
    )
    link = f"{app_url.rstrip('/')}/sign-up?hr={token}"
    try:
        mailer.send(invite_email(team, supervisor, email, link))
    except MailError as error:
        logger.warning("The HR invitation could not be sent: %s", error)
        raise ApiError(502, "email_failed", "The invitation email could not be sent.") from None
    return email, True


def accept(db: Session, user: User, token: str, now: datetime) -> Team:
    """Makes a new account the HR contact its invitation was for."""
    invite = db.scalar(select(HrInvite).where(HrInvite.token_hash == _hash(token)))
    if (
        invite is None
        or invite.accepted_at is not None
        or invite.expires_at.replace(tzinfo=now.tzinfo) <= now
    ):
        raise ApiError(400, "invite_invalid", "This invitation has expired or was already used.")
    if user.email != invite.email:
        raise ApiError(400, "invite_other_email", "This invitation is for another email address.")
    team = db.get(Team, invite.team_id)
    user.status, user.role, user.decided_at = "approved", "hr", now
    team.hr_id = user.id
    invite.accepted_at = now
    return team


def notice_email(to: str, app_url: str) -> Email:
    """What the supervisor and HR contact are emailed for a check-in request: no name, nothing
    else, as in the app's inbox; the name is shown only on Check-ins, behind the role check."""
    link = f"{app_url.rstrip('/')}/checkins"
    text = (
        "You have a check-in request in Patterns.\n\n"
        f"Open Check-ins to see who it is about: {link}\n\n"
        "For privacy this email does not say who it is about."
    )
    html = "".join(f"<p>{escape(p)}</p>" for p in text.split("\n\n"))
    return Email(to=to, subject="You have a check-in request", text=text, html=html)
