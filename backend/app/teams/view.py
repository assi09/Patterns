"""One representation of a team's week for the supervisor's screen and for MCP (docs/mcp.md).

A claim means the same thing wherever it is read: the app's evidence screen and the MCP tools both
use these functions. Everything here is built from computed fields and fixed labels, never from a
stored sentence: a priority's sentence can carry a supervisor's note, and while the note screen
can still miss a named remark (#246), free text stays out. Records are bounded on the way out: a
team figure, its counts, its dates and its method; never a person's value, a quartile, a note or a
check-in.

Two comparisons appear in one report, and each is labelled with its own dates:
- a **priority** comes from the four-week team scan, against one fixed baseline (the 28 days before
  the first scanned week): a "Sustained change" when it held for weeks, a "New change" when only
  this week moved;
- a **weekly line** compares this week with the four weeks just before it.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.report import change_text
from app.analysis.team import BREADTH, MIN_MEMBERS, SUSTAINED_WEEKS, team_info, week_of
from app.db.models import Team, TeamAction, TeamActionMark, TeamReport
from app.teams import playbook

WEEKLY_LABEL = "This week vs. the previous four weeks"
PRIORITY_LABELS = {"lasting": "Sustained change", "new": "New change"}
LIMITS = (
    "Team aggregates from at least 5 people; no person's value is shown.",
    "Describes a change in readings; it does not establish a cause.",
    "People without enough data that week are not counted.",
)


class NotFound(LookupError):
    """Nothing of this team's matches; says no more than that."""


def _span(start: date, end: date) -> dict:
    return {"start": start.isoformat(), "end": end.isoformat()}


def _window(record: dict, at: int) -> dict | None:
    spans = record.get("windows") or []
    return dict(spans[at]) if len(spans) > at else None


def _unit(metric: str) -> str | None:
    unit = team_info(metric).unit
    return "min" if metric == "bedtime_hour" else (unit or None)


def _value(metric: str, raw: float) -> float:
    """In the unit the supervisor reads: bedtime is stored in hours and shown in minutes."""
    return round(raw * 60) if metric == "bedtime_hour" else round(raw, 1)


def _direction(metric: str, way: str | None) -> str | None:
    if way is None:
        return None
    if metric == "bedtime_hour":
        return "later" if way == "up" else "earlier"
    return "higher" if way == "up" else "lower"


def _change(metric: str, raw: float) -> dict:
    return {"value": _value(metric, raw), "unit": _unit(metric), "text": change_text(metric, raw)}


def week_report(
    db: Session, team: Team, week: date | None, made_by: date | None = None
) -> TeamReport | None:
    """The report of the week holding `week`, or the latest stored report when no week is asked;
    with `made_by`, only a report that existed by the end of that day. A week's report is made
    once and never replaced (`reports.build_report`), so the one stored is the version that was
    available from the day it was made."""
    query = select(TeamReport).where(TeamReport.team_id == team.id)
    if week is not None:
        query = query.where(TeamReport.week_start == week_of(week).start)
    found = [
        r
        for r in db.scalars(query.order_by(TeamReport.week_start.desc()))
        if made_by is None or r.created_at.date() <= made_by
    ]
    return found[0] if found else None


def _held(stats: dict) -> dict | None:
    """The weeks a scanned change held, up to the latest: from the first of its running weeks."""
    weeks = stats.get("weeks") or []
    running = stats.get("weeks_running") or 1
    if not weeks:
        return None
    first = weeks[-running] if len(weeks) >= running else weeks[0]
    return _span(date.fromisoformat(first["start"]), date.fromisoformat(weeks[-1]["end"]))


