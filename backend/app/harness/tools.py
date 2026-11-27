"""What a harness may read and send through MCP, as plain functions of (db, caller).

Every function checks the caller's current role, as the app does, and returns only what the app
would show that person: a supervisor's own teams in aggregates from at least 5 people, a member's
own days. Check-in alerts are never read or written here (docs/mcp.md, docs/escalation.md).
What a harness sends is untrusted: checked against the schemas below and held as pending until
the person approves it in the app.
"""

import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import null, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analysis.team import TEAM_METRICS, team_observed
from app.db.daily import load_daily
from app.db.models import (
    EVENT_CATEGORIES,
    HarnessSubmission,
    Team,
    TeamAction,
    TeamAlert,
    TeamNote,
    User,
)
from app.sync import calendar
from app.teams import agent as team_agent
from app.teams import memberships as teams
from app.teams import observed as observed_text
from app.teams import playbook, reports, view

PAST_DAYS = 60  # how far back a harness may send calendar days
AHEAD_DAYS = 14  # and how far ahead
OWN_METRICS = ("sleep_minutes", "steps", "resting_hr", "hrv_ms")


class HarnessError(ValueError):
    """Refused; the message says why and is safe to show the harness."""


# --- what a harness may send ----------------------------------------------------------------


class CalendarDayIn(BaseModel):
    """One day of a member's own meeting load, as counted by the harness from its calendar."""

    model_config = ConfigDict(extra="forbid")

    date: date
    meeting_minutes: float = Field(ge=0, le=24 * 60)
    meetings: int = Field(ge=0, le=60)
    after_hours_minutes: float = Field(ge=0, le=24 * 60)
    back_to_back: int = Field(ge=0, le=60)
    focus_minutes: float = Field(default=0, ge=0, le=24 * 60)


class TeamEventIn(BaseModel):
    """A team event the harness knows of (a launch, a deadline), for the supervisor's notes."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    starts_on: date
    ends_on: date | None = None
    # Optional: "other" for a known event that fits none; left out when there is no category.
    category: Literal[EVENT_CATEGORIES] | None = None

    @field_validator("title")
    @classmethod
    def _plain(cls, value: str) -> str:
        cleaned = " ".join(value.split())  # one line, kept as data
        if not cleaned:
            raise ValueError("A title is needed.")
        # Control characters (NUL, terminal escapes) are not text: PostgreSQL refuses NUL in JSON,
        # and escapes could rewrite a screen that shows the title.
        if any(unicodedata.category(ch).startswith("C") for ch in cleaned):
            raise ValueError("A title is plain text, without control characters.")
        return cleaned


class FindingRef(BaseModel):
    """A finding of one of the team's reports, as team_overview gives it."""

    model_config = ConfigDict(extra="forbid")

    report_id: str = Field(min_length=1, max_length=64)
    evidence_id: str = Field(min_length=1, max_length=32)


