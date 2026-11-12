"""Creating teams, joining and leaving them, and the two consents a member gives.

Joining shares only team aggregates, never built from fewer than MIN_MEMBERS people. Showing one's
own named weekly levels to the supervisor is a second consent, off until the member turns it on.
Every change is written to `team_events`. Nothing here reads anyone's health data.
"""

import secrets
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.team import MIN_MEMBERS as TEAM_MINIMUM
from app.api.errors import ApiError
from app.db.models import Team, TeamEvent, TeamMembership, User

MIN_MEMBERS = TEAM_MINIMUM  # no team figure is built from fewer people
# Codes avoid letters and digits that read alike (0/O, 1/I/L), so they can be read out loud.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8

# The texts a member agrees to. A change of wording gets a new version; each membership keeps the
# version it was given.
CONSENT_VERSION = "teams-v1"
CONSENT_TEXT = (
    "Your supervisor will see weekly figures about the whole team: how its sleep, activity, "
    "recovery, strain and stress changed, each built from at least {minimum} people. They will "
    "not see your name, your own values, your days, your chats or anything else from your "
    "account, and they will not see whether you joined. You can leave at any time in Settings; "
    "from then on your data is left out of the team's figures."
)
LEVELS_CONSENT_VERSION = "team-levels-v1"
LEVELS_CONSENT_TEXT = (
    "Your supervisor will also see your name with your own weekly recovery, sleep, strain and "
    "stress, each as below, within or above your own usual range and as the week's average. "
    "Nothing else: no days, no other metrics, no chats. You can turn this off at any time; your "
    "row then disappears, including from past weeks."
)


def consent_text() -> str:
    return CONSENT_TEXT.format(minimum=MIN_MEMBERS)


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(code: str) -> str:
    """People type codes with spaces, dashes and in lower case."""
    return "".join(c for c in code.upper() if c.isalnum())


def _event(db: Session, team: Team, user: User | None, event: str, now: datetime) -> None:
    db.add(
        TeamEvent(team_id=team.id, user_id=user.id if user else None, event=event, created_at=now)
    )


def create_team(
    db: Session, supervisor: User, name: str, report_email: str | None, now: datetime
) -> Team:
    team = Team(
        supervisor_id=supervisor.id,
        name=name.strip(),
        invite_code=_unused_code(db),
        report_email=report_email,
        created_at=now,
    )
    db.add(team)
    db.flush()
    _event(db, team, supervisor, "created", now)
    return team


def _unused_code(db: Session) -> str:
    while True:
        code = new_code()
        if db.scalar(select(Team.id).where(Team.invite_code == code)) is None:
            return code


def rotate_code(db: Session, team: Team, supervisor: User, now: datetime) -> Team:
    team.invite_code = _unused_code(db)
    _event(db, team, supervisor, "code_rotated", now)
    return team


def supervised(db: Session, supervisor: User) -> list[Team]:
    return list(
        db.scalars(
            select(Team).where(Team.supervisor_id == supervisor.id).order_by(Team.created_at)
        )
    )


def supervised_team(db: Session, supervisor: User, team_id: str) -> Team:
    """The supervisor's own team; another supervisor's is as unknown as one that does not exist."""
    team = _team(db, team_id)
    if team is None or team.supervisor_id != supervisor.id:
        raise ApiError(404, "not_found", "No such team.")
    return team


def _team(db: Session, team_id: str) -> Team | None:
    try:
        key = uuid.UUID(team_id)
    except ValueError:
        return None
    return db.get(Team, key)


def active_members(db: Session, team: Team) -> int:
    return db.scalar(
        select(func.count())
        .select_from(TeamMembership)
        .where(TeamMembership.team_id == team.id, TeamMembership.left_at.is_(None))
    )


def member_ids(db: Session, team: Team) -> set[uuid.UUID]:
    return set(
        db.scalars(
            select(TeamMembership.user_id).where(
                TeamMembership.team_id == team.id, TeamMembership.left_at.is_(None)
            )
        )
    )


def overlap_problem(db: Session, team: Team) -> str | None:
    """Why this team's figures are paused, or None. One supervisor may run several teams (a
    department and its squads), but two of them that share people must differ by at least
    MIN_MEMBERS people each way, or comparing their figures could single someone out."""
    mine = member_ids(db, team)
    others = db.scalars(
        select(Team).where(Team.supervisor_id == team.supervisor_id, Team.id != team.id)
    )
    for other in others:
        theirs = member_ids(db, other)
        if not mine & theirs:
            continue
        if 0 < len(mine - theirs) < MIN_MEMBERS or 0 < len(theirs - mine) < MIN_MEMBERS:
            return (
                f"It shares people with your team {other.name!r} and differs from it by fewer "
                f"than {MIN_MEMBERS} people, so comparing the two could single someone out. Its "
                f"figures are paused until the two teams differ by at least {MIN_MEMBERS} people "
                "or not at all."
            )
    return None


def team_for_code(db: Session, code: str) -> Team | None:
    return db.scalar(select(Team).where(Team.invite_code == normalize_code(code)))


def _active(db: Session, team: Team, user: User) -> TeamMembership | None:
    return db.scalar(
        select(TeamMembership).where(
            TeamMembership.team_id == team.id,
            TeamMembership.user_id == user.id,
            TeamMembership.left_at.is_(None),
        )
    )


def join(db: Session, team: Team, user: User, now: datetime) -> TeamMembership:
    if team.supervisor_id == user.id:
        raise ApiError(409, "own_team", "You supervise this team, so you cannot join it.")
    if _active(db, team, user) is not None:
        raise ApiError(409, "already_member", "You are already in this team.")
    membership = TeamMembership(
        team_id=team.id, user_id=user.id, joined_at=now, consent_version=CONSENT_VERSION
    )
    db.add(membership)
    _event(db, team, user, "joined", now)
    db.flush()
    return membership


def memberships(db: Session, user: User) -> list[tuple[TeamMembership, Team, User]]:
    """The person's active memberships, each with its team and supervisor."""
    rows = db.execute(
        select(TeamMembership, Team, User)
        .join(Team, Team.id == TeamMembership.team_id)
        .join(User, User.id == Team.supervisor_id)
        .where(TeamMembership.user_id == user.id, TeamMembership.left_at.is_(None))
        .order_by(TeamMembership.joined_at)
    )
    return [tuple(row) for row in rows]


def own_membership(db: Session, user: User, team_id: str) -> tuple[TeamMembership, Team]:
    team = _team(db, team_id)
    membership = _active(db, team, user) if team else None
    if membership is None:
        raise ApiError(404, "not_found", "You are not in this team.")
    return membership, team


def leave(db: Session, user: User, team_id: str, now: datetime) -> None:
    membership, team = own_membership(db, user, team_id)
    membership.left_at = now
    membership.share_levels = False
    membership.levels_changed_at = now
    _event(db, team, user, "left", now)


def share_levels(
    db: Session, user: User, team_id: str, share: bool, now: datetime
) -> TeamMembership:
    membership, team = own_membership(db, user, team_id)
    if membership.share_levels == share:
        return membership
    membership.share_levels = share
    membership.levels_changed_at = now
    if share:
        membership.levels_consent_version = LEVELS_CONSENT_VERSION
    _event(db, team, user, "levels_shared" if share else "levels_unshared", now)
    return membership