def _priority(report: TeamReport, row: dict) -> dict | None:
    record = (report.evidence or {}).get(row.get("evidence_id"))
    if not record or record.get("tool") != "team_scan":
        return None
    stats = record["stats"]
    metric = row["metric"]
    weeks = stats.get("weeks") or []
    latest = weeks[-1] if weeks else {}
    running = stats.get("weeks_running") or 1
    way = stats.get("direction")
    moved = latest.get("members_up" if way == "up" else "members_down")
    lasting = stats.get("status") == "lasting"
    why = (
        f"Changed the same way in {running} weeks running against the fixed baseline"
        if lasting
        else "Changed this week against the fixed baseline"
    ) + (
        f" (at least {SUSTAINED_WEEKS} weeks counts as sustained); large enough, and at least "
        f"{round(BREADTH * 100)}% of contributors moved that way."
    )
    return {
        "label": PRIORITY_LABELS.get(stats.get("status"), "New change"),
        "kind": row.get("kind"),
        "metric": metric,
        "metric_label": team_info(metric).label,
        "direction": _direction(metric, way),
        "change": _change(metric, latest.get("median_change", 0.0)),
        "target": _held(stats),
        "weeks_running": running,
        "baseline": _window(record, 1),
        "contributors": latest.get("members"),
        "moved_that_way": moved,
        "roster": report.members_total,
        "why": why,
        "evidence_id": record["id"],
    }


def _weekly(report: TeamReport) -> dict:
    week = week_of(report.week_start)
    changed, steady, withheld = [], [], []
    for section in (report.body or {}).get("sections", []):
        record = (report.evidence or {}).get(section.get("evidence_id")) or {}
        metric = section["metric"]
        stats = record.get("stats") or {}
        if not record.get("sufficient"):
            withheld.append(
                {
                    "metric": metric,
                    "metric_label": team_info(metric).label,
                    "contributors": stats.get("members", 0),
                    "minimum": MIN_MEMBERS,
                    "evidence_id": record.get("id"),
                }
            )
            continue
        line = {
            "metric": metric,
            "metric_label": team_info(metric).label,
            "change": _change(metric, stats["median_change"]),
            "contributors": stats["members"],
            "higher": stats["members_up"],
            "lower": stats["members_down"],
            "evidence_id": record["id"],
        }
        if section.get("status") == "changed":
            way = "up" if stats["median_change"] > 0 else "down"
            changed.append({**line, "direction": _direction(metric, way)})
        else:
            steady.append(line)
    reportable = len(changed) + len(steady)
    return {
        "label": WEEKLY_LABEL,
        "week": _span(week.start, week.end),
        "baseline": _span(week.start - timedelta(days=28), week.start - timedelta(days=1)),
        "summary": (
            f"{len(changed)} of {reportable} reportable metrics changed this week vs. the previous "
            f"four weeks; {len(withheld)} had fewer than {MIN_MEMBERS} people with data."
        ),
        "changed": changed,
        "steady": steady,
        "withheld_metrics": withheld,
    }


def _bounded_change(record: dict) -> dict | None:
    """A team_change record's figure, counts and test, with nothing per person."""
    if not record.get("sufficient"):
        return None
    stats = record["stats"]
    metric = record["metrics"][0]
    return {
        "change": _change(metric, stats["median_change"]),
        "higher": stats["members_up"],
        "lower": stats["members_down"],
        "p_value": stats.get("p_value"),
    }


def action_title(action: TeamAction) -> str:
    """A controlled label: the playbook's own title, or "Custom team change". A supervisor's own
    title is free text and can name someone (#246), so it never leaves through MCP."""
    play = playbook.PLAY.get(action.play or "")
    return play.title if play is not None and action.play != "custom" else "Custom team change"


def _stored_result(db: Session, team: Team, action: TeamAction, as_of: date):
    """The record a report stored for this change once it ended, from a report made by `as_of`:
    (report, record), or None when no report has covered it yet."""
    window = _span(action.starts_on, action.ends_on)
    for report in db.scalars(
        select(TeamReport)
        .where(TeamReport.team_id == team.id, TeamReport.week_start <= as_of - timedelta(days=7))
        .order_by(TeamReport.week_start)
    ):
        if report.created_at.date() > as_of:
            continue  # made later: on `as_of` this outcome did not exist yet
        for row in (report.body or {}).get("challenges", []):
            record = (report.evidence or {}).get(row.get("evidence_id")) or {}
            if row.get("metric") == action.metric and _window(record, 0) == window:
                return report, record
    return None


NO_OUTCOME_BY = (
    "No outcome was recorded by {day}: no weekly report had covered this change by then."
)


NO_CHECK_BY = "No calendar check was recorded by {day}."


