"""The coach: the team's calendar beside its wellbeing in the Monday briefing (docs/pivot.md).

All of it is code; no model writes or chooses any of it. From members' daily calendar counts
(`app.sync.calendar`) it finds what clearly moved in the report's week, against each member's own
usual week (`app.analysis.team_calendar.team_load`), from at least MIN_MEMBERS people:

- **Beside a wellbeing change** it says what the calendar did *in the same week*, never that one
  caused the other: two things moving together is not proof of a cause.
- **With no wellbeing change** it says by how much meetings moved and that nothing else did: a
  heavier week the team handled within its usual range.
- It names the calendar signals that point to a playbook change (`playbook.Play.triggers`), and
  after an approved change, whether the calendar shows it was followed (`Play.adherence`), so
  "it did not help" can be told apart from "it was not done".
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.analysis.evidence import Evidence, Window
from app.analysis.team import MIN_BASELINE_DAYS, MIN_MEMBERS
from app.analysis.team_calendar import LOAD, team_load
from app.db.models import Team, TeamAction
from app.sync import calendar
from app.teams import memberships

# The calendar signals the coach watches, each in the way that adds load.
WATCHED = {
    "meeting_minutes": "up",
    "after_hours_minutes": "up",
    "back_to_back": "up",
    "focus_minutes": "down",
}
BROAD = 0.5  # at least half the members with a calendar moved that way
# The smallest change a week the coach mentions, for the typical person: enough to notice in a
# working week, well above week-to-week noise (one more back-to-back meeting was not). Higher
# than the Team tab's per-person bar (team_calendar.MIN_CHANGE), which only sorts people up or
# down and is shown with its counts.
NOTICEABLE = {
    "meeting_minutes": 60.0,  # an hour more in meetings
    "after_hours_minutes": 30.0,  # half an hour more after hours
    "back_to_back": 3.0,  # three more back-to-back meetings
    "focus_minutes": 60.0,  # an hour less of focus time
}
BASELINE_DAYS = 28


def week_load(db: Session, team: Team, week: Window) -> list[Evidence]:
    """The team's calendar load for one week, one record per metric (team_calendar.team_load)."""
    frames = [
        frame
        for uid in memberships.member_ids(db, team)
        if not (
            frame := calendar.frame_for(
                db, uid, week.start - timedelta(days=BASELINE_DAYS), week.end + timedelta(days=8)
            )
        ).empty
    ]
    return team_load(frames, week)


def moved(load: list[Evidence]) -> dict[str, Evidence]:
    """The watched signals that clearly moved the loading way: the typical member by at least
    NOTICEABLE, and at least half the members past their own per-person bar."""
    found = {}
    for evidence in load:
        metric = evidence.metrics[0]
        way = WATCHED.get(metric)
        stats = evidence.stats
        if way is None or not evidence.sufficient:
            continue
        change = stats["median_change"] if way == "up" else -stats["median_change"]
        count = stats["members_up" if way == "up" else "members_down"]
        if change >= NOTICEABLE[metric] and count >= BROAD * stats["members"]:
            found[metric] = evidence
    return found


def amount(metric: str, value: float) -> str:
    """A calendar figure as a supervisor reads it: minutes as hours and minutes, counts whole."""
    value = abs(value)
    if LOAD[metric][1] == "count":
        return f"{value:.0f}"
    hours, minutes = divmod(round(value), 60)
    if hours and minutes:
        return f"{hours} h {minutes} min"
    return f"{hours} h" if hours else f"{minutes} min"


def _part(evidence: Evidence, first: bool) -> str:
    metric = evidence.metrics[0]
    stats = evidence.stats
    way = WATCHED[metric]
    count = stats["members_up" if way == "up" else "members_down"]
    people = " people" if first else ""
    return (
        f"{LOAD[metric][0].lower()} {way} {amount(metric, stats['median_change'])} "
        f"({count} of {stats['members']}{people})"
    )


def line(load: list[Evidence], wellbeing_changed: bool) -> dict | None:
    """The briefing's calendar sentence, or None when nothing clearly moved or too few calendars."""
    found = moved(load)
    if not found:
        return None
    shown = [found[m] for m in WATCHED if m in found]
    parts = [_part(e, i == 0) for i, e in enumerate(shown)]
    listed = ", ".join(parts)
    figures = f"For the typical person, against their own usual week: {listed}."
    if wellbeing_changed:
        text = f"In the same week, the team's calendars were busier than usual. {figures}"
    else:
        text = (
            f"Meetings changed last week. {figures} Nothing in sleep, recovery or activity moved "
            "beyond the team's usual range: a heavier week, handled within its capacity."
        )
    return {"text": text, "kind": "calendar", "metric": None, "evidence_ids": [e.id for e in shown]}


def signals(load: list[Evidence]) -> set[tuple[str, str]]:
    """The calendar signals that moved, as (metric, way), for playbook.Play.triggers."""
    return {(metric, WATCHED[metric]) for metric in moved(load)}


def followed(db: Session, team: Team, action: TeamAction, metric: str, way: str) -> dict | None:
    """Whether the calendar shows the change was done: the metric during it against each member's
    28 days before, pooled as a median weekly change, from at least MIN_MEMBERS people. None when
    fewer have a calendar for both spans."""
    during = Window(start=action.starts_on, end=action.ends_on)
    before = Window(
        start=during.start - timedelta(days=BASELINE_DAYS), end=during.start - timedelta(days=1)
    )
    changes = []
    for uid in memberships.member_ids(db, team):
        frame = calendar.frame_for(db, uid, before.start, during.end + timedelta(days=1))
        if frame.empty or metric not in frame.columns:
            continue
        span = frame[metric].loc[pd.Timestamp(during.start) : pd.Timestamp(during.end)].dropna()
        usual = frame[metric].loc[pd.Timestamp(before.start) : pd.Timestamp(before.end)].dropna()
        if len(span) < (during.end - during.start).days // 2 + 1 or len(usual) < MIN_BASELINE_DAYS:
            continue
        changes.append(7 * (float(span.mean()) - float(usual.mean())))
    if len(changes) < MIN_MEMBERS:
        return None
    median = float(np.median(changes))
    threshold = NOTICEABLE[metric]
    went = (
        sum(c <= -threshold for c in changes)
        if way == "down"
        else sum(c >= threshold for c in changes)
    )
    done = (-median if way == "down" else median) >= threshold and went >= BROAD * len(changes)
    label = LOAD[metric][0]
    if done:
        text = (
            f"{label} {'fell' if way == 'down' else 'rose'} during it: "
            f"{amount(metric, median)} a week for the typical person ({went} of {len(changes)})."
        )
    else:
        text = (
            f"{label} did not clearly {'fall' if way == 'down' else 'rise'} during it, "
            "so it may not have been followed."
        )
    return {"followed": done, "text": text, "members": len(changes)}


def heads_up_week(report_body: dict) -> bool:
    """True when the week's report found no team-wide change in any wellbeing metric."""
    return not any(s.get("status") == "changed" for s in report_body.get("sections", []))


def report_week(report) -> Window:
    start: date = report.week_start
    return Window(start=start, end=start + timedelta(days=6))
