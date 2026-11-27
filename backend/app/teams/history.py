"""A team's past cases for an assistant: events, decisions and the evidence for their dates
(docs/change-memory.md).

Patterns returns facts with their dates and leaves relevance to the assistant: it never ranks,
recommends, names a cause or says a change worked. Records are linked only when the supervisor
linked them; a date overlap is returned as `nearby`, labelled so. No free text leaves here: an
event is its category and dates (its words stay in the app, #246), a change its controlled title.
Evidence is what Patterns already has, the weekly reports whose weeks overlap a case; nothing
day-specific exists yet, and asking for a day says so instead of borrowing a week.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.team import MIN_MEMBERS, team_info, week_of
from app.db.models import Team, TeamAction, TeamNote, TeamReport
from app.teams import playbook, view

EVENT = "event"
CHANGE = "change"
NO_DAY = "No day-specific team evidence available."
LISTED = 20  # a short list first; the assistant opens a case with team_case
NEARBY = "Dates overlap only; not linked by the supervisor, and not an explanation."
SLEEP_DATES = (
    "Sleep is dated by the local day it ended: the figure for a day is the night ending that "
    "morning."
)
NIGHTLY = {"sleep_minutes", "sleep_score", "deep_sleep_minutes", "rem_sleep_minutes"}


class NotFound(LookupError):
    """No such case for this team."""


def _span(start: date | None, end: date | None) -> dict | None:
    if start is None:
        return None
    return {"start": start.isoformat(), "end": (end or start).isoformat()}


def _overlaps(a: dict | None, b: dict | None) -> bool:
    return a is not None and b is not None and a["start"] <= b["end"] and b["start"] <= a["end"]


def _event_id(note: TeamNote) -> str:
    return f"{EVENT}:{note.id}"


def _change_id(action: TeamAction) -> str:
    return f"{CHANGE}:{action.id}"


def _records(db: Session, team: Team, as_of: date):
    """The team's events and changes as known on `as_of`: nothing recorded after it."""
    notes = [
        n
        for n in db.scalars(select(TeamNote).where(TeamNote.team_id == team.id))
        if n.created_at is None or n.created_at.date() <= as_of
    ]
    actions = [
        a
        for a in db.scalars(
            select(TeamAction).where(TeamAction.team_id == team.id, TeamAction.kind == "challenge")
        )
        if a.proposed_at is None or a.proposed_at.date() <= as_of
    ]
    reports = [
        r
        for r in db.scalars(select(TeamReport).where(TeamReport.team_id == team.id))
        if r.created_at.date() <= as_of
    ]
    return notes, actions, reports


def _decision(action: TeamAction, as_of: date) -> dict:
    decided = action.decided_at.date() if action.decided_at else None
    if action.status == "proposed" or decided is None or decided > as_of:
        return {"state": "pending", "on": None}
    return {"state": action.status, "on": decided.isoformat()}


def _tracking(action: TeamAction) -> dict | None:
    if not action.metric:
        return None
    if action.comparison == "observation_only":
        return {
            "metric": action.metric,
            "metric_label": team_info(action.metric).label,
            "observe": _span(action.observe_starts_on, action.observe_ends_on),
            "comparison": "observation only (no comparison verdict)",
        }
    return {
        "metric": action.metric,
        "metric_label": team_info(action.metric).label,
        "observe": _span(action.starts_on, action.ends_on),
        "comparison": "the 28 days before the change started",
    }


def _weekly_context(reports: list[TeamReport], span: dict | None) -> list[dict]:
    """The weekly reports whose weeks overlap a case's dates: context, with their actual dates."""
    found = []
    for report in sorted(reports, key=lambda r: r.week_start):
        week = week_of(report.week_start)
        dates = _span(week.start, week.end)
        if _overlaps(dates, span):
            found.append(
                {
                    "report_id": str(report.id),
                    "week": dates,
                    "relation": "weekly context: a team figure for the whole week, not for a day "
                    "within it",
                    "state": "withheld" if report.status != "ready" else "ready",
                }
            )
    return found


def _outcome(db: Session, team: Team, action: TeamAction, as_of: date) -> dict | None:
    """The stored outcome, once a report covered the ended change by `as_of`."""
    stored = view._stored_result(db, team, action, as_of)
    if stored is None or action.comparison != "before_the_change":
        return None
    from app.teams import outcome

    report, record = stored
    described = outcome.describe(action, record)
    return {
        "outcome": described["outcome"],
        "label": described["label"],
        "difference": described.get("difference"),
        "contributors": described["contributors"],
        "minimum": MIN_MEMBERS,
        "during": described["during"],
        "reference": described["reference"],
        "report_id": str(report.id),
        "evidence_id": record["id"],
        "caveats": described["caveats"],
    }


