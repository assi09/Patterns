"""What happens when a supervisor approves or declines a team action the agent proposed.

Approving a message sends it to every active member's inbox, unsigned by any member and naming
nobody. Approving a challenge tells every member what it is and for which days; it is measured for
the team once it ends (`app.teams.agent.challenge_result`). Declining changes nothing for members.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db.models import Notification, Team, TeamAction, TeamMembership


def action_of(db: Session, team: Team, action_id: str) -> TeamAction:
    action = next(
        (
            a
            for a in db.scalars(select(TeamAction).where(TeamAction.team_id == team.id))
            if str(a.id) == action_id
        ),
        None,
    )
    if action is None:
        raise ApiError(404, "not_found", "There is no such proposal.")
    return action


def decide(db: Session, team: Team, action: TeamAction, approve: bool, now: datetime) -> int:
    """Approves or declines a proposal once; returns how many members were told."""
    if action.status != "proposed":
        raise ApiError(409, "already_decided", "This proposal was already decided.")
    action.decided_at = now
    if not approve:
        action.status = "declined"
        db.flush()
        return 0
    action.status = "approved"
    members = db.scalars(
        select(TeamMembership.user_id).where(
            TeamMembership.team_id == team.id, TeamMembership.left_at.is_(None)
        )
    ).all()
    if action.kind == "challenge":
        title = f"{team.name} challenge: {action.title}"
        body = f"{action.body} From {action.starts_on:%b %-d} to {action.ends_on:%b %-d}."
    else:
        title, body = f"A note for {team.name}: {action.title}", action.body
    for user_id in members:
        db.add(
            Notification(
                user_id=user_id,
                kind="team_note" if action.kind == "message" else "team_challenge",
                title=title[:80],
                body=body[:400],
                link="/",
                created_at=now,
            )
        )
    db.flush()
    return len(members)