def no_outcome(as_of: date) -> dict:
    """A past date's answer when no stored record existed by then: said, with no figure, rather
    than one measured today inside an answer about what was known then."""
    return {"outcome": None, "recorded": False, "note": NO_OUTCOME_BY.format(day=as_of)}


def _result(db: Session, team: Team, action: TeamAction, as_of: date, found: dict) -> dict:
    """What followed once the change ended (`app.teams.outcome`): the report's stored record when
    one covered it (so its evidence can be opened), otherwise measured now and marked so. A stored
    record keeps its own comparison dates; only the words describing it are new."""
    from app.teams import outcome

    stored = _stored_result(db, team, action, as_of)
    if stored is not None:
        report, record = stored
        source = {"report_id": str(report.id), "evidence_id": record["id"]}
    else:
        record = found["evidence"].model_dump(mode="json")
        source = {"measured_now": "no report has covered this change yet; no stored record"}
    described = outcome.describe(action, record)
    return {
        "measured": f"the team's median difference in {described['metric_label'].lower()} during "
        f"the change against {described['reference']['label']}",
        "outcome": described["outcome"],
        "label": described["label"],
        **source,
        "target": _window(record, 0),
        "reference": described["reference"],
        "contributors": described["contributors"],
        "minimum": described["minimum"],
        "figure": _bounded_change(record),
        "caveats": described["caveats"],
    }


STARTED_BY = {
    "supervisor": "supervisor",
    "assistant": "suggested in chat, recorded by an assistant",
    "agent": "suggested by Patterns",
}
IMPLEMENTATION_TEXT = {
    "tried": "reported tried by the supervisor",
    "not_tried": "reported not tried by the supervisor",
    None: "not reported: whether the team tried it is unknown",
}


def implementation(db: Session, action: TeamAction, as_of: date) -> str:
    """What the supervisor reported about trying it, as on record on `as_of`: the last answer
    given by the end of that day, so a later correction or undo leaves it as it was. Unanswered
    is unknown, never assumed tried because it was approved."""
    marks = db.scalars(
        select(TeamActionMark)
        .where(TeamActionMark.action_id == action.id)
        .order_by(TeamActionMark.marked_at)
    )
    known = None
    for mark in marks:
        if mark.marked_at.date() > as_of:
            break
        known = mark.implementation
    return IMPLEMENTATION_TEXT[known]


def follow_up(db: Session, team: Team, as_of: date, today: date | None = None) -> list[dict]:
    """Team changes as they stood on `as_of`: a result only for a change that had ended by then.
    For a past date (`as_of` before `today`), only what was stored by then: nothing is measured
    on today's data or membership, so a later sync cannot change what was known then. No calendar
    check is stored yet, so a past answer says none was recorded and gives no followed flag."""
    past = today is not None and as_of < today
    actions = db.scalars(
        select(TeamAction)
        .where(TeamAction.team_id == team.id, TeamAction.kind == "challenge")
        .order_by(TeamAction.proposed_at)
    ).all()
    if past:
        measured = {str(a.id) for a in playbook.ended(db, team, as_of)}
        results = {}
    else:
        results = playbook.results_of(db, team, as_of)
        measured = set()
    out = []
    for action in actions:
        decided = action.decided_at.date() if action.decided_at else None
        if action.proposed_at is not None and action.proposed_at.date() > as_of:
            continue  # not yet suggested or planned at that date
        if action.status == "proposed" or decided is None or decided > as_of:
            state = "proposed"
        elif action.status == "declined":
            state = "declined"
        elif action.starts_on and as_of < action.starts_on:
            state = "approved, not started"
        elif action.ends_on and as_of <= action.ends_on:
            state = "in_progress"
        else:
            state = "ended"
        item = {
            "title": action_title(action),
            "metric": action.metric,
            "metric_label": team_info(action.metric).label if action.metric else None,
            "started_by": STARTED_BY.get(action.source, "suggested by Patterns"),
            "state": state,
            "dates": _span(action.starts_on, action.ends_on)
            if action.starts_on and action.ends_on
            else None,
            "as_of": as_of.isoformat(),
            "tried": implementation(db, action, as_of)
            if state in ("in_progress", "ended")
            else None,
        }
        if state == "ended" and past and str(action.id) in measured:
            play = playbook.PLAY.get(action.play or "")
            if play is not None and play.adherence is not None:
                item["calendar_check"] = NO_CHECK_BY.format(day=as_of)
            stored = _stored_result(db, team, action, as_of)
            item["result"] = _result(db, team, action, as_of, {}) if stored else no_outcome(as_of)
            out.append(item)
            continue
        found = results.get(str(action.id)) if state == "ended" else None
        if found is not None:
            followed = found.get("followed")
            if followed is not None:  # the calendar's own observation, beside the report
                item["calendar_check"] = followed.get("text")
                item["followed_on_the_calendar"] = bool(followed.get("followed"))
            item["result"] = _result(db, team, action, as_of, found)
        out.append(item)
    return out


