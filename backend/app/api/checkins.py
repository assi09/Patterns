"""Check-in alerts over HTTP (docs/escalation.md, app/teams/checkin.py).

- The person: turns check-in alerts on or off per team, sees their own alerts with the evidence
  behind them, and can stop one while it waits.
- HR and the supervisor: see the alerts sent to them (who, which team, when; never why), open
  and mark them. Someone else's alert answers like one that does not exist.
- The supervisor: names the team's HR contact.

Everything here is code; no model is involved.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.api import schemas
from app.api.auth import Db, Now, approved_user
from app.api.errors import ApiError
from app.api.teams import Supervisor, _membership
from app.db.models import CheckinAlert, Team, User
from app.teams import checkin
from app.teams import memberships as teams

router = APIRouter(tags=["checkins"])
Person = Annotated[User, Depends(approved_user)]


def _evidence(record: dict) -> schemas.CheckinEvidence:
    stats = record["stats"]
    usual, recent = record["windows"]
    return schemas.CheckinEvidence(
        id=record["id"],
        metric=record["metrics"][0],
        direction=stats["direction"],
        usual_low=stats["usual_low"],
        usual_high=stats["usual_high"],
        margin=stats["margin"],
        days_far=stats["days_far"],
        days_worn=stats["days_worn"],
        recent_mean=stats["recent_mean"],
        usual=schemas.Window(**usual),
        recent=schemas.Window(**recent),
    )


def _own(db, alert: CheckinAlert, team: Team) -> schemas.OwnCheckin:
    return schemas.OwnCheckin(
        id=str(alert.id),
        team_id=str(team.id),
        team=team.name,
        status=alert.status,
        raised_at=alert.raised_at,
        send_after=alert.send_after,
        sent_at=alert.sent_at,
        withdrawn_at=alert.withdrawn_at,
        recipients=checkin.RECIPIENTS,
        evidence=[_evidence(record) for record in alert.evidence],
    )


def _received(item: checkin.Received) -> schemas.ReceivedCheckin:
    def mark(m: checkin.Mark) -> schemas.CheckinMark:
        return schemas.CheckinMark(role=m.role, outcome=m.outcome, marked_at=m.marked_at)

    return schemas.ReceivedCheckin(
        id=str(item.id),
        person=item.person,
        team=item.team,
        sent_at=item.sent_at,
        mine=mark(item.mine),
        others=[mark(m) for m in item.others],
        note=item.note,
    )


# The person


@router.post("/me/teams/{team_id}/checkin", response_model=schemas.Membership)
def share_checkin(
    team_id: str, body: schemas.ShareCheckin, db: Db, clock: Now, user: Person
) -> schemas.Membership:
    """Turns check-in alerts on or off for one team; off withdraws any alert still waiting."""
    if body.share and body.consent_version != checkin.CONSENT_VERSION:
        raise ApiError(409, "consent_changed", "Read what check-in alerts mean first.")
    membership, team = teams.own_membership(db, user, team_id)
    checkin.set_consent(db, membership, team, body.share, clock)
    return _membership(membership, team, db.get(User, team.supervisor_id))


@router.get("/me/checkins", response_model=list[schemas.OwnCheckin])
def my_checkins(db: Db, user: Person) -> list[schemas.OwnCheckin]:
    return [_own(db, alert, team) for alert, team in checkin.own_alerts(db, user)]


@router.post("/me/checkins/{alert_id}/send", response_model=schemas.OwnCheckin)
def send_now(alert_id: str, db: Db, clock: Now, user: Person) -> schemas.OwnCheckin:
    """The person sends their own waiting alert now, before the hour is up."""
    alert = checkin.send_now(db, user, alert_id, clock)
    return _own(db, alert, db.get(Team, alert.team_id))


@router.post("/me/checkins/{alert_id}/stop", response_model=schemas.OwnCheckin)
def stop(alert_id: str, db: Db, clock: Now, user: Person) -> schemas.OwnCheckin:
    """The person stops this alert. Check-in alerts stay on; the switch turns them off."""
    alert = checkin.stop(db, user, alert_id, clock)
    return _own(db, alert, db.get(Team, alert.team_id))


# HR and the supervisor


@router.get("/checkins", response_model=list[schemas.ReceivedCheckin])
def received(db: Db, user: Person) -> list[schemas.ReceivedCheckin]:
    return [_received(item) for item in checkin.received(db, user)]


@router.post("/checkins/{alert_id}/open", response_model=schemas.ReceivedCheckin)
def open_checkin(alert_id: str, db: Db, clock: Now, user: Person) -> schemas.ReceivedCheckin:
    return _received(checkin.open_alert(db, user, alert_id, clock))


@router.post("/checkins/{alert_id}/mark", response_model=schemas.ReceivedCheckin)
def mark_checkin(
    alert_id: str, body: schemas.MarkCheckin, db: Db, clock: Now, user: Person
) -> schemas.ReceivedCheckin:
    return _received(checkin.mark_alert(db, user, alert_id, body.outcome, body.note, clock))


# The supervisor


@router.put("/teams/{team_id}/hr", response_model=schemas.TeamHr)
def set_hr(team_id: str, body: schemas.TeamHr, db: Db, user: Supervisor) -> schemas.TeamHr:
    """Names the team's HR contact: an approved account with the hr role, or none."""
    team = teams.supervised_team(db, user, team_id)
    if body.email is None:
        team.hr_id = None
        return schemas.TeamHr(email=None)
    hr = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if hr is None or hr.status != "approved" or hr.role != "hr":
        raise ApiError(404, "not_hr", "There is no approved HR account with that email.")
    team.hr_id = hr.id
    return schemas.TeamHr(email=hr.email)