def _event_case(note: TeamNote) -> dict:
    return {
        "case_id": _event_id(note),
        "kind": EVENT,
        "category": note.category,
        "dates": _span(note.starts_on, note.ends_on),
        "words": "kept in the Patterns app; not shared through MCP",
    }


def _change_case(db: Session, team: Team, action: TeamAction, as_of: date) -> dict:
    span = _span(action.starts_on, action.ends_on)
    decision = _decision(action, as_of)
    started = decision["state"] == "approved" and action.starts_on and action.starts_on <= as_of
    out = {
        "case_id": _change_id(action),
        "kind": CHANGE,
        "title": view.action_title(action),
        "play": action.play,
        # Not a current playbook change: the supervisor's own words, or a retired entry whose
        # stored title may be edited text; both read "Custom team change" (view.action_title).
        "custom": action.play not in playbook.PLAY,
        "dates": span,
        "recorded": {
            "by": view.STARTED_BY.get(action.source, "suggested by Patterns"),
            "on": action.proposed_at.date().isoformat() if action.proposed_at else None,
        },
        "decision": decision,
        "implementation": view.implementation(db, action, as_of) if started else None,
        "tracking": _tracking(action),
        "outcome": _outcome(db, team, action, as_of) if decision["state"] == "approved" else None,
    }
    if action.play == "custom" or action.play is None:
        out["custom_note"] = (
            "A change the supervisor wrote in their own words; what it involved is in the app, "
            "not shared through MCP."
        )
    elif out["custom"]:
        out["custom_note"] = (
            "A change from a playbook entry since retired; its wording is in the app, not shared "
            "through MCP."
        )
    return out


def _links(notes: list[TeamNote], actions: list[TeamAction], cases: dict[str, dict]) -> None:
    """Explicit links (the supervisor's), then nearby records by date overlap, kept apart."""
    events = {str(n.id): _event_id(n) for n in notes}
    for note in notes:
        cases[_event_id(note)]["linked_changes"] = []
    for action in actions:
        case = cases[_change_id(action)]
        linked = events.get(str(action.event_id)) if action.event_id else None
        case["linked"] = {
            "event": linked,
            "finding": {
                "report_id": str(action.finding_report_id),
                "evidence_id": action.finding_evidence_id,
            }
            if action.finding_report_id
            else None,
        }
        if linked:
            cases[linked]["linked_changes"].append(case["case_id"])
    for item in cases.values():
        linked = set(item.get("linked_changes", [])) | {(item.get("linked") or {}).get("event")}
        item["nearby"] = {
            "cases": sorted(
                other["case_id"]
                for other in cases.values()
                if other is not item
                and other["case_id"] not in linked
                and _overlaps(item["dates"], other["dates"])
            ),
            "meaning": NEARBY,
        }


def _cases(db: Session, team: Team, as_of: date) -> tuple[dict[str, dict], list]:
    notes, actions, reports = _records(db, team, as_of)
    cases = {_event_id(n): _event_case(n) for n in notes}
    cases |= {_change_id(a): _change_case(db, team, a, as_of) for a in actions}
    _links(notes, actions, cases)
    for case in cases.values():
        case["evidence"] = _weekly_context(reports, case["dates"])
    return cases, reports


def _keep(case: dict, start, end, category, play, metric, cases: dict[str, dict]) -> bool:
    dates = case["dates"]
    if start and (dates is None or dates["end"] < start.isoformat()):
        return False
    if end and (dates is None or dates["start"] > end.isoformat()):
        return False
    # Every filter given must hold; none is skipped because another matched.
    if category is not None:
        if case["kind"] == EVENT:
            if case["category"] != category:
                return False
        else:
            event = cases.get((case.get("linked") or {}).get("event") or "")
            if event is None or event["category"] != category:
                return False
    if play is not None:
        if case["kind"] != CHANGE:
            return False
        if not (case["custom"] if play == "custom" else case["play"] == play):
            return False
    if metric is not None:
        tracked = (case.get("tracking") or {}).get("metric")
        if case["kind"] != CHANGE or tracked != metric:
            return False
    return True