def overview(
    db: Session,
    team: Team,
    week: date | None,
    today: date,
    report: TeamReport | None = None,
    follow: bool = True,
    as_of: date | None = None,
) -> dict:
    """The team's week: its report's state, priorities, weekly comparison and follow-up.

    With no week asked, the latest stored report. With a week asked and no report for it, says so
    and substitutes nothing. A week's answer is dated the day after the week, or the day its
    report was made if that was later (never after today), so a report never appears under a date
    before it existed; the week covered and the day it was made are given apart.

    An explicit `as_of` is a cutoff for the whole answer: only a report made by then, the team's
    decisions and reports of trying as known then, and outcomes stored by then. With no report by
    then it says "No report was available by that date." and gives nothing about a later one.
    """
    cutoff = min(as_of, today) if as_of is not None else None
    if report is None:
        report = week_report(db, team, week, made_by=cutoff)
    out: dict = {"team_id": str(team.id), "team": team.name, "minimum": MIN_MEMBERS}
    if report is None and cutoff is not None:
        asked = week_of(week) if week is not None else None
        out["report"] = {
            "state": "no_report_by_then",
            "week": _span(asked.start, asked.end) if asked else None,
            "note": "No report was available by that date.",
        }
        out["priorities"] = []
        if follow:
            out["follow_up"] = follow_up(db, team, cutoff, today)
        out["as_of"] = cutoff.isoformat()
        return out
    if report is None:
        asked = week_of(week) if week is not None else None
        out["report"] = {
            "state": "no_report",
            "week": _span(asked.start, asked.end) if asked else None,
            "note": "No report was made for that week." if asked else "No report yet.",
        }
        out["priorities"] = []
        return out
    span = week_of(report.week_start)
    made = report.created_at.date()
    if cutoff is not None:
        as_of = cutoff
    elif week is not None:
        as_of = min(today, max(span.end + timedelta(days=1), made))
    else:
        as_of = today
    priorities = [
        p for row in (report.body or {}).get("priorities", []) if (p := _priority(report, row))
    ]
    state = (
        "withheld"
        if report.status != "ready"
        else "findings"
        if priorities
        else "no_priority_finding"
    )
    out["report"] = {
        "state": state,
        "status": report.status,  # ready or withheld, as the report was made
        "report_id": str(report.id),
        "week": _span(span.start, span.end),
        "made_on": made.isoformat(),  # apart from the week covered: a report can be made later
        "roster": report.members_total,
        "with_enough_data": report.members_included,
    }
    if report.status != "ready":
        out["report"]["reason"] = (
            f"Withheld: {report.members_included} of the {MIN_MEMBERS} people needed had data. "
            "No team figure is computed below that."
        )
        out["priorities"] = []
        return out
    out["priorities"] = priorities
    out["this_week_vs_previous_four"] = _weekly(report)
    if follow:  # the team's changes, measured; the app reads them from its own route
        out["follow_up"] = follow_up(db, team, as_of, today)
    out["as_of"] = as_of.isoformat()
    return out


