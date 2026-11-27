"""Team changes a supervisor can plan, and the one the weekly briefing may suggest.

A change is a team-level lever (meetings, deadlines, messages after hours, a shared goal), never
anything about one person and nothing medical. The supervisor can start one directly from the
Team tab, or write their own; the weekly briefing suggests one for approval when the team has a
reason for it: an event coming up like a past one that was followed by a dip, or a concern that
has lasted two weeks or more. Which change it suggests is decided by code from this team's own
history: one that went better during it before comes first, one that went worse comes last, and
one the supervisor declined recently is not suggested again. Each approved change is measured
like a weekly change once it ends (`app.teams.agent.challenge_result`): the team's metric during
it against the 28 days before. That is what happened during it, not proof it was the cause.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.evidence import Evidence
from app.analysis.report import change_text
from app.analysis.screen import FDR
from app.analysis.team import TEAM_METRICS, kind_of, team_info
from app.db.models import Team, TeamAction

CHALLENGE_DAYS = (7, 28)
DECLINED_REST = timedelta(days=28)  # a declined change is not suggested again this soon


@dataclass(frozen=True)
class Play:
    id: str
    title: str
    body: str
    fits: tuple[str, ...]  # the wellbeing metrics it is meant for, the first measured by default
    days: int = 14
    # The calendar signals that point to it: (metric, "up" or "down") as the team calendar
    # measures them (app.analysis.team_calendar.LOAD). None for a change the calendar cannot see.
    triggers: tuple[tuple[str, str], ...] = ()
    # Whether the team did it, read from the calendar during the change: (metric, the way it
    # should move). None when the calendar cannot tell.
    adherence: tuple[str, str] | None = None
    source: str = ""  # the evidence it rests on, as cited in docs/teams.md


# Four levers, one per thing a supervisor controls and the calendar can see: when people meet,
# how meetings are spaced, how much of the week they take, and movement. Each has its own trigger,
# so no two compete for the same signal, and each but the last can be checked against the
# calendar (docs/teams.md, "The playbook"). Retired on 2026-11-26, kept only as the titles stored
# on past changes: no_late_meetings and quiet_evenings (now the evening boundary), lighter_week
# and focus_mornings (now a meeting-free day), walking_meetings (its evidence is about creativity,
# and the calendar cannot tell a walk).
PLAYS = (
    Play(
        "evening_boundary",
        "Evening boundary",
        "No team meetings after 5 pm on working days; messages wait until the morning.",
        ("sleep_minutes", "bedtime_hour"),
        triggers=(("after_hours_minutes", "up"),),
        adherence=("after_hours_minutes", "down"),
        source="after-hours work messages and sleep (Barber & Santuzzi 2015); right to disconnect",
    ),
    Play(
        "meeting_free_day",
        "A meeting-free day",
        "One working day a week with no team meetings.",
        ("stress_score", "recovery_score", "strain", "hrv_ms", "resting_hr"),
        triggers=(("meeting_minutes", "up"), ("focus_minutes", "down")),
        # Read from the days themselves (coach.MEETING_FREE_DAYS): less meeting time overall could
        # come from shorter meetings with no free day, and a moved meeting keeps the total.
        adherence=("meeting_free_days", "up"),
        source="meeting-free days in 76 companies (Laker et al. 2022, MIT Sloan Management Review)",
    ),
    Play(
        "meeting_breaks",
        "Breaks between meetings",
        "Leave 10 to 15 minutes between meetings; end calls early to make room.",
        ("stress_score", "recovery_score"),
        triggers=(("back_to_back", "up"),),
        adherence=("back_to_back", "down"),
        source="breaks between video meetings, EEG (Microsoft Human Factors Lab 2021, 14 people)",
    ),
    Play(
        "step_goal",
        "A team step goal",
        "A shared goal for the team's steps together; nobody is ranked.",
        ("steps", "active_zone_minutes"),
        source="team step games, randomised trial of 602 adults (Patel et al. 2019, JAMA Int Med)",
    ),
)
PLAY = {p.id: p for p in PLAYS}
CUSTOM = "custom"

# What came of a change, from the team's metric during it against the 28 days before.
VERDICT_ORDER = {"better": 0, None: 1, "changed": 2, "no_change": 2, "unclear": 2, "worse": 3}


def verdict(action: TeamAction, evidence: Evidence) -> dict:
    """better, worse, changed (a metric with no good direction), no_change or unclear."""
    label = team_info(action.metric).label
    if not evidence.sufficient:
        return {
            "verdict": "unclear",
            "text": f"Not enough people with data to tell how {label.lower()} went.",
            "evidence_id": evidence.id,
        }
    median = evidence.stats["median_change"]
    if evidence.stats["p_value"] >= FDR or median == 0:
        return {
            "verdict": "no_change",
            "text": f"No clear change in {label.lower()} during it.",
            "evidence_id": evidence.id,
        }
    way = "up" if median > 0 else "down"
    kind = kind_of(action.metric, way)
    moved = evidence.stats["members_up" if way == "up" else "members_down"]
    word = {"improvement": "better", "concern": "worse", "change": "changed"}[kind]
    return {
        "verdict": word,
        "text": (
            f"{label} {'rose' if way == 'up' else 'fell'} during it: median change "
            f"{change_text(action.metric, median)} against the 28 days before "
            f"({moved} of {evidence.stats['members']} people)."
        ),
        "evidence_id": evidence.id,
    }


def plays_for(metric: str) -> list[Play]:
    return [p for p in PLAYS if metric in p.fits]


def start_change(
    db: Session,
    team: Team,
    *,
    play: str,
    metric: str | None,
    title: str | None,
    body: str | None,
    starts_on: date,
    days: int | None,
    source: str,
    status: str,
    now: datetime,
) -> TeamAction:
    """A planned change, from the playbook or the supervisor's own words; callers check the text."""
    if play == CUSTOM:
        if not (title and body and metric):
            raise ValueError("A change of your own needs a title, what it is and what to measure.")
        chosen = None
    elif play in PLAY:
        chosen = PLAY[play]
        title, body = title or chosen.title, body or chosen.body
        metric = metric or chosen.fits[0]
    else:
        raise ValueError(f"Unknown change {play!r}.")
    if metric not in TEAM_METRICS:
        raise ValueError(f"Unknown metric {metric!r}.")
    days = days or (chosen.days if chosen else 14)
    if not CHALLENGE_DAYS[0] <= days <= CHALLENGE_DAYS[1]:
        raise ValueError(f"A change runs {CHALLENGE_DAYS[0]} to {CHALLENGE_DAYS[1]} days.")
    action = TeamAction(
        team_id=team.id,
        kind="challenge",
        title=title.strip()[:80],
        body=body.strip()[:400],
        metric=metric,
        starts_on=starts_on,
        ends_on=starts_on + timedelta(days=days - 1),
        status=status,
        source=source,
        play=play,
        proposed_at=now,
    )
    db.add(action)
    db.flush()
    return action