def history(
    db: Session,
    team: Team,
    today: date,
    *,
    start: date | None = None,
    end: date | None = None,
    category: str | None = None,
    play: str | None = None,
    metric: str | None = None,
    as_of: date | None = None,
) -> dict:
    """A short list of the team's cases, newest first, as known on `as_of` (today if not given):
    events with no change included, and declined, untried, inconclusive and unmeasured changes."""
    known = min(as_of or today, today)
    cases, _ = _cases(db, team, known)
    kept = [c for c in cases.values() if _keep(c, start, end, category, play, metric, cases)]
    kept.sort(key=lambda c: (c["dates"] or {"start": ""})["start"], reverse=True)
    return {
        "as_of": known.isoformat(),
        "as_of_meaning": "what was recorded by that date; anything later is left out"
        if as_of
        else "what is known today",
        "filters": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
            "category": category,
            "play": play,
            "metric": metric,
        },
        "cases": [_summary(c) for c in kept[:LISTED]],
        "more": max(0, len(kept) - LISTED),
        "note": "Linked records were linked by the supervisor; nearby ones only share dates. "
        "Open a case with team_case for its evidence.",
    }


def _summary(case: dict) -> dict:
    """The short form: dates, state, links and how much evidence exists, not the evidence."""
    out = {
        k: case[k]
        for k in ("case_id", "kind", "dates", "linked_changes", "linked", "nearby")
        if k in case
    }
    if case["kind"] == EVENT:
        out["category"] = case["category"]
    else:
        out |= {
            "title": case["title"],
            "play": case["play"],
            "decision": case["decision"],
            "implementation": case["implementation"],
            "tracked": case["tracking"] is not None,
            "outcome": (case["outcome"] or {}).get("label"),
        }
    out["evidence_available"] = len(case["evidence"])
    return out


def one_case(
    db: Session,
    team: Team,
    case_id: str,
    today: date,
    *,
    day: date | None = None,
    as_of: date | None = None,
) -> dict:
    """One case in full: its record, its links, and the evidence that exists for its dates."""
    known = min(as_of or today, today)
    cases, reports = _cases(db, team, known)
    found = cases.get(case_id)
    if found is None:
        raise NotFound
    out = found | {"as_of": known.isoformat()}
    out["evidence"] = [_week_lines(reports, ref) for ref in found["evidence"]]
    if day is not None:
        out["day"] = _day(found, reports, day)
    tracking = found.get("tracking")
    if tracking and tracking["comparison"].startswith("observation only"):
        out["observation"] = _observation(tracking, reports)
    return out


def _week_lines(reports: list[TeamReport], ref: dict) -> dict:
    """A weekly report, cut to what is reportable: each line's figure, coverage and evidence id."""
    report = next(r for r in reports if str(r.id) == ref["report_id"])
    weekly = view._weekly(report)
    return ref | {
        "label": view.WEEKLY_LABEL,
        "baseline": weekly["baseline"],
        "changed": weekly["changed"],
        "steady": weekly["steady"],
        "withheld_metrics": weekly["withheld_metrics"],
        "minimum": MIN_MEMBERS,
    }


def _day(found: dict, reports: list[TeamReport], day: date) -> dict:
    """A day asked about: there is no team figure for one day, so the gap is said, and the week
    that holds it is given as weekly context with its own dates."""
    week = week_of(day)
    holding = _weekly_context(reports, _span(week.start, week.end))
    return {
        "day": day.isoformat(),
        "within_case_dates": _overlaps(found["dates"], _span(day, day)),
        "day_specific": NO_DAY,
        "weekly_context": holding,
        "date_convention": SLEEP_DATES,
    }


def _observation(tracking: dict, reports: list[TeamReport]) -> dict:
    """Days chosen to observe: no day-level figure exists, so the state says so; the weeks that
    overlap are context only, not a comparison chosen for the change."""
    window = tracking["observe"]
    start, end = date.fromisoformat(window["start"]), date.fromisoformat(window["end"])
    whole_weeks = start == week_of(start).start and end == week_of(end).end
    return {
        "metric": tracking["metric"],
        "observe": window,
        "state": "unavailable",
        "reason": NO_DAY
        if not whole_weeks
        else "No figure is computed for a chosen window yet; the weekly reports below cover the "
        "same weeks as context.",
        "date_convention": SLEEP_DATES if tracking["metric"] in NIGHTLY else None,
        "weekly_context": _weekly_context(reports, window),
    }
