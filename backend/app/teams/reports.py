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
from app.analysis.screen import FDR
from app.analysis.team import (
    LEVEL_METRICS,
    MIN_MEMBERS,
    Level,
    TeamStatistics,
    kind_of,
    member_levels,
    team_info,
    team_scan,
    team_statistics,
    week_of,
    worthwhile,
)
from app.db.daily import load_daily
from app.db.models import Team, TeamAction, TeamAlert, TeamMembership, TeamNote, TeamReport, User
from app.teams.memberships import active_members, overlap_problem

SOURCE = "google_health"  # team reports read each member's live data only
HISTORY_DAYS = 70  # enough before the week for the scores' baselines and four earlier weeks
NOTES_BEFORE = timedelta(days=7)  # a deadline the week before a change can line up with it
# The order a supervisor reads: what needs attention, what lasted before what is new, then load and
# bedtime (neither good nor bad), then good news.
KIND_ORDER = {"concern": 0, "change": 1, "improvement": 2}
STATUS_ORDER = {"lasting": 0, "new": 1}


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


def lined_up(db: Session, team: Team, window: Window) -> str:
    """The supervisor's notes whose dates fall in the change's span or the week before it."""
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


def priorities(db: Session, team: Team, scan) -> list[dict]:
    """What the week's report leads with: every lasting or new team change that is worth a
    supervisor's attention (the alerts' rule), concerns first, lasting before new, each with the
    note it lined up with. Code writes every sentence from the scan's figures."""
    found = []
    for evidence in scan.metrics:
        status, way = evidence.stats.get("status"), evidence.stats.get("direction")
        if status not in STATUS_ORDER or way is None:
            continue
        metric = evidence.metrics[0]
        latest = evidence.stats["weeks"][-1]
        if not worthwhile(metric, latest, way):
            continue
        running = evidence.stats["weeks_running"]
        label = team_info(metric).label
        moved = latest["members_up"] if way == "up" else latest["members_down"]
        figures = (
            f"median change {change_text(metric, latest['median_change'])} against the four "
            f"weeks before ({moved} of {latest['members']} people)"
        )
        if status == "lasting":
            word = "later" if metric == "bedtime_hour" else "higher" if way == "up" else "lower"
            text = f"{label} has been {word} for {running} weeks running: {figures}."
        else:
            text = f"{label} {_direction(metric, latest['median_change'])} this week: {figures}."
        span = Window(
            start=scan.weeks[-running].start if running else scan.weeks[-1].start,
            end=scan.weeks[-1].end,
        )
        kind = kind_of(metric, way)
        found.append(
            {
                "metric": metric,
                "label": label,
                "kind": kind,
                "status": status,
                "text": text + lined_up(db, team, span),
                "evidence_id": evidence.id,
            }
        )
    return sorted(found, key=lambda f: (KIND_ORDER[f["kind"]], STATUS_ORDER[f["status"]]))


def headline_from(found: list[dict]) -> str | None:
    if not found:
        return None
    first = found[0]
    lead = {"concern": "Needs attention", "change": "Worth knowing", "improvement": "Good news"}
    more = f" ({len(found) - 1} more below)" if len(found) > 1 else ""
    return f"{lead[first['kind']]}: {first['text'].split(':')[0]}{more}."


def week_alerts(db: Session, team: Team, week: Window) -> list[str]:
    """Alerts raised during the week, as the supervisor saw them."""
    return [
        a.text
        for a in db.scalars(
            select(TeamAlert).where(TeamAlert.team_id == team.id).order_by(TeamAlert.raised_at)
        )
        if week.start <= a.raised_at.date() <= week.end + timedelta(days=1)
    ]


def challenges(db: Session, team: Team, week: Window, frames: list) -> list[tuple[dict, Evidence]]:
    """Approved challenges that ended by the end of the week and not before the week before it:
    did the team's metric move during them? Read like a weekly change."""
    from app.teams.agent import challenge_result  # the agent imports this module

    done = []
    for action in db.scalars(select(TeamAction).where(TeamAction.team_id == team.id)):
        ends = action.ends_on
        if (
            action.kind != "challenge"
            or action.status != "approved"
            or not action.metric
            or ends is None
            or not (week.start - timedelta(days=7) <= ends <= week.end)
        ):
            continue
        evidence = challenge_result(frames, action)
        label = team_info(action.metric).label
        if not evidence.sufficient:
            text = f"{action.title}: not enough people with data to tell."
        elif evidence.stats["p_value"] < FDR:
            median = change_text(action.metric, evidence.stats["median_change"])
            way = _direction(action.metric, evidence.stats["median_change"])
            text = f"{action.title}: {label.lower()} {way} during it (median change {median})."
        else:
            text = f"{action.title}: no clear change in {label.lower()} during it."
        done.append(({"metric": action.metric, "text": text, "evidence_id": evidence.id}, evidence))
    return done


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
    if paused := overlap_problem(db, team):  # not stored: the week can be made once it is fixed
        return TeamReport(
            team_id=team.id,
            week_start=week.start,
            status="withheld",
            members_total=total,
            members_included=0,
            headline=f"No report this week. {paused}",
            body={"sections": [], "weekdays": []},
            evidence={},
            generated_by="template",
            cost_usd=0.0,
            created_at=now,
        )
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
        scan = team_scan(frames, week)
        found = priorities(db, team, scan)
        ended = challenges(db, team, week, frames)
        body |= {
            "priorities": found,
            "alerts": week_alerts(db, team, week),
            "challenges": [row for row, _ in ended],
        }
        headline = headline_from(found) or headline
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
        cited = [*statistics.changes, *statistics.weekdays, *scan.metrics, *(e for _, e in ended)]
        evidence = {e.id: e.model_dump(mode="json") for e in cited}
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
