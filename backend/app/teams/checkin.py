"""Check-in alerts: one person's sustained, extreme change, sent to HR and the supervisor.

The second gateway of the team product (docs/escalation.md). Code does all of it, and no model
reads, writes or explains an alert:

1. **Consent.** Only members who turned on check-in alerts for a team, a third consent after
   joining and showing their weekly levels.
2. **The rule** (`detect`), on the person's own history: the last 7 days against the 28 before.
   In at least `MIN_SIGNALS` of the signals, at least `DAYS_FAR` of the 7 days sit past the worse
   edge of the person's usual range (the middle half of the 28 days) by its full width, or by a
   floor when the range is narrow. One bad night, one cold or one trip does not raise it.
3. **The person first.** The alert waits `WAIT`; they see the evidence behind it and can turn
   check-in alerts off, which withdraws it.
4. **Then HR and the supervisor**, each told only "please check in with <person>", never a
   metric, value or reason. Each marks it checked in or not needed; an alert nobody has marked
   after `REMIND_AFTER` is shown to them once more.

Every step is written to `checkin_events` with who and when, and no health data.
"""

import logging
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alarms.run import Sessions
from app.analysis.day import with_scores
from app.analysis.evidence import Evidence, Window
from app.analysis.tools import LOW_WEAR_MINUTES
from app.api.errors import ApiError
from app.db.daily import load_daily
from app.db.models import (
    CheckinAlert,
    CheckinEvent,
    CheckinMark,
    Notification,
    Team,
    TeamMembership,
    User,
)

logger = logging.getLogger(__name__)

RULE = "checkin-v1"  # stored on each alert; a change of the rule below gets a new name
SOURCE = "google_health"
WINDOW_DAYS = 7
BASELINE_DAYS = 28
MIN_BASELINE = 14  # days with a value in the 28 before, for a usual range to mean anything
MIN_WORN = 5  # of the 7 days
DAYS_FAR = 5  # of the 7 days, per signal
MIN_SIGNALS = 2
FAR = 1.0  # widths of the usual range past its worse edge
# signal -> (the worse direction, the smallest gap that counts when the usual range is narrow)
SIGNALS = {
    "sleep_minutes": ("down", 45.0),
    "recovery_score": ("down", 15.0),
    "hrv_ms": ("down", 8.0),
    "resting_hr": ("up", 5.0),
    "stress_score": ("up", 15.0),
}
FRESH_DAYS = 1  # the window ends yesterday or today, not on old data
WAIT = timedelta(hours=24)
COOLDOWN = timedelta(days=28)
REMIND_AFTER = timedelta(days=3)
FIRST_HOUR_UTC = 6  # after the morning's syncs, as the team alerts

CONSENT_VERSION = "checkin-v1"
CONSENT_TEXT = (
    "If your own data shows a sustained, extreme change, for example several signals far outside "
    "your usual range on most days of a week, {recipients} will get a message asking them to "
    "check in with you. The message has your name and nothing else: no values, no metrics, no "
    "reason. You are told first, see what raised it, and have 24 hours to turn this off before "
    "anything is sent. You can turn it off at any time."
)

PERSON_TITLE = "Check-in alert: you can still stop it"
PERSON_BODY = (
    "Your data in the last 7 days met the check-in rule you agreed to. In 24 hours {recipients} "
    "will be asked to check in with you. Open it to see why, or turn check-in alerts off."
)
RECIPIENT_TITLE = "Please check in with {person}"
RECIPIENT_BODY = (
    "{person} agreed to check-in alerts in {team}, and their own data met the agreed rule. No "
    "details are shared. Mark it in the app once you have checked in."
)


# --- the rule -------------------------------------------------------------------------------


def _worn(frame: pd.DataFrame, days: pd.DatetimeIndex) -> pd.Series:
    """True for each day worn long enough to count (no wear column: every day counts)."""
    if "wear_minutes" not in frame.columns:
        return pd.Series(True, index=days)
    wear = frame["wear_minutes"].reindex(days)
    return wear.isna() | (wear >= LOW_WEAR_MINUTES)