def legacy_report(found: dict) -> dict:
    """The first version's `weekly_report`, from an overview: the same keys, controlled text."""
    report = found["report"]
    if report["state"] == "withheld":
        headline = report["reason"]
    elif found["priorities"]:
        first = found["priorities"][0]
        headline = f"{first['label']}: {first['metric_label']} {first['direction']}"
    else:
        headline = "No priority finding this week."
    weekly = found.get("this_week_vs_previous_four") or {}
    figures = [
        f"{row['metric_label']}: median change {row['change']['text']} "
        f"({row['higher']} higher, {row['lower']} lower, {row['contributors']} people)"
        for row in (*weekly.get("changed", []), *weekly.get("steady", []))
    ] + [
        f"{row['metric_label']}: not enough data ({row['contributors']} of the {row['minimum']} "
        "people needed)"
        for row in weekly.get("withheld_metrics", [])
    ]
    return {
        "week_start": report["week"]["start"],
        "status": report["status"],
        "headline": headline,
        "figures": figures,
    }


def alert_line(alert) -> str:
    """An open team alert from its fields only: never its stored sentence (#246)."""
    way = _direction(alert.metric, alert.direction) or alert.direction
    return (
        f"{team_info(alert.metric).label} {way} across the team (raised {alert.raised_at:%b %-d})"
    )


def finding_evidence(db: Session, team: Team, report_id: str, evidence_id: str) -> dict:
    """One record of one report of this team, bounded. Anything else is NotFound."""
    try:
        report = db.get(TeamReport, uuid.UUID(str(report_id)))
    except ValueError:
        raise NotFound from None
    if report is None or report.team_id != team.id:
        raise NotFound
    return evidence_of(report, evidence_id)


def evidence_of(report: TeamReport, evidence_id: str) -> dict:
    cited = {
        row.get("evidence_id")
        for key in ("priorities", "sections", "challenges")
        for row in (report.body or {}).get(key, [])
    }
    record = (report.evidence or {}).get(evidence_id)
    if record is None or evidence_id not in cited:
        raise NotFound
    metric = record["metrics"][0]
    span = week_of(report.week_start)
    out = {
        "evidence_id": evidence_id,
        "report_id": str(report.id),
        "report_week": _span(span.start, span.end),
        "metric": metric,
        "metric_label": team_info(metric).label,
        "unit": _unit(metric),
        "coverage": {"roster": report.members_total, "minimum": MIN_MEMBERS},
        "limitations": list(LIMITS),
    }
    if record["tool"] == "team_scan":
        stats = record["stats"]
        out |= {
            "label": PRIORITY_LABELS.get(stats.get("status"), "Team scan"),
            "measured": "For each person, each of the four scanned weeks minus the person's own "
            "average over the fixed baseline; the team figure is the median across people.",
            "method": "Each week is tested across the team, with one correction across every "
            "metric and week scanned. Sustained means changed the same way in at least "
            f"{SUSTAINED_WEEKS} weeks running, up to the latest.",
            # The weeks it held, as the finding says them; the whole scan is `scanned`.
            "target": _held(stats) or _window(record, 0),
            "scanned": _window(record, 0),
            "baseline": _window(record, 1),
            "status": stats.get("status"),
            "weeks_running": stats.get("weeks_running"),
            "weeks": [
                {
                    "week": _span(date.fromisoformat(w["start"]), date.fromisoformat(w["end"])),
                    "contributors": w.get("members", 0),
                    "change": _change(metric, w["median_change"]) if "members" in w else None,
                    "higher": w.get("members_up"),
                    "lower": w.get("members_down"),
                    "changed": bool(w.get("changed")),
                }
                for w in stats.get("weeks", [])
            ],
        }
        out["coverage"]["contributors"] = (stats.get("weeks") or [{}])[-1].get("members", 0)
        out["limitations"].append(
            "The baseline is fixed for the whole scan, so it differs from the weekly comparison's "
            "four weeks just before."
        )
        return out
    if record["tool"] == "team_change":
        stats = record["stats"]
        result = evidence_id in {
            row.get("evidence_id") for row in (report.body or {}).get("challenges", [])
        }
        out |= {
            "label": WEEKLY_LABEL,
            "measured": "For each person, the week's average minus the person's own average over "
            "the previous four weeks; the team figure is the median across people.",
            "method": "A test of whether the team's changes are centred away from zero; the "
            "report counts a metric as changed only after a correction across all metrics.",
            "target": _window(record, 0),
            "baseline": _window(record, 1),
        }
        out["coverage"]["contributors"] = stats.get("members", 0)
        if result:
            # The same account as the outcome card (`outcome`): its test, its dates, its caveats.
            from app.teams import outcome

            found = outcome.outcome_of(record)
            out |= {
                "label": "Result of a team change",
                "measured": outcome.MEASURED,
                "method": outcome.METHOD,
                "baseline_label": outcome.REFERENCES[outcome.BEFORE_CHANGE],
                "outcome": found,
                "outcome_label": outcome.OUTCOMES[found],
            }
            out["limitations"] += [outcome.CONTRIBUTION, outcome.REBOUND]
        figure = _bounded_change(record)
        if figure is None:
            out["withheld"] = (
                f"{stats.get('members', 0)} of the {MIN_MEMBERS} people needed had data for this "
                "metric, so no team figure was computed."
            )
        else:
            out["result"] = figure
        return out
    raise NotFound


