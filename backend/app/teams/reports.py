"""A team's weekly report: the team statistics and a text built only from them.

The text is templated here: every number in it is read from the evidence it cites. A language
model may later write a narrative over the same evidence, checked against it; this text stays as
the fallback. Reports hold aggregates only. Named levels are read when a report is opened, for
members sharing them at that moment, and are never stored.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.llm import LLM
from app.analysis.evidence import Evidence, Window
from app.analysis.report import change_text
from app.analysis.team import (
    LEVEL_METRICS,
    MIN_MEMBERS,
    Level,
    TeamStatistics,
    member_levels,
    team_info,
    team_statistics,
    week_of,
)
from app.db.daily import load_daily
from app.db.models import Team, TeamMembership, TeamReport, User
from app.teams.memberships import active_members

SOURCE = "google_health"  # team reports read each member's live data only
HISTORY_DAYS = 70  # enough before the week for the scores' baselines and four earlier weeks


def last_full_week(today: date) -> Window:
    """The Monday-to-Sunday week before the one containing `today`."""
    return week_of(today - timedelta(days=7))


def _section(evidence: Evidence, changed: bool) -> dict:
    metric = evidence.metrics[0]
    label = team_info(metric).label
    base = {"metric": metric, "label": label, "evidence_id": evidence.id}
    if not evidence.sufficient:
        members = evidence.stats["members"]
        return {
            **base,
            "status": "not_enough_data",
            "text": f"{label}: not enough data ({members} of the {MIN_MEMBERS} people needed).",
        }
    stats = evidence.stats
    median = change_text(metric, stats["median_change"])
    who = f"{stats['members_up']} of {stats['members']} higher, {stats['members_down']} lower"
    if changed:
        direction = _direction(metric, stats["median_change"])
        text = f"{label} {direction} across the team: median change {median} ({who})."
        return {**base, "status": "changed", "text": text}
    text = f"{label}: no clear change for the team (median {median}; {who})."
    return {**base, "status": "steady", "text": text}


def _direction(metric: str, median_change: float) -> str:
    if metric == "bedtime_hour":
        return "moved later" if median_change > 0 else "moved earlier"
    return "rose" if median_change > 0 else "fell"


def _weekday(evidence: Evidence) -> dict | None:
    medians = evidence.stats["median_deviation_by_weekday"]
    if not evidence.sufficient:
        return None
    metric = evidence.metrics[0]
    high = max(medians, key=medians.get)
    low = min(medians, key=medians.get)
    return {
        "metric": metric,
        "evidence_id": evidence.id,
        "text": (
            f"{team_info(metric).label} by weekday: highest on {high.capitalize()}s "
            f"({change_text(metric, medians[high])} against each person's usual), lowest on "
            f"{low.capitalize()}s ({change_text(metric, medians[low])})."
        ),
    }


def template(statistics: TeamStatistics) -> tuple[str, dict]:
    """The headline and body of a report, every figure read from the evidence it cites."""
    changed_ids = {e.id for e in statistics.changed}
    sections = [_section(e, e.id in changed_ids) for e in statistics.changes]
    weekdays = [w for e in statistics.weekdays if (w := _weekday(e))]
    changed = [
        f"{team_info(e.metrics[0]).label.lower()} "
        f"{_direction(e.metrics[0], e.stats['median_change'])}"
        for e in statistics.changed
    ]
    if changed:
        listed = ", ".join(changed[:-1]) + (" and " if len(changed) > 1 else "") + changed[-1]
        headline = f"This week the team's {listed} against the four weeks before"
        steady = any(s["status"] == "steady" for s in sections)
        headline += "; the rest held steady." if steady else "."
    else:
        headline = "No clear team-wide change this week against the four weeks before."
    return headline, {"sections": sections, "weekdays": weekdays}


def _member_frames(db: Session, team: Team, week: Window) -> list:
    users = db.scalars(
        select(TeamMembership.user_id).where(
            TeamMembership.team_id == team.id, TeamMembership.left_at.is_(None)
        )
    ).all()
    start = week.start - timedelta(days=HISTORY_DAYS)
    end = week.end + timedelta(days=1)
    frames = [load_daily(db, user_id, SOURCE, start, end) for user_id in users]
    return [frame for frame in frames if not frame.empty]


def build_report(
    db: Session,
    team: Team,
    week: Window,
    now: datetime,
    writer: LLM | None = None,
    cap_usd: float = 0.02,
) -> TeamReport:
    """Makes and stores the team's report for `week`, or returns the one already made.

    With a `writer`, a model writes the prose over the same evidence (`narrative.py`); when it
    fails or its text does not check out, the templated text stands alone."""
    found = db.scalar(
        select(TeamReport).where(TeamReport.team_id == team.id, TeamReport.week_start == week.start)
    )
    if found is not None:
        return found
    total = active_members(db, team)
    frames = _member_frames(db, team, week)
    statistics = team_statistics(frames, week)
    if not statistics.changes:
        report = TeamReport(
            team_id=team.id,
            week_start=week.start,
            status="withheld",
            members_total=total,
            members_included=len(frames),
            headline=(
                f"No report this week: {len(frames)} of the {MIN_MEMBERS} people needed had data."
            ),
            body={"sections": [], "weekdays": []},
            evidence={},
            created_at=now,
        )
    else:
        headline, body = template(statistics)
        generated_by, cost = "template", 0.0
        if writer is not None:
            from app.teams.narrative import narrate  # it imports the report's text helpers

            attempt = narrate(writer, statistics, cap_usd)
            cost = attempt.cost_usd
            if attempt.narrated:
                headline, generated_by = attempt.narrated.headline, "model"
                body["narrative"] = attempt.narrated.paragraphs
            else:
                body["narrative_problems"] = attempt.problems[:10]
        evidence = {
            e.id: e.model_dump(mode="json") for e in [*statistics.changes, *statistics.weekdays]
        }
        report = TeamReport(
            team_id=team.id,
            week_start=week.start,
            status="ready",
            members_total=total,
            members_included=len(frames),
            headline=headline,
            body=body,
            evidence=evidence,
            generated_by=generated_by,
            cost_usd=cost,
            created_at=now,
        )
    db.add(report)
    db.flush()
    return report


def shared_levels(db: Session, team: Team, week: Window) -> list[tuple[str, dict]]:
    """Each member sharing their levels now, by email, alphabetically; computed, never stored."""
    rows = db.execute(
        select(User.id, User.email)
        .join(TeamMembership, TeamMembership.user_id == User.id)
        .where(
            TeamMembership.team_id == team.id,
            TeamMembership.left_at.is_(None),
            TeamMembership.share_levels.is_(True),
        )
        .order_by(User.email)
    ).all()
    start = week.start - timedelta(days=HISTORY_DAYS)
    end = week.end + timedelta(days=1)
    levels = []
    for user_id, email in rows:
        frame = load_daily(db, user_id, SOURCE, start, end)
        if frame.empty:  # no live data: nothing to show, not an error
            levels.append((email, {m: Level(None, None) for m in LEVEL_METRICS}))
        else:
            levels.append((email, member_levels(frame, week)))
    return levels