def ended(db: Session, team: Team, today: date) -> list[TeamAction]:
    return [
        a
        for a in _history(db, team)
        if a.kind == "challenge"
        and a.status == "approved"
        and a.metric
        and a.ends_on is not None
        and a.ends_on < today
    ]


def results_of(db: Session, team: Team, today: date) -> dict[str, dict]:
    """Each ended change's verdict and evidence, by action id, measured on the members there now."""
    from app.teams.agent import challenge_result  # the agent imports the reports this needs
    from app.teams.reports import member_frames

    done = ended(db, team, today)
    if not done:
        return {}
    first = min(a.starts_on for a in done) - timedelta(days=35)
    frames = member_frames(db, team, first, max(a.ends_on for a in done))
    from app.teams import coach, outcome

    found = {}
    for action in done:
        evidence = challenge_result(frames, action)
        described = outcome.describe(action, evidence)
        # `verdict` only orders the old automatic suggestions (`rank`, off in the app); what is
        # shown is the outcome, which makes no judgement.
        result = {
            **verdict(action, evidence),
            "text": described["text"],
            "outcome": described,
            "evidence": evidence,
        }
        play = PLAY.get(action.play or "")
        check = (
            coach.followed(db, team, action, *play.adherence)
            if play is not None and play.adherence is not None
            else None
        )
        if check is not None:
            result["followed"] = check
            result["text"] = f"{result['text']} {check['text']}"
        found[str(action.id)] = result
    return found