# The team calendar, for the same week as a report (docs/supervisor-workflow.md)

CALENDAR_LABELS = {
    "meeting_minutes": "Scheduled meeting time",
    "after_hours_minutes": "Scheduled meeting time outside working hours",
    "back_to_back": "Back-to-back meetings",
    "meetings": "Meetings",
    "focus_minutes": "Focus time",
}
CALENDAR_DEFINITION = (
    "Scheduled meeting time: timed calendar events with at least one other attendee, not "
    "declined, cancelled, all-day or marked free; overlaps count once. Working hours are 8:00 to "
    "18:00 on weekdays; weekend meeting time counts as outside working hours. A day in a synced "
    "range with no meetings is 0; a day never synced is missing and is not counted as 0."
)
CALENDAR_LIMITS = (
    "Scheduled time, not time actually spent in meetings.",
    "Beside a Fitbit finding it shows what else happened that week; it does not show that "
    "meetings caused a change.",
    "Patterns does not read the supervisor's own calendar: dates of upcoming meetings come from "
    "the supervisor's calendar app or assistant connector.",
)


# The way each judged calendar metric adds load, as the coach reads it (coach.WATCHED).
LOADING = {
    "meeting_minutes": "higher",
    "after_hours_minutes": "higher",
    "back_to_back": "higher",
    "focus_minutes": "lower",
}


def clear_change(evidence) -> str:
    """ "higher", "lower" or "none" by the coach's bar, in both directions; "not judged" for a
    metric the coach has no bar for. A clear fall is reported as a fall, not as no change."""
    from app.teams import coach

    metric = evidence.metrics[0]
    bar = coach.NOTICEABLE.get(metric)
    if bar is None:
        return "not judged"
    stats = evidence.stats
    median, n = stats["median_change"], stats["members"]
    if median >= bar and stats["members_up"] >= coach.BROAD * n:
        return "higher"
    if median <= -bar and stats["members_down"] >= coach.BROAD * n:
        return "lower"
    return "none"


def _utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)  # SQLite drops it


def calendar_cohort(db: Session, team: Team, week) -> dict:
    """Whose calendars count for a past week: the group behind that week's Fitbit report.

    A report is made just after its week from everyone who is a member at that moment, with their
    history. So a calendar counts the people who had joined by the exact time that week's report
    was made and are still in the team. Someone who joined later, even the same day, was not in
    that report and is left out; someone who has left is left out too, since leaving withdraws
    their data from team figures. Only someone who was in the report and left after it makes the
    calendar group smaller than the report's, and that is said. With no report for the week, the
    group is the members at the start of the day after it, and the answer is labelled so."""
    from app.db.models import TeamMembership

    report = week_report(db, team, week.start)
    if report is not None:
        cutoff = _utc(report.created_at)
        basis = "the members when that week's report was made"
    else:
        cutoff = datetime.combine(week.end + timedelta(days=1), time.min, UTC)
        basis = "no report for that week: the members at the start of the day after it"
    rows = db.scalars(select(TeamMembership).where(TeamMembership.team_id == team.id)).all()
    by_then = [r for r in rows if _utc(r.joined_at) <= cutoff]
    counted = [r for r in by_then if r.left_at is None]
    joined_later = [r for r in rows if r.left_at is None and _utc(r.joined_at) > cutoff]
    left_since = [r for r in by_then if r.left_at is not None and _utc(r.left_at) > cutoff]
    return {
        "user_ids": [r.user_id for r in counted],
        "rule": "The members behind that week's report (joined by the moment it was made) who are "
        "still in the team. People who joined later and people who have left are not counted.",
        "basis": basis,
        "group_as_of": cutoff.isoformat(),
        "counted": len(counted),
        "joined_later": len(joined_later),
        "left_since": len(left_since),
        "same_group_as_report": report is not None and not left_since,
    }