def detect(frame: pd.DataFrame, today: date) -> list[Evidence]:
    """The evidence for an alert, one record per signal that qualified; empty when the rule is
    not met. `frame` is the person's daily data with the app's scores (`with_scores`)."""
    if frame.empty:
        return []
    last = frame.index.max().date()
    if (today - last).days > FRESH_DAYS:
        return []
    recent = Window(start=last - timedelta(days=WINDOW_DAYS - 1), end=last)
    usual = Window(
        start=recent.start - timedelta(days=BASELINE_DAYS), end=recent.start - timedelta(days=1)
    )
    days = pd.date_range(recent.start, recent.end)
    worn = _worn(frame, days)
    if int(worn.sum()) < MIN_WORN:
        return []
    found = []
    for metric, (direction, floor) in SIGNALS.items():
        if metric not in frame.columns:
            continue
        before = frame[metric].loc[pd.Timestamp(usual.start) : pd.Timestamp(usual.end)].dropna()
        if len(before) < MIN_BASELINE:
            continue
        low, high = float(before.quantile(0.25)), float(before.quantile(0.75))
        margin = max(FAR * (high - low), floor)
        values = frame[metric].reindex(days)[worn]
        far = values <= low - margin if direction == "down" else values >= high + margin
        days_far = int(far.sum())
        if days_far < DAYS_FAR:
            continue
        found.append(
            Evidence(
                tool="checkin_rule",
                metrics=(metric,),
                windows=(usual, recent),
                n=int(values.notna().sum()),
                sufficient=True,
                stats={
                    "rule": RULE,
                    "direction": direction,
                    "usual_low": round(low, 2),
                    "usual_high": round(high, 2),
                    "margin": round(margin, 2),
                    "days_far": days_far,
                    "days_worn": int(worn.sum()),
                    "recent_mean": round(float(values.mean()), 2),
                },
            )
        )
    return found if len(found) >= MIN_SIGNALS else []


# --- consent --------------------------------------------------------------------------------


def recipients_text(db: Session, team: Team) -> str:
    supervisor = db.get(User, team.supervisor_id)
    hr = db.get(User, team.hr_id) if team.hr_id else None
    named = [f"your supervisor ({supervisor.email})"] if supervisor else []
    if hr:
        named.append(f"HR ({hr.email})")
    return " and ".join(named) or "your supervisor"


def consent_text(db: Session, team: Team) -> str:
    return CONSENT_TEXT.format(recipients=recipients_text(db, team))


def set_consent(
    db: Session, membership: TeamMembership, team: Team, on: bool, now: datetime
) -> TeamMembership:
    """Turns check-in alerts on or off; off withdraws every alert still waiting."""
    if membership.checkin_alerts == on:
        return membership
    membership.checkin_alerts = on
    membership.checkin_changed_at = now
    if on:
        membership.checkin_consent_version = CONSENT_VERSION
        return membership
    waiting = db.scalars(
        select(CheckinAlert).where(
            CheckinAlert.team_id == team.id,
            CheckinAlert.user_id == membership.user_id,
            CheckinAlert.status == "waiting",
        )
    )
    for alert in waiting:
        _withdraw(db, alert, membership.user_id, now)
    return membership


def _withdraw(db: Session, alert: CheckinAlert, actor: uuid.UUID | None, now: datetime) -> None:
    alert.status = "withdrawn"
    alert.withdrawn_at = now
    _log(db, alert, actor, "withdrawn", now)


def _log(
    db: Session, alert: CheckinAlert, actor: uuid.UUID | None, event: str, now: datetime
) -> None:
    db.add(CheckinEvent(alert_id=alert.id, actor_id=actor, event=event, created_at=now))


def _notify(db: Session, user_id: uuid.UUID, title: str, body: str, link: str, now: datetime):
    db.add(
        Notification(
            user_id=user_id,
            kind="checkin",
            title=title[:80],
            body=body[:400],
            link=link,
            created_at=now,
        )
    )


# --- raising, sending, reminding ------------------------------------------------------------


def _recent_alert(db: Session, team: Team, user_id: uuid.UUID, now: datetime) -> bool:
    return (
        db.scalar(
            select(CheckinAlert.id).where(
                CheckinAlert.team_id == team.id,
                CheckinAlert.user_id == user_id,
                CheckinAlert.raised_at > now - COOLDOWN,
            )
        )
        is not None
    )


