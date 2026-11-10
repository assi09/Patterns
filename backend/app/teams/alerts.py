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
from app.analysis.team import team_alerts, team_info
from app.db.models import Notification, Team, TeamAlert, User
from app.email import Email, Mailer, MailError
from app.reminders import store
from app.reminders.schedule import zone
from app.teams.reports import _direction, _member_frames

logger = logging.getLogger(__name__)

COOLDOWN = timedelta(days=14)
FIRST_HOUR_UTC = 6  # after the morning's syncs, as the weekly report
LINK = "/team"
NOTE = "Team figures from everyone with data. It describes a pattern, not any one person."


def alert_text(evidence: Evidence) -> str:
    metric, stats = evidence.metrics[0], evidence.stats
    who = stats["members_up"] if stats["direction"] == "up" else stats["members_down"]
    return (
        f"{team_info(metric).label} {_direction(metric, stats['median_change'])} across the team "
        f"over the past week: median change {change_text(metric, stats['median_change'])} "
        f"({who} of {stats['members']} people)."
    )


def check_team(db: Session, team: Team, end: date, now: datetime) -> list[TeamAlert]:
    """Raises what is new and closes what has ended; returns the new alerts."""
    window = Window(start=end - timedelta(days=6), end=end)
    found = team_alerts(_member_frames(db, team, window), end)
    alerts = list(db.scalars(select(TeamAlert).where(TeamAlert.team_id == team.id)))
    for alert in alerts:
        if alert.resolved_at is None and (alert.metric, alert.direction) not in found.still_moving:
            alert.resolved_at = now

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
            text=alert_text(evidence)[:300],
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
    if len(alerts) == 1:
        return f"{team.name}: {team_info(alerts[0].metric).label.lower()} changed"[:80]
    return f"{team.name}: {len(alerts)} changes across the team"[:80]


def deliver(
    db: Session, team: Team, alerts: list[TeamAlert], now: datetime, mailer: Mailer, app_url: str
) -> None:
    supervisor = db.get(User, team.supervisor_id)
    if supervisor is None:
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
                new = check_team(db, team, _yesterday(db, team, now), now)
                if new:
                    deliver(db, team, new, now, mailer, app_url)
                counts["alerts"] += len(new)
        except Exception:
            logger.exception("Checking one team for alerts failed")
            counts["errors"] += 1
    return counts