class TrackingIn(BaseModel):
    """What to observe, chosen now, before any outcome exists: a metric and the days to watch."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    observe_from: date
    observe_to: date


class TeamChangeIn(BaseModel):
    """A change the supervisor agreed to in the chat, to be confirmed in the Patterns app."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=8, max_length=64)
    # The playbook's own ids, offered as the schema's choices so an assistant picks one on its
    # first try; a change in the supervisor's own words is planned in the app.
    play: Literal[tuple(playbook.PLAY)]  # type: ignore[valid-type]
    starts_on: date
    # Required: the dates the supervisor agreed to, never a length Patterns picks (one day is
    # starts_on again).
    ends_on: date
    event_id: str | None = Field(default=None, max_length=64)
    finding: FindingRef | None = None
    tracking: TrackingIn | None = None

    @field_validator("request_id")
    @classmethod
    def _token(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", value):
            raise ValueError("A request_id is letters, digits and - _ . : only.")
        return value


def _own_data_allowed(user: User) -> None:
    # HR and admins have nothing to read through MCP, their own days included (docs/mcp.md).
    if user.role not in ("member", "supervisor"):
        raise HarnessError("Nothing can be read through MCP with this account.")


def _in_range(day: date, today: date) -> None:
    if not today - timedelta(days=PAST_DAYS) <= day <= today + timedelta(days=AHEAD_DAYS):
        raise HarnessError(
            f"Dates must be within the last {PAST_DAYS} days or the next {AHEAD_DAYS}: {day}."
        )


# --- who is calling -------------------------------------------------------------------------


def _supervised(db: Session, user: User, team_id: str) -> Team:
    if user.role != "supervisor":
        raise HarnessError("Only a supervisor can read or send team information.")
    try:
        team = teams.supervised_team(db, user, team_id)
    except Exception:
        raise HarnessError("No such team.") from None  # another's team looks like none
    if teams.overlap_problem(db, team):
        raise HarnessError("This team's figures are paused.")
    return team


def who_am_i(db: Session, user: User) -> dict:
    if user.role == "supervisor":
        own = db.scalars(select(Team).where(Team.supervisor_id == user.id)).all()
        return {
            "role": "supervisor",
            "teams": [
                {"team_id": str(t.id), "name": t.name, "members": teams.active_members(db, t)}
                for t in own
            ],
            "can": "read your teams' figures (from at least 5 people) and send team events",
        }
    if user.role == "member":
        joined = [team.name for _, team, _ in teams.memberships(db, user)]
        return {
            "role": "member",
            "teams": joined,
            "can": "read your own recent days and calendar counts, and send your calendar days",
        }
    return {"role": user.role, "can": "nothing through MCP"}


# --- reading --------------------------------------------------------------------------------


def _week(value: str | None) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise HarnessError("A week is a date like 2021-07-19 (any day of that week).") from None


def team_overview(
    db: Session,
    user: User,
    team_id: str,
    today: date,
    week: str | None = None,
    as_of: str | None = None,
) -> dict:
    """The team's week in one call: the report's state, its priority findings and weekly
    comparison, each with its own dates, coverage and evidence id, and the follow-up on team
    changes as known then (app.teams.view). With no week, the latest report, plus today's
    observed readings and open alerts as before. With a week, that week only: nothing current is
    mixed in, and a week without a report says so. `as_of`: what was known by that day, applied
    to the whole answer; nothing current is mixed in either."""
    team = _supervised(db, user, team_id)
    asked = _week(week)
    cutoff = _date(as_of, "as_of")
    out = view.overview(db, team, asked, today, as_of=cutoff)
    if asked is not None:
        return out
    if cutoff is not None and cutoff < today:
        out["note"] = "Today's readings and open alerts are left out of an answer for a past date."
        return out
    frames = reports.member_frames(db, team, today - timedelta(days=4), today)
    report = view.week_report(db, team, None)
    alerts = db.scalars(
        select(TeamAlert).where(TeamAlert.team_id == team.id, TeamAlert.resolved_at.is_(None))
    ).all()
    # Kept for callers of the first version, rebuilt from computed fields and fixed labels: a
    # stored headline, section or alert sentence can carry a supervisor's note (#246).
    return out | {
        "readings": [observed_text.sentence(e, today) for e in team_observed(frames, today)],
        "weekly_report": None if report is None else view.legacy_report(out),
        "open_alerts": [view.alert_line(a) for a in alerts],
        "minimum_members": teams.MIN_MEMBERS,
    }


def team_finding_evidence(
    db: Session, user: User, team_id: str, report_id: str, evidence_id: str
) -> dict:
    """One evidence record of one of the team's reports, bounded (app.teams.view)."""
    team = _supervised(db, user, team_id)
    try:
        return view.finding_evidence(db, team, report_id, evidence_id)
    except view.NotFound:
        raise HarnessError("No such evidence for this team's report.") from None


def team_meeting_load(
    db: Session, user: User, team_id: str, today: date, week: str | None = None
) -> dict:
    """The team's scheduled meeting time for one full week (the last one when no week is asked),
    with its comparison dates and an explicit state (app.teams.view.meeting_load)."""
    team = _supervised(db, user, team_id)
    out = view.meeting_load(db, team, _week(week), today)
    # Kept for callers of the first version.
    return out | {
        "members_with_a_calendar": out.get("coverage", {}).get("with_calendar_days_that_week", 0),
        "minimum_members": teams.MIN_MEMBERS,
    }


def my_recent_days(db: Session, user: User, today: date, days: int = 7) -> list[dict]:
    """The caller's own last days: sleep, steps, resting heart rate and HRV."""
    _own_data_allowed(user)
    days = max(1, min(days, 28))
    frame = load_daily(
        db, user.id, "google_health", today - timedelta(days=days - 1), today + timedelta(days=1)
    )
    out = []
    for stamp, row in frame.iterrows():
        out.append(
            {"date": stamp.date().isoformat()}
            | {
                m: (None if m not in row or row[m] != row[m] else round(float(row[m]), 1))
                for m in OWN_METRICS
            }
        )
    return out


def my_calendar_days(db: Session, user: User, today: date, days: int = 14) -> list[dict]:
    _own_data_allowed(user)
    days = max(1, min(days, 60))
    frame = calendar.frame_for(
        db, user.id, today - timedelta(days=days - 1), today + timedelta(days=1)
    )
    return [
        {"date": stamp.date().isoformat()} | {k: float(v) for k, v in row.dropna().items()}
        for stamp, row in frame.iterrows()
    ]


# --- sending, held as pending ---------------------------------------------------------------


def _hold(
    db: Session, user: User, kind: str, payload: dict, team: Team | None, token_id, now: datetime
) -> dict:
    row = HarnessSubmission(
        user_id=user.id,
        team_id=team.id if team else None,
        token_id=token_id,
        kind=kind,
        payload=payload,
        status="pending",
        created_at=now,
    )
    db.add(row)
    db.flush()
    return {
        "submission_id": str(row.id),
        "status": "pending",
        "note": "Held until approved in the Patterns app; nothing changes before that.",
    }


def send_calendar_days(
    db: Session, user: User, days: list[CalendarDayIn], token_id, now: datetime
) -> dict:
    """A member's own calendar days, counted by the harness; held for them to approve."""
    if user.role != "member":
        raise HarnessError("Only a member sends their own calendar days.")
    if not days or len(days) > PAST_DAYS + AHEAD_DAYS + 1:
        raise HarnessError(f"Send between 1 and {PAST_DAYS + AHEAD_DAYS + 1} days.")
    seen = set()
    for day in days:
        _in_range(day.date, now.date())
        if day.date in seen:
            raise HarnessError(f"{day.date} appears twice.")
        seen.add(day.date)
    payload = {"days": [d.model_dump(mode="json") for d in days]}
    return _hold(db, user, "calendar_days", payload, None, token_id, now)


def send_team_event(
    db: Session, user: User, team_id: str, event: TeamEventIn, token_id, now: datetime
) -> dict:
    """A team event for the supervisor's notes; held for them to approve."""
    team = _supervised(db, user, team_id)
    # Screened like a note written in the app (the team agent's model reads notes), so an
    # instruction, a person singled out or someone's health is refused before it is even held.
    if problem := team_agent._unsafe(event.title, note=True):
        raise HarnessError(f"Not sent: {problem}")
    _in_range(event.starts_on, now.date())
    if event.ends_on is not None:
        _in_range(event.ends_on, now.date())
        if event.ends_on < event.starts_on:
            raise HarnessError("The event ends before it starts.")
    return _hold(db, user, "team_event", event.model_dump(mode="json"), team, token_id, now)


# --- the team's past cases (docs/change-memory.md) ----------------------------------------------


def _date(value: str | None, field: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HarnessError(f"{field}: a date like 2026-11-20.") from None


def team_history(
    db: Session,
    user: User,
    team_id: str,
    today: date,
    start: str | None = None,
    end: str | None = None,
    category: str | None = None,
    play: str | None = None,
    metric: str | None = None,
    as_of: str | None = None,
    cursor: str | None = None,
) -> dict:
    """The team's past cases: events (with or without a change), changes in every state, and the
    evidence available for their dates. Facts only: relevance is the assistant's to judge.

    A page holds at most 20; `next_cursor` continues the same lookup. The cursor carries the
    team, the filters and the as-of date of the first page (resolved, so "today" does not move
    between pages); it is passed alone."""
    from app.teams import history

    team = _supervised(db, user, team_id)
    after = None
    asked_as_of = as_of is not None
    if cursor is not None:
        if any(v is not None for v in (start, end, category, play, metric, as_of)):
            raise HarnessError(
                "cursor: pass it alone; it already carries the filters and as_of of the first page."
            )
        saved = _read_cursor(cursor, team)
        start, end, category, play, metric = (saved["filters"][k] for k in FILTERS)
        as_of, asked_as_of, after = saved["as_of"], saved["asked_as_of"], tuple(saved["after"])
    if category is not None and category not in EVENT_CATEGORIES:
        raise HarnessError(f"category: one of {', '.join(EVENT_CATEGORIES)}.")
    if play is not None and play not in (*playbook.PLAY, "custom"):
        raise HarnessError(f"play: one of {', '.join(playbook.PLAY)}, or custom.")
    if metric is not None and metric not in TEAM_METRICS:
        raise HarnessError(f"metric: one of {', '.join(TEAM_METRICS)}.")
    known = min(_date(as_of, "as_of") or today, today)
    out = history.history(
        db,
        team,
        today,
        start=_date(start, "start"),
        end=_date(end, "end"),
        category=category,
        play=play,
        metric=metric,
        as_of=known,
        after=after,
    )
    if not asked_as_of:
        out["as_of_meaning"] = "what was known on the day this lookup began"
    last = out.pop("last")
    out["next_cursor"] = (
        _write_cursor(
            team,
            {k: out["filters"][k] for k in FILTERS},
            out["as_of"],
            asked_as_of,
            last,
        )
        if last
        else None
    )
    return out


FILTERS = ("start", "end", "category", "play", "metric")


def _write_cursor(team: Team, filters: dict, as_of: str, asked: bool, after) -> str:
    import base64
    import json

    body = {"team": str(team.id), "filters": filters, "as_of": as_of, "asked_as_of": asked}
    body["after"] = list(after)
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _read_cursor(cursor: str, team: Team) -> dict:
    """A cursor is the caller's to hold, so it is checked like any input: its values pass the
    same validation as the filters (team_history re-checks them), and it only works for the team
    it came from."""
    import base64
    import binascii
    import json

    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        saved = json.loads(raw)
        ok = (
            isinstance(saved, dict)
            and set(saved) == {"team", "filters", "as_of", "asked_as_of", "after"}
            and isinstance(saved["filters"], dict)
            and set(saved["filters"]) == set(FILTERS)
            and all(v is None or isinstance(v, str) for v in saved["filters"].values())
            and isinstance(saved["as_of"], str)
            and isinstance(saved["asked_as_of"], bool)
            and isinstance(saved["after"], list)
            and len(saved["after"]) == 2
            and all(isinstance(v, str) for v in saved["after"])
        )
    except (binascii.Error, ValueError, UnicodeDecodeError):
        ok = False
    if not ok or len(cursor) > 2000:
        raise HarnessError("cursor: not a cursor from team_history.")
    if saved["team"] != str(team.id):
        raise HarnessError("cursor: it belongs to another lookup.")
    return saved


def team_case(
    db: Session,
    user: User,
    team_id: str,
    today: date,
    case_id: str,
    day: str | None = None,
    as_of: str | None = None,
) -> dict:
    """One case from team_history in full, with the evidence that exists for its dates."""
    from app.teams import history

    team = _supervised(db, user, team_id)
    try:
        return history.one_case(
            db, team, case_id, today, day=_date(day, "day"), as_of=_date(as_of, "as_of")
        )
    except history.NotFound:
        raise HarnessError("No such case for this team.") from None


# --- a decision, recorded as a pending draft (docs/change-memory.md) ---------------------------

SUGGESTED = "Suggested in chat — awaiting your confirmation"
CHANGE_AHEAD_DAYS = 60  # as for a change planned in the app
LONGEST_CHANGE_DAYS = 60


def _draft(action: TeamAction) -> dict:
    """A recorded change as MCP returns it: controlled labels and fields, no free text."""
    tracked = action.metric is not None and action.comparison == "observation_only"
    return {
        "change_id": str(action.id),
        "request_id": action.request_id,
        "status": "pending" if action.status == "proposed" else action.status,
        "shown_in_app": SUGGESTED if action.status == "proposed" else None,
        "title": view.action_title(action),
        "play": action.play if action.play in playbook.PLAY else None,  # never a retired id
        "starts_on": action.starts_on.isoformat(),
        "ends_on": action.ends_on.isoformat(),
        "linked_event_id": str(action.event_id) if action.event_id else None,
        "linked_finding": {
            "report_id": str(action.finding_report_id),
            "evidence_id": action.finding_evidence_id,
        }
        if action.finding_report_id
        else None,
        "tracking": {
            "metric": action.metric,
            "observe_from": action.observe_starts_on.isoformat(),
            "observe_to": action.observe_ends_on.isoformat(),
            "comparison": "observation only",
        }
        if tracked
        else None,
        "members_notified": 0 if action.status == "proposed" else None,
        "note": "Nothing reaches the team until the supervisor confirms it in the Patterns app. "
        "Whether the team tried it is unknown until the supervisor reports it there.",
    }


def _same_request(action: TeamAction, change: TeamChangeIn, ends_on: date) -> bool:
    track = change.tracking
    return (
        action.play == change.play
        and action.starts_on == change.starts_on
        and action.ends_on == ends_on
        and (str(action.event_id) if action.event_id else None) == change.event_id
        and action.finding_evidence_id == (change.finding.evidence_id if change.finding else None)
        and action.metric == (track.metric if track else None)
        and action.observe_starts_on == (track.observe_from if track else None)
        and action.observe_ends_on == (track.observe_to if track else None)
    )


def record_team_change(
    db: Session,
    user: User,
    team_id: str,
    change: TeamChangeIn,
    token_id,
    now: datetime,
    today: date,
) -> dict:
    """Records a playbook change the supervisor agreed to in the chat, as a pending draft that
    only the Patterns app can confirm or decline. Nobody is told; nothing is measured unless
    tracking was chosen now. The same request_id returns the same record."""
    team = _supervised(db, user, team_id)
    play = playbook.PLAY.get(change.play)
    if change.play == playbook.CUSTOM or play is None:  # the schema already refuses these
        raise HarnessError(
            "Only a playbook change can be recorded through MCP; a change in your own words is "
            "planned in the Patterns app. Playbook changes: " + ", ".join(playbook.PLAY) + "."
        )
    ends_on = change.ends_on
    if (repeat := _repeat(db, team, change, ends_on)) is not None:
        return repeat
    if not today <= change.starts_on <= today + timedelta(days=CHANGE_AHEAD_DAYS):
        raise HarnessError(
            f"starts_on: a change starts between today and {CHANGE_AHEAD_DAYS} days from now."
        )
    if (
        not change.starts_on
        <= ends_on
        <= change.starts_on + timedelta(days=LONGEST_CHANGE_DAYS - 1)
    ):
        raise HarnessError(
            f"ends_on: on or after starts_on, and at most {LONGEST_CHANGE_DAYS} days in all."
        )
    event = None
    if change.event_id is not None:
        event = next(
            (
                n
                for n in db.scalars(select(TeamNote).where(TeamNote.team_id == team.id))
                if str(n.id) == change.event_id
            ),
            None,
        )
        if event is None:
            raise HarnessError("event_id: no such event for this team.")
    if change.finding is not None:
        try:
            view.finding_evidence(db, team, change.finding.report_id, change.finding.evidence_id)
        except view.NotFound:
            raise HarnessError("finding: no such finding in this team's reports.") from None
    track = change.tracking
    if track is not None:
        if track.metric not in TEAM_METRICS:
            raise HarnessError(f"tracking.metric: one of {', '.join(TEAM_METRICS)}.")
        if not today <= track.observe_from <= track.observe_to:
            raise HarnessError(
                "tracking: the days observed start today or later and end on or after they "
                "start, so they are chosen before any outcome exists."
            )
        if track.observe_to > track.observe_from + timedelta(days=LONGEST_CHANGE_DAYS - 1):
            raise HarnessError(f"tracking: at most {LONGEST_CHANGE_DAYS} days observed.")
    action = TeamAction(
        team_id=team.id,
        kind="challenge",
        title=play.title,
        body=play.body,
        metric=track.metric if track else None,
        starts_on=change.starts_on,
        ends_on=ends_on,
        status="proposed",
        source="assistant",
        play=play.id,
        proposed_at=now,
        request_id=change.request_id,
        token_id=token_id,
        event_id=event.id if event else None,
        finding_report_id=_uuid(change.finding.report_id) if change.finding else None,
        finding_evidence_id=change.finding.evidence_id if change.finding else None,
        observe_starts_on=track.observe_from if track else None,
        observe_ends_on=track.observe_to if track else None,
        # NULL itself: a plain None would let the column default make it "before_the_change".
        comparison="observation_only" if track else null(),
    )
    try:
        with db.begin_nested():  # a retry racing this one hits the unique request id
            db.add(action)
            db.flush()
    except IntegrityError:
        if (repeat := _repeat(db, team, change, ends_on)) is not None:
            return repeat
        raise
    return _draft(action)


def _repeat(db: Session, team: Team, change: TeamChangeIn, ends_on: date) -> dict | None:
    existing = db.scalar(
        select(TeamAction).where(
            TeamAction.team_id == team.id, TeamAction.request_id == change.request_id
        )
    )
    if existing is None:
        return None
    if not _same_request(existing, change, ends_on):
        raise HarnessError("This request_id was already used for a different change.")
    return _draft(existing) | {"repeat": True}


def _uuid(value: str):
    import uuid

    return uuid.UUID(value)