def raise_for_team(db: Session, team: Team, now: datetime) -> int:
    """Checks every consenting member of the team; returns how many alerts were raised."""
    members = db.scalars(
        select(TeamMembership).where(
            TeamMembership.team_id == team.id,
            TeamMembership.left_at.is_(None),
            TeamMembership.checkin_alerts.is_(True),
        )
    ).all()
    raised = 0
    today = now.date()
    start = today - timedelta(days=WINDOW_DAYS + BASELINE_DAYS + FRESH_DAYS)
    for membership in members:
        if _recent_alert(db, team, membership.user_id, now):
            continue
        frame = load_daily(db, membership.user_id, SOURCE, start, today + timedelta(days=1))
        if frame.empty:
            continue
        evidence = detect(with_scores(frame), today)
        if not evidence:
            continue
        alert = CheckinAlert(
            team_id=team.id,
            user_id=membership.user_id,
            rule=RULE,
            last_day=evidence[0].windows[1].end,
            evidence=[e.model_dump(mode="json") for e in evidence],
            status="waiting",
            raised_at=now,
            send_after=now + WAIT,
        )
        db.add(alert)
        db.flush()
        _log(db, alert, None, "raised", now)
        _notify(
            db,
            membership.user_id,
            PERSON_TITLE,
            PERSON_BODY.format(recipients=recipients_text(db, team)),
            f"/checkin/{alert.id}",
            now,
        )
        raised += 1
    return raised


def _recipients(team: Team) -> list[tuple[uuid.UUID, str]]:
    found = [(team.supervisor_id, "supervisor")]
    if team.hr_id and team.hr_id != team.supervisor_id:
        found.append((team.hr_id, "hr"))
    return found


def send_due(db: Session, now: datetime) -> int:
    """Sends every alert whose wait is over, if the person still agrees; returns how many."""
    sent = 0
    due = db.scalars(
        select(CheckinAlert).where(CheckinAlert.status == "waiting", CheckinAlert.send_after <= now)
    ).all()
    for alert in due:
        team = db.get(Team, alert.team_id)
        membership = db.scalar(
            select(TeamMembership).where(
                TeamMembership.team_id == alert.team_id,
                TeamMembership.user_id == alert.user_id,
                TeamMembership.left_at.is_(None),
            )
        )
        if team is None or membership is None or not membership.checkin_alerts:
            _withdraw(db, alert, None, now)  # left the team or turned it off: nothing goes
            continue
        person = db.get(User, alert.user_id)
        alert.status = "sent"
        alert.sent_at = now
        _log(db, alert, None, "sent", now)
        for user_id, role in _recipients(team):
            db.add(CheckinMark(alert_id=alert.id, user_id=user_id, role=role))
            _notify(
                db,
                user_id,
                RECIPIENT_TITLE.format(person=person.email),
                RECIPIENT_BODY.format(person=person.email, team=team.name),
                f"/checkins/{alert.id}",
                now,
            )
        sent += 1
    return sent


def remind_due(db: Session, now: datetime) -> int:
    """Shows an alert nobody has marked after REMIND_AFTER once more to its recipients."""
    reminded = 0
    stale = db.scalars(
        select(CheckinAlert).where(
            CheckinAlert.status == "sent",
            CheckinAlert.reminded_at.is_(None),
            CheckinAlert.sent_at <= now - REMIND_AFTER,
        )
    ).all()
    for alert in stale:
        marks = db.scalars(select(CheckinMark).where(CheckinMark.alert_id == alert.id)).all()
        if any(mark.outcome for mark in marks):
            continue
        person = db.get(User, alert.user_id)
        team = db.get(Team, alert.team_id)
        for mark in marks:
            _notify(
                db,
                mark.user_id,
                RECIPIENT_TITLE.format(person=person.email),
                "Still open: " + RECIPIENT_BODY.format(person=person.email, team=team.name),
                f"/checkins/{alert.id}",
                now,
            )
        alert.reminded_at = now
        _log(db, alert, None, "reminded", now)
        reminded += 1
    return reminded


_last_raise: date | None = None


def run_due(sessions: Sessions, now: datetime) -> Counter:
    """From the background loop: raise once a day after the syncs, send and remind every pass.
    One team failing stops no other."""
    global _last_raise
    counts: Counter = Counter()
    if now.hour >= FIRST_HOUR_UTC and _last_raise != now.date():
        _last_raise = now.date()
        with sessions() as db:
            teams = list(db.scalars(select(Team.id)))
        for team_id in teams:
            try:
                with sessions() as db:
                    counts["raised"] += raise_for_team(db, db.get(Team, team_id), now)
            except Exception:
                logger.exception("Checking one team for check-in alerts failed")
                counts["errors"] += 1
    with sessions() as db:
        counts["sent"] += send_due(db, now)
        counts["reminded"] += remind_due(db, now)
    return +counts