def meeting_load(db: Session, team: Team, week: date | None, today: date) -> dict:
    """The team's scheduled meeting time in one full week against each member's previous four
    weeks: observed, below the minimum, or unavailable. Never another week's figures, and never
    a zero for days nobody synced."""
    from app.analysis.team_calendar import team_load
    from app.sync import calendar

    asked = week_of(week) if week is not None else week_of(today - timedelta(days=7))
    out: dict = {
        "team_id": str(team.id),
        "week": _span(asked.start, asked.end),
        "baseline": _span(asked.start - timedelta(days=28), asked.start - timedelta(days=1)),
        "definition": CALENDAR_DEFINITION,
        "minimum": MIN_MEMBERS,
        "limitations": list(CALENDAR_LIMITS),
    }
    if asked.end >= today:
        return out | {
            "state": "week_not_over",
            "note": "Figures are made for full weeks only; this week is not over.",
        }
    cohort = calendar_cohort(db, team, asked)
    frames, with_days = [], 0
    for uid in cohort["user_ids"]:
        frame = calendar.frame_for(
            db, uid, asked.start - timedelta(days=28), asked.end + timedelta(days=1)
        )
        if frame.empty:
            continue
        frames.append(frame)
        in_week = frame.loc[str(asked.start) : str(asked.end)]
        with_days += bool(in_week.notna().any(axis=None)) if not in_week.empty else 0
    load = team_load(frames, asked)
    out["coverage"] = {
        "roster": len(cohort["user_ids"]),
        "with_calendar_days_that_week": with_days,
        "with_a_whole_week_and_usual_week": max((e.n for e in load), default=0),
    }
    out["cohort"] = {k: v for k, v in cohort.items() if k != "user_ids"}
    if not cohort["same_group_as_report"]:
        out["limitations"].append(
            "No Fitbit report for that week to match."
            if cohort["left_since"] == 0
            else f"{cohort['left_since']} of the people in that week's Fitbit report have left "
            "since, so this calendar group is not the same group; compare the two with care."
        )
    if with_days == 0:
        return out | {
            "state": "unavailable",
            "note": "No calendar data for that week. Nothing is inferred: missing is not zero.",
            "figures": [],
        }
    figures = []
    for evidence in load:
        metric = evidence.metrics[0]
        stats = evidence.stats
        row: dict = {"metric": metric, "label": CALENDAR_LABELS[metric]}
        row["contributors"] = evidence.n
        if evidence.sufficient:
            moved = clear_change(evidence)
            row |= {
                "unit": stats["unit"],
                "median_week": stats["median_week"],
                "median_change": stats["median_change"],
                "higher": stats["members_up"],
                "lower": stats["members_down"],
                "clear_change": moved,
                "heavier_load": moved == LOADING.get(metric) if metric in LOADING else None,
                "evidence_id": evidence.id,
            }
        figures.append(row)
    if not any(e.sufficient for e in load):
        return out | {
            "state": "below_minimum",
            "note": f"Fewer than {MIN_MEMBERS} people had a whole week and their usual weeks on "
            "the calendar, so no team figure was computed.",
            "figures": figures,
        }
    return out | {
        "state": "observed",
        "clear_changes": [
            {
                "metric": row["metric"],
                "direction": row["clear_change"],
                "heavier_load": row["heavier_load"],
            }
            for row in figures
            if row.get("clear_change") in ("higher", "lower")
        ],
        "rule": "A clear change, either way: the typical member moved by at least an hour of "
        "meetings or focus time (30 min outside working hours, 3 back-to-back meetings) and at "
        "least half of contributors moved that way. heavier_load says whether that direction adds "
        "load (more meeting time, more outside hours, more back-to-back, less focus time); the "
        "number of meetings is not judged.",
        "figures": figures,
    }
