"""Tell a supervisor when a team's aggregate changes, without waiting for Monday's report.

Once a day, after the morning's syncs, each team is checked over the last seven full days. Code does
all of it: no model sees or writes anything, so an alert cannot name or guess at a person. An alert
holds team figures from at least five people, and is raised once: a change that stays is not sent
again, and the same change cannot return within COOLDOWN of ending.
"""

import html
import logging
from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alarms.run import Sessions
from app.analysis.evidence import Evidence, Window
from app.analysis.report import change_text
from app.analysis.team import AREA_OF, team_alerts, team_info
from app.db.models import Notification, Team, TeamAlert, TeamNote, User
from app.email import Email, Mailer, MailError
from app.reminders import store
from app.reminders.schedule import zone
from app.teams.reports import _direction, _member_frames

logger = logging.getLogger(__name__)

COOLDOWN = timedelta(days=14)
FIRST_HOUR_UTC = 6  # after the morning's syncs, as the weekly report
LINK = "/team"
NOTE = "Team figures from everyone with data. It describes a pattern, not any one person."
NOTES_BEFORE = timedelta(days=7)  # a deadline the week before a change can line up with it
SENT_AT_ONCE = ("concern", "change")  # good news waits for the weekly report and the Team tab


def alert_text(evidence: Evidence) -> str:
    metric, stats = evidence.metrics[0], evidence.stats
    who = stats["members_up"] if stats["direction"] == "up" else stats["members_down"]
    return (
        f"{team_info(metric).label} {_direction(metric, stats['median_change'])} across the team "
        f"over the past week: median change {change_text(metric, stats['median_change'])} "
        f"({who} of {stats['members']} people)."
    )


def lined_up(db: Session, team: Team, window: Window) -> str:
    """The supervisor's notes whose dates fall in the change's week or the week before it."""
    start, end = window.start - NOTES_BEFORE, window.end
    notes = [
        note
        for note in db.scalars(select(TeamNote).where(TeamNote.team_id == team.id))
        if note.starts_on is not None
        and note.starts_on <= end
        and (note.ends_on or note.starts_on) >= start
    ]
    if not notes:
        return ""
    said = "; ".join(f"{n.text[:80]} ({n.starts_on:%b %-d})" for n in notes[:2])
    return f" It lined up with your note: {said}."


def check_team(
    db: Session, team: Team, end: date, now: datetime, ended: list[TeamAlert] | None = None
) -> list[TeamAlert]:
    """Raises what is new and closes what has ended; returns the new alerts, and adds the ones
    that ended to `ended` when given."""
    window = Window(start=end - timedelta(days=6), end=end)
    found = team_alerts(_member_frames(db, team, window), end)
    alerts = list(db.scalars(select(TeamAlert).where(TeamAlert.team_id == team.id)))
    for alert in alerts:
        if alert.resolved_at is None and (alert.metric, alert.direction) not in found.still_moving:
            alert.resolved_at = now
            if ended is not None:
                ended.append(alert)

    def blocked(metric: str, direction: str) -> bool:
        return any(
            a.metric == metric
            and a.direction == direction
            and (a.resolved_at is None or now - store.utc(a.resolved_at) < COOLDOWN)
            for a in alerts
        )

    new = []
    for evidence in found.raised:
        metric, direction = evidence.metrics[0], evidence.stats["direction"]
        if blocked(metric, direction):
            continue
        alert = TeamAlert(
            team_id=team.id,
            metric=metric,
            direction=direction,
            kind=evidence.stats.get("kind", "change"),
            text=(alert_text(evidence) + lined_up(db, team, evidence.windows[0]))[:400],
            evidence=evidence.model_dump(mode="json"),
            raised_at=now,
        )
        db.add(alert)
        new.append(alert)
    db.flush()
    return new


