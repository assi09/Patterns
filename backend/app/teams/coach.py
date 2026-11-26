"""The coach: the team's calendar beside its wellbeing in the Monday briefing (docs/pivot.md).

All of it is code; no model writes or chooses any of it. From members' daily calendar counts
(`app.sync.calendar`) it finds what clearly moved in the report's week, against each member's own
usual week (`app.analysis.team_calendar.team_load`), from at least MIN_MEMBERS people:

- **Beside a wellbeing change** it says what the calendar did *in the same week*, never that one
  caused the other: two things moving together is not proof of a cause.
- **With no wellbeing change found** it says by how much meetings moved and that no clear
  change was detected in the readings there were enough of, naming those too thin to tell. It
  never says the team coped: an absence of evidence is not a measure of capacity.
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


def line(load: list[Evidence], sections: list[dict]) -> dict | None:
    """The briefing's calendar sentence, or None when nothing clearly moved or too few calendars.
    `sections` are the week's report sections, which say per wellbeing metric whether it changed,
    stayed steady or had too few readings to tell."""
    found = moved(load)
    if not found:
        return None
    shown = [found[m] for m in WATCHED if m in found]
    parts = [_part(e, i == 0) for i, e in enumerate(shown)]
    figures = f"For the typical person, against their own usual week: {', '.join(parts)}."
    ids = [e.id for e in shown]
    if any(s.get("status") == "changed" for s in sections):
        text = f"In the same week, the team's calendars were busier than usual. {figures}"
        return {"text": text, "kind": "calendar", "metric": None, "evidence_ids": ids}
    # No team-wide change found. That is all it says: an absence of evidence, not a measure of
    # the team's capacity, and only for the readings there were enough of.
    read = [s for s in sections if s.get("status") in ("steady", "changed")]
    short = [_in_sentence(s["label"]) for s in sections if s.get("status") == "not_enough_data"]
    if not read:
        after = "There were too few team readings to tell whether anything else changed."
    else:
        after = "We detected no clear change in the available team readings."
        if short:
            after += f" Too few readings to tell for {_listed(short)}."
    text = f"Calendars were busier last week. {figures} {after}"
    return {"text": text, "kind": "calendar", "metric": None, "evidence_ids": ids}


def _in_sentence(label: str) -> str:
    """A metric label inside a sentence: lower case, except an acronym ("HRV") stays as it is."""
    return label if label[:2].isupper() else label[:1].lower() + label[1:]


def _listed(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def signals(load: list[Evidence]) -> set[tuple[str, str]]:
    """The calendar signals that moved, as (metric, way), for playbook.Play.triggers."""
    return {(metric, WATCHED[metric]) for metric in moved(load)}


MEETING_FREE_DAYS = "meeting_free_days"  # an adherence measure of its own, not a calendar column


def _meeting_free_days(frame: pd.DataFrame, window: Window) -> tuple[float, int] | None:
    """Workdays with no meeting at all, per week, and the workdays read; out-of-office days are
    not counted, so a day away is not a meeting-free day."""
    days = frame.loc[pd.Timestamp(window.start) : pd.Timestamp(window.end)]
    days = days[(days.index.weekday < 5) & days["meeting_minutes"].notna()]
    if "out_of_office" in days.columns:
        days = days[days["out_of_office"].fillna(0) == 0]
    if days.empty:
        return None
    return 5 * float((days["meeting_minutes"] == 0).mean()), len(days)


def _followed_meeting_free(db: Session, team: Team, during: Window, before: Window) -> dict | None:
    """Whether the team kept a meeting-free day: the typical person had at least one meeting-free
    workday a week during it, more than in their 28 days before. Read from the days themselves,
    so moving Monday's meetings to Tuesday counts and only shortening meetings does not."""
    rows = []
    for uid in memberships.member_ids(db, team):
        frame = calendar.frame_for(db, uid, before.start, during.end + timedelta(days=1))
        if frame.empty or "meeting_minutes" not in frame.columns:
            continue
        now_, usual = _meeting_free_days(frame, during), _meeting_free_days(frame, before)
        if now_ is None or usual is None or now_[1] < 3 or usual[1] < 10:
            continue
        rows.append((now_[0], usual[0]))
    if len(rows) < MIN_MEMBERS:
        return None
    during_week = float(np.median([r[0] for r in rows]))
    usual_week = float(np.median([r[1] for r in rows]))
    kept = sum(r[0] >= 1 and r[0] > r[1] for r in rows)
    done = during_week >= 1 and during_week > usual_week and kept >= BROAD * len(rows)
    if done:
        text = (
            f"Meeting-free workdays during it: {during_week:.1f} a week for the typical person, "
            f"against {usual_week:.1f} before ({kept} of {len(rows)} had at least one a week)."
        )
    else:
        text = (
            f"Meeting-free workdays during it: {during_week:.1f} a week for the typical person, "
            f"against {usual_week:.1f} before, so it may not have been followed."
        )
    return {"followed": done, "text": text, "members": len(rows)}


def followed(db: Session, team: Team, action: TeamAction, metric: str, way: str) -> dict | None:
    """Whether the calendar shows the change was done: the metric during it against each member's
    28 days before, pooled as a median weekly change, from at least MIN_MEMBERS people. None when
    fewer have a calendar for both spans."""
    during = Window(start=action.starts_on, end=action.ends_on)
    before = Window(
        start=during.start - timedelta(days=BASELINE_DAYS), end=during.start - timedelta(days=1)
    )
    if metric == MEETING_FREE_DAYS:
        return _followed_meeting_free(db, team, during, before)
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


def report_week(report) -> Window:
    start: date = report.week_start
    return Window(start=start, end=start + timedelta(days=6))
