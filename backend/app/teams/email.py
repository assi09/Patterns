"""The weekly team report by email (docs/teams.md): aggregates only, and a link to the app.

An email is easily forwarded and kept, so it holds less than the app: the headline, the counts,
and how many people went each way on each metric. Named weekly levels never go in an email, even
for people who share them; they stay behind the supervisor's sign-in.

Sending itself is shared with reminders, in `app/email.py`.
"""

import html
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.analysis.report import change_text
from app.db.models import Team, TeamReport, User
from app.email import (  # noqa: F401  (re-exported for the CLI and tests)
    RESEND_URL,
    Email,
    Mailer,
    MailError,
    OutboxMailer,
    ResendMailer,
    mailer_from_settings,
)

# The app's light-theme metric colors (mobile/src/theme.ts), for the bars of changed metrics.
COLORS = {
    "sleep_minutes": "#4F6BD8",
    "bedtime_hour": "#4F6BD8",
    "steps": "#D9531F",
    "active_zone_minutes": "#D9531F",
    "strain": "#D9531F",
    "resting_hr": "#D63A5A",
    "hrv_ms": "#D63A5A",
    "recovery_score": "#4E9A3A",
    "stress_score": "#7C4DCC",
}
STEADY = "#A0958A"
TRACK = "#EFE7DC"
INK, MUTED = "#1F1A16", "#6F655C"


def _week(report: TeamReport) -> str:
    start = report.week_start
    end = start.fromordinal(start.toordinal() + 6)
    return f"{start:%b} {start.day} – {end:%b} {end.day}"


@dataclass(frozen=True)
class _Line:
    metric: str
    label: str
    changed: bool
    up: int
    down: int
    members: int
    median: str


def _lines(report: TeamReport) -> list[_Line]:
    lines = []
    for section in report.body.get("sections", []):
        if section["status"] not in ("changed", "steady"):
            continue
        stats = report.evidence[section["evidence_id"]]["stats"]
        lines.append(
            _Line(
                metric=section["metric"],
                label=section["label"],
                changed=section["status"] == "changed",
                up=stats["members_up"],
                down=stats["members_down"],
                members=stats["members"],
                median=change_text(section["metric"], stats["median_change"]),
            )
        )
    return sorted(lines, key=lambda line: not line.changed)


def _html_briefing(text: str) -> str:
    return (
        f'<p style="margin:0 0 4px;font-size:12px;color:{MUTED}">From your team agent</p>'
        f'<p style="margin:0 0 16px;font-size:15px;line-height:22px">{html.escape(text)}</p>'
    )


def compose(team: Team, report: TeamReport, to: str, app_url: str) -> Email:
    """The email for one stored report, every figure read from its stored evidence."""
    week = _week(report)
    link = f"{app_url.rstrip('/')}/team"
    subject = f"{team.name}: week of {week}"
    lines = _lines(report) if report.status == "ready" else []
    changed = [line for line in lines if line.changed]
    counts = (
        f"{report.members_included} people with data · {len(changed)} of {len(lines)} metrics "
        "changed"
    )

    briefing = (report.body or {}).get("briefing", {}).get("summary")
    text = [f"{team.name}, week of {week}", "", report.headline, ""]
    if briefing:
        text += ["From your team agent:", briefing, ""]
    if lines:
        text += [counts, ""]
        for line in lines:
            mark = "*" if line.changed else "-"
            text.append(
                f"{mark} {line.label}: median {line.median} "
                f"({line.down} lower, {line.up} higher of {line.members})"
            )
        text.append("")
    text += [
        f"The full report, with weekday patterns: {link}",
        "",
        "Each person is compared with their own four weeks before; only the team's counts and "
        "medians are reported, never anyone's own data. Patterns, not advice.",
    ]

    rows = "".join(_html_row(line) for line in lines)
    body = f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#F7F2EA;font-family:-apple-system,Segoe UI,\
Helvetica,Arial,sans-serif;color:{INK}">
<table role="presentation" width="100%" style="max-width:560px;margin:0 auto;background:#FFFFFF;\
border-radius:12px;padding:24px" cellpadding="0" cellspacing="0"><tr><td>
<p style="margin:0 0 4px;font-size:12px;letter-spacing:.6px;text-transform:uppercase;\
color:{MUTED}">{html.escape(team.name)} · week of {week}</p>
<h1 style="margin:0 0 16px;font-size:20px;line-height:26px">{html.escape(report.headline)}</h1>
{_html_briefing(briefing) if briefing else ""}
{f'<p style="margin:0 0 16px;color:{MUTED};font-size:14px">{counts}</p>' if lines else ""}
{_html_table(rows) if rows else ""}
<p style="margin:20px 0"><a href="{html.escape(link)}" style="display:inline-block;\
background:{INK};color:#FFFFFF;text-decoration:none;padding:10px 18px;border-radius:999px;\
font-size:14px">Open the full report</a></p>
<p style="margin:0;color:{MUTED};font-size:12px;line-height:17px">Each person is compared with \
their own four weeks before; only the team's counts and medians are reported, never anyone's own \
data. Patterns, not advice.</p>
</td></tr></table></body></html>"""
    return Email(to=to, subject=subject, text="\n".join(text), html=body)


def _html_table(rows: str) -> str:
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        f'<tr><td style="font-size:12px;color:{MUTED};padding-bottom:8px">&larr; People lower</td>'
        f'<td style="font-size:12px;color:{MUTED};padding-bottom:8px;text-align:right">'
        "People higher &rarr;</td></tr>"
        f"{rows}</table>"
    )


def _html_row(line: _Line) -> str:
    """A metric's diverging bar in table cells, which email clients draw reliably."""
    color = COLORS.get(line.metric, INK) if line.changed else STEADY
    weight = "600" if line.changed else "400"
    ink = INK if line.changed else MUTED
    down = round(100 * line.down / line.members) if line.members else 0
    up = round(100 * line.up / line.members) if line.members else 0
    return (
        f'<tr><td style="padding-top:12px;font-size:14px;font-weight:{weight};color:{ink}">'
        f"{html.escape(line.label)}</td>"
        f'<td style="padding-top:12px;font-size:14px;font-weight:{weight};color:{ink};'
        f'text-align:right">{html.escape(line.median)} '
        f'<span style="font-size:12px;color:{MUTED};font-weight:400">median</span></td></tr>'
        '<tr><td colspan="2" style="padding:6px 0 2px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td width="50%" style="background:{TRACK};height:8px;line-height:8px;font-size:0">'
        f'<div style="float:right;width:{down}%;height:8px;background:{color}"></div></td>'
        f'<td width="2" style="width:2px;min-width:2px;background:{MUTED};font-size:0">'
        "&nbsp;</td>"
        f'<td width="50%" style="background:{TRACK};height:8px;line-height:8px;font-size:0">'
        f'<div style="width:{up}%;height:8px;background:{color}"></div></td>'
        "</tr></table></td></tr>"
        f'<tr><td style="font-size:12px;color:{MUTED}">{line.down} lower</td>'
        f'<td style="font-size:12px;color:{MUTED};text-align:right">{line.up} higher</td></tr>'
    )


def deliver(
    db: Session, team: Team, report: TeamReport, mailer: Mailer, app_url: str, now: datetime
) -> bool:
    """Emails a report to the team's report address, or its supervisor; once per report."""
    if report.emailed_at is not None:
        return False
    to = team.report_email or db.get(User, team.supervisor_id).email
    mailer.send(compose(team, report, to, app_url))
    report.emailed_at = now
    db.flush()
    return True