def compose(team: Team, alerts: list[TeamAlert], to: str, app_url: str) -> Email:
    subject = _title(team, alerts)
    url = f"{app_url.rstrip('/')}{LINK}"
    lines = "\n".join(f"- {a.text}" for a in alerts)
    items = "".join(f'<li style="margin:0 0 8px">{html.escape(a.text)}</li>' for a in alerts)
    page = (
        '<div style="font-family:-apple-system,Segoe UI,sans-serif;color:#1F1A16;'
        'max-width:480px;line-height:1.5">'
        f'<p style="font-size:17px;margin:0 0 8px"><strong>{html.escape(subject)}</strong></p>'
        f'<ul style="font-size:15px;margin:0 0 16px;padding-left:18px">{items}</ul>'
        f'<p style="font-size:13px;color:#6F655C;margin:0">{NOTE} '
        f'<a href="{html.escape(url)}" style="color:#6F655C">Open the team</a>.</p></div>'
    )
    return Email(to=to, subject=subject, text=f"{lines}\n\n{NOTE}\n{url}\n", html=page)


def _title(team: Team, alerts: list[TeamAlert]) -> str:
    areas = {AREA_OF.get(a.metric) for a in alerts if a.kind == "concern"}
    if {"sleep", "recovery"} <= areas:  # moving together: one story, not several
        return f"{team.name}: sleep and recovery moved together"[:80]
    if len(alerts) == 1:
        return f"{team.name}: {team_info(alerts[0].metric).label.lower()} changed"[:80]
    return f"{team.name}: {len(alerts)} changes across the team"[:80]


def deliver(
    db: Session,
    team: Team,
    alerts: list[TeamAlert],
    now: datetime,
    mailer: Mailer,
    app_url: str,
    ended: list[TeamAlert] = (),
) -> None:
    """Concerns and changes now, in the inbox and by email; good news only on the Team tab and in
    the weekly report; a concern that ended, as a quiet line in the inbox."""
    supervisor = db.get(User, team.supervisor_id)
    if supervisor is None:
        return
    over = [a for a in ended if a.kind == "concern"]
    if over:
        names = ", ".join(team_info(a.metric).label.lower() for a in over)
        db.add(
            Notification(
                user_id=supervisor.id,
                kind="team_alert",
                title=f"{team.name}: back to usual"[:80],
                body=f"The team's {names} {'is' if len(over) == 1 else 'are'} back to usual."[:400],
                link=LINK,
                created_at=now,
            )
        )
    alerts = [a for a in alerts if a.kind in SENT_AT_ONCE]
    if not alerts:
        db.flush()
        return
    db.add(
        Notification(
            user_id=supervisor.id,
            kind="team_alert",
            title=_title(team, alerts),
            body=" ".join(a.text for a in alerts)[:400],
            link=LINK,
            created_at=now,
        )
    )
    if store.notification_settings(db, supervisor.id).email:
        try:
            mailer.send(compose(team, alerts, team.report_email or supervisor.email, app_url))
        except MailError as error:
            logger.warning("A team alert email failed: %s", str(error)[:200])
    db.flush()


def _yesterday(db: Session, team: Team, now: datetime) -> date:
    """The last full day where the supervisor is: members' today is still being recorded."""
    supervisor = db.get(User, team.supervisor_id)
    return now.astimezone(zone(store.timezone_of(supervisor))).date() - timedelta(days=1)


_last_run: date | None = None


def run_due(sessions: Sessions, now: datetime, mailer: Mailer, app_url: str) -> Counter:
    """Once a day. A restart raises nothing twice, and one team failing stops no other."""
    global _last_run
    counts: Counter = Counter()
    if now.hour < FIRST_HOUR_UTC or _last_run == now.date():
        return counts
    _last_run = now.date()
    with sessions() as db:
        teams = list(db.scalars(select(Team.id)))
    for team_id in teams:
        try:
            with sessions() as db:
                team = db.get(Team, team_id)
                ended: list[TeamAlert] = []
                new = check_team(db, team, _yesterday(db, team, now), now, ended)
                if new or ended:
                    deliver(db, team, new, now, mailer, app_url, ended)
                counts["alerts"] += len(new)
        except Exception:
            logger.exception("Checking one team for alerts failed")
            counts["errors"] += 1
    return counts