# --- what each person may see and do ---------------------------------------------------------


@dataclass(frozen=True)
class Mark:
    role: str
    outcome: str | None
    marked_at: datetime | None


@dataclass(frozen=True)
class Received:
    """A sent alert as a recipient sees it: who, which team, when; never why."""

    id: uuid.UUID
    person: str
    team: str
    sent_at: datetime
    mine: Mark
    others: list[Mark]
    note: str | None


def _team_roles(db: Session, user: User) -> dict[uuid.UUID, str]:
    roles = {
        team.id: "supervisor"
        for team in db.scalars(select(Team).where(Team.supervisor_id == user.id))
    }
    for team in db.scalars(select(Team).where(Team.hr_id == user.id)):
        roles.setdefault(team.id, "hr")
    return roles


def received(db: Session, user: User) -> list[Received]:
    """The sent alerts this person is a recipient of, newest first."""
    rows = db.execute(
        select(CheckinMark, CheckinAlert, Team, User)
        .join(CheckinAlert, CheckinAlert.id == CheckinMark.alert_id)
        .join(Team, Team.id == CheckinAlert.team_id)
        .join(User, User.id == CheckinAlert.user_id)
        .where(CheckinMark.user_id == user.id, CheckinAlert.status == "sent")
        .order_by(CheckinAlert.sent_at.desc())
    ).all()
    out = []
    for mark, alert, team, person in rows:
        others = db.scalars(
            select(CheckinMark).where(
                CheckinMark.alert_id == alert.id, CheckinMark.user_id != user.id
            )
        )
        out.append(
            Received(
                id=alert.id,
                person=person.email,
                team=team.name,
                sent_at=alert.sent_at,
                mine=Mark(mark.role, mark.outcome, mark.marked_at),
                others=[Mark(o.role, o.outcome, o.marked_at) for o in others],
                note=mark.note,
            )
        )
    return out


def _my_mark(db: Session, user: User, alert_id: str) -> tuple[CheckinMark, CheckinAlert]:
    try:
        key = uuid.UUID(alert_id)
    except ValueError:
        raise ApiError(404, "not_found", "No such check-in alert.") from None
    row = db.execute(
        select(CheckinMark, CheckinAlert)
        .join(CheckinAlert, CheckinAlert.id == CheckinMark.alert_id)
        .where(
            CheckinMark.alert_id == key,
            CheckinMark.user_id == user.id,
            CheckinAlert.status == "sent",
        )
    ).first()
    if row is None:  # someone else's alert looks like one that does not exist
        raise ApiError(404, "not_found", "No such check-in alert.")
    return row[0], row[1]


def open_alert(db: Session, user: User, alert_id: str, now: datetime) -> Received:
    mark, alert = _my_mark(db, user, alert_id)
    if mark.opened_at is None:
        mark.opened_at = now
        _log(db, alert, user.id, "opened", now)
    return next(r for r in received(db, user) if r.id == alert.id)


def mark_alert(
    db: Session, user: User, alert_id: str, outcome: str, note: str | None, now: datetime
) -> Received:
    mark, alert = _my_mark(db, user, alert_id)
    mark.opened_at = mark.opened_at or now
    mark.outcome = outcome
    mark.note = (note or "").strip()[:500] or None
    mark.marked_at = now
    _log(db, alert, user.id, "marked", now)
    db.flush()
    return next(r for r in received(db, user) if r.id == alert.id)


def own_alerts(db: Session, user: User) -> list[tuple[CheckinAlert, Team]]:
    """The person's own alerts with their evidence, newest first."""
    rows = db.execute(
        select(CheckinAlert, Team)
        .join(Team, Team.id == CheckinAlert.team_id)
        .where(CheckinAlert.user_id == user.id)
        .order_by(CheckinAlert.raised_at.desc())
    ).all()
    return [tuple(row) for row in rows]


def is_recipient(db: Session, user: User) -> bool:
    return bool(_team_roles(db, user))