def _history(db: Session, team: Team) -> list[TeamAction]:
    return list(db.scalars(select(TeamAction).where(TeamAction.team_id == team.id)))


def _busy(history: list[TeamAction], metric: str, start: date, end: date) -> bool:
    """A proposal still waiting, or an approved change on the same metric that overlaps."""
    for action in history:
        if action.status == "proposed":
            return True
        if (
            action.status == "approved"
            and action.metric == metric
            and action.starts_on is not None
            and action.starts_on <= end
            and action.ends_on >= start
        ):
            return True
    return False


def rank(
    candidates: list[Play],
    history: list[TeamAction],
    results: dict[str, str | None],
    today: date,
    signals: set[tuple[str, str]] = frozenset(),
) -> list[Play]:
    # `results`: an ended change's id -> its verdict (None when it was not followed).
    """Plays in the order to suggest them: one whose calendar trigger fired this week first (it
    targets what the calendar shows), then what went better for this team, untried, made no
    difference, went worse; one declined lately is left out."""
    declined = {
        a.play
        for a in history
        if a.status == "declined"
        and a.decided_at is not None
        and today - a.decided_at.date() < DECLINED_REST
    }
    best: dict[str, int] = {}
    for action in history:
        if action.play and (seen := results.get(str(action.id))) is not None:
            order = VERDICT_ORDER[seen]
            best[action.play] = min(best.get(action.play, order), order)
    kept = [p for p in candidates if p.id not in declined]
    return sorted(
        kept,
        key=lambda p: (
            not any(t in signals for t in p.triggers),
            best.get(p.id, VERDICT_ORDER[None]),
            PLAYS.index(p),
        ),
    )


def verdicts(found: dict[str, dict]) -> dict[str, str | None]:
    """Each ended change's verdict for ranking; None for one the calendar shows was not followed,
    so a change that was not done is not held against it."""
    return {
        key: None if (r.get("followed") or {}).get("followed") is False else r["verdict"]
        for key, r in found.items()
    }


def reasons(priorities: list[dict], warnings: list[dict], today: date) -> list[dict]:
    """Why a change may be suggested, most pressing first: an event coming up like one followed by
    a dip (start it on the event's day), then a concern lasting two weeks or more (start tomorrow).
    """
    found = []
    for warning in warnings:
        for metric in warning["concerns"]:
            found.append(
                {
                    "metric": metric,
                    "starts_on": max(warning["on"], today + timedelta(days=1)),
                    "why": f"before {warning['note']}",
                    "evidence_ids": warning["evidence_ids"],
                }
            )
    for row in priorities:
        if row["kind"] == "concern" and row["status"] == "lasting":
            found.append(
                {
                    "metric": row["metric"],
                    "starts_on": today + timedelta(days=1),
                    "why": f"{team_info(row['metric']).label.lower()} has been lower for a while",
                    "evidence_ids": [row["evidence_id"]],
                }
            )
    return found


def suggest(
    db: Session,
    team: Team,
    priorities: list[dict],
    warnings: list[dict],
    results: dict[str, str | None],
    today: date,
    now: datetime,
    signals: set[tuple[str, str]] = frozenset(),
) -> tuple[TeamAction, dict] | None:
    """At most one change a week, proposed for the supervisor's approval, with why. `signals`
    are the calendar signals that moved this week (coach.signals); a change they point to comes
    first."""
    history = _history(db, team)
    for reason in reasons(priorities, warnings, today):
        candidates = plays_for(reason["metric"])
        if not candidates:
            continue
        ordered = rank(candidates, history, results, today, signals)
        if not ordered:
            continue
        play = ordered[0]
        start = reason["starts_on"]
        if _busy(history, reason["metric"], start, start + timedelta(days=play.days - 1)):
            return None  # one thing at a time: a waiting proposal or a change already running
        action = start_change(
            db,
            team,
            play=play.id,
            metric=reason["metric"],
            title=None,
            body=None,
            starts_on=start,
            days=None,
            source="agent",
            status="proposed",
            now=now,
        )
        return action, reason
    return None
