"""The pilot report: totals and rates only, computed where the data lives.

Run inside the deployed `api` service, which already reaches the database (it has no public port):
`python -m app.pilot_report --since 2026-11-12 --until 2026-11-22 > pilot.json`. Nothing here
prints an email, a message, a claim's text or a health value: people are "person 1", "person 2"…
in an order that says nothing about them, per-person rows hold counts only, and statistics about
someone's data (the recovery score against their check-ins) are reported across people, never
one by one. The owner and other admins are left out unless asked for.

Accuracy is each stored, verified claim checked against the independent answer key
(`app.oracle`) on that person's own data, over the very periods its evidence covered. Only claims
the key can judge are counted (changes, no-changes, weekend gaps and links); the rest are listed
as not checkable. That shows the numbers are right, not that nothing was missed, so recall checks
the "has anything changed" answers against what the key finds changed in the question's area.
Answers from before stored traces existed have no trace and are counted as such.
"""

import argparse
import hashlib
import json
import sys
import uuid
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from statistics import mean, median

import pandas as pd
from scipy import stats
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import oracle
from app.agent.experts import EXPERTS
from app.analysis.day import RECOVERY, with_scores
from app.analysis.habits import CHECKIN_RATING
from app.config import settings
from app.db.daily import load_daily
from app.db.models import (
    Alarm,
    AnswerTrace,
    ChatMessage,
    CheckIn,
    EvidenceRecord,
    MemoryFact,
    Reminder,
    Team,
    TeamAction,
    TeamAlert,
    TeamChatMessage,
    TeamMembership,
    User,
)
from app.db.session import session_scope

SOURCE = "google_health"
MIN_PAIRED_DAYS = 7  # check-ins with a recovery score before a person's link is worth a number
SUCCESS = ("answered", "answered_in_part")
RECENT_DAYS, BASELINE_DAYS = 14, 28  # what "lately" means when a question names no period


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _spread(values: Iterable[float], digits: int = 1) -> dict:
    """Count, mean, median, 90th percentile and maximum; None for each when empty."""
    values = sorted(values)
    if not values:
        return {"n": 0, "mean": None, "median": None, "p90": None, "max": None}
    at = min(len(values) - 1, round(0.9 * (len(values) - 1)))
    return {
        "n": len(values),
        "mean": round(mean(values), digits),
        "median": round(median(values), digits),
        "p90": round(values[at], digits),
        "max": round(values[-1], digits),
    }


def _pseudonyms(ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    """ "person 1", "person 2"… ordered by a hash of the id, which says nothing about the person."""
    ordered = sorted(set(ids), key=lambda i: hashlib.sha256(i.bytes).hexdigest())
    return {person: f"person {at}" for at, person in enumerate(ordered, start=1)}


def participants(db: Session, include_admins: bool = False) -> list[User]:
    admins = {email.strip().lower() for email in settings.admin_emails}
    people = db.scalars(select(User).where(User.status == "approved")).all()
    return [p for p in people if include_admins or p.email.lower() not in admins]


# Usage, success, latency and cost


def _answers(db: Session, people: set[uuid.UUID], start: datetime, end: datetime) -> list:
    rows = db.execute(
        select(ChatMessage, AnswerTrace)
        .outerjoin(AnswerTrace, AnswerTrace.message_id == ChatMessage.id)
        .where(ChatMessage.role == "assistant", ChatMessage.user_id.in_(people))
    ).all()
    return [(m, t) for m, t in rows if start <= _aware(m.created_at) < end]


def _questions(db: Session, people: set[uuid.UUID], start: datetime, end: datetime) -> list:
    rows = db.scalars(
        select(ChatMessage).where(ChatMessage.role == "user", ChatMessage.user_id.in_(people))
    ).all()
    return [m for m in rows if start <= _aware(m.created_at) < end]


def _traced(traces: list[AnswerTrace]) -> dict:
    outcomes = Counter(t.outcome for t in traces)
    asked = len(traces) - outcomes["refused"]
    return {
        "answers": len(traces),
        "outcomes": dict(sorted(outcomes.items())),
        # Of the questions it was allowed to answer: refusals are by design, not failures.
        "success_rate": _rate(sum(outcomes[o] for o in SUCCESS), asked),
        "refusal_rate": _rate(outcomes["refused"], len(traces)),
        "latency_s": _spread((t.latency_ms / 1000 for t in traces), 2),
        "model_s": _spread(((t.stages_ms or {}).get("model", 0) / 1000 for t in traces), 2),
        "model_calls": _spread(t.model_calls for t in traces),
        "tool_calls": _spread(t.tool_calls for t in traces),
        "with_tool_errors": sum(1 for t in traces if t.tool_errors),
        "with_repairs": sum(1 for t in traces if t.repair_rounds),
        "rejected_claims": sum(t.rejected_claims for t in traces),
        "summary_fell_back": sum(1 for t in traces if t.summary_fell_back),
        "guard_down": sum(1 for t in traces if t.guard_down),
    }


def _thumbs(ratings: list[str | None]) -> dict:
    given = [r for r in ratings if r]
    return {
        "rated": len(given),
        "rated_share": _rate(len(given), len(ratings)),
        "up": given.count("up"),
        "down": given.count("down"),
        "up_rate": _rate(given.count("up"), len(given)),
    }


def chat_section(db, people, names, start, end, days: int) -> dict:
    answers = _answers(db, people, start, end)
    questions = _questions(db, people, start, end)
    traces = [t for _, t in answers if t is not None]
    per_person = Counter(q.user_id for q in questions)
    active = {(q.user_id, _aware(q.created_at).date()) for q in questions}
    costs = [m.cost_usd or 0.0 for m, _ in answers]
    return {
        "questions": len(questions),
        "people_who_asked": len(per_person),
        "questions_per_person_per_day": _rate(len(questions), len(people) * days),
        "questions_per_active_day": _rate(len(questions), len(active)),
        "question_types": dict(Counter(t.question_type or "unknown" for t in traces).most_common()),
        "untraced_answers": len(answers) - len(traces),
        **_traced(traces),
        "cost_usd": {
            "total": round(sum(costs), 4),
            "per_answer": _spread(costs, 4),
            "per_person_per_day": round(sum(costs) / (len(people) * days), 4) if people else None,
        },
        "thumbs": _thumbs([m.rating for m, _ in answers]),
        "thumbs_by_outcome": {
            outcome: _thumbs([m.rating for m, t in answers if t and t.outcome == outcome])
            for outcome in sorted({t.outcome for t in traces})
        },
        "per_person": [
            {
                "person": names[person],
                "questions": per_person[person],
                "active_days": sum(1 for who, _ in active if who == person),
            }
            for person in sorted(people, key=lambda p: names[p])
        ],
    }


# Accuracy against the independent answer key


def _window(payload: dict, at: int) -> tuple[date, date] | None:
    windows = payload.get("windows") or []
    if len(windows) <= at:
        return None
    return date.fromisoformat(windows[at]["start"]), date.fromisoformat(windows[at]["end"])


def judge(claim: dict, evidence: dict[str, dict], frame: pd.DataFrame) -> tuple[str, str | None]:
    """("agree" | "disagree" | "unchecked", the tool judged) for one stored claim."""
    kind, direction = claim.get("kind"), claim.get("direction")
    if kind not in ("change", "no_change", "association"):
        return "unchecked", None
    for evidence_id in claim.get("evidence_ids") or ():
        payload = evidence.get(evidence_id)
        if not payload:
            continue
        tool, metrics = payload.get("tool"), payload.get("metrics") or []
        key = None
        if tool == "compare_windows" and kind != "association" and _window(payload, 1):
            key = oracle.change_between(frame, metrics[0], _window(payload, 0), _window(payload, 1))
        elif tool == "weekday_split" and kind != "association" and _window(payload, 0):
            key = oracle.weekend_gap_between(frame, metrics[0], *_window(payload, 0))
        elif tool == "correlate" and kind in ("association", "no_change") and _window(payload, 0):
            lag = (payload.get("stats") or {}).get("best_lag") or 0
            linked = oracle.link_between(frame, *metrics[:2], *_window(payload, 0), lag=lag)
            key = {"positive": "up", "negative": "down"}.get(linked, linked)
        if key is None:
            continue
        said = "none" if kind == "no_change" else direction
        return ("agree" if key == said else "disagree"), tool
    return "unchecked", None


def accuracy_section(db, people, start, end, frames: dict) -> dict:
    verdicts: Counter = Counter()
    by_tool: dict[str, Counter] = {}
    by_kind: dict[str, Counter] = {}
    for message, _ in _answers(db, people, start, end):
        claims = message.claims or []
        if not claims:
            continue
        frame = frames.get(message.user_id)
        ids = {i for c in claims for i in c.get("evidence_ids") or ()}
        stored = {
            row.id: row.payload
            for row in db.scalars(
                select(EvidenceRecord).where(
                    EvidenceRecord.user_id == message.user_id, EvidenceRecord.id.in_(ids)
                )
            )
        }
        for claim in claims:
            verdict, tool = (
                judge(claim, stored, frame) if frame is not None else ("unchecked", None)
            )
            verdicts[verdict] += 1
            if tool:
                by_tool.setdefault(tool, Counter())[verdict] += 1
            by_kind.setdefault(claim.get("kind") or "unknown", Counter())[verdict] += 1
    checked = verdicts["agree"] + verdicts["disagree"]
    return {
        "claims": sum(verdicts.values()),
        "checked": checked,
        "agree": verdicts["agree"],
        "disagree": verdicts["disagree"],
        "unchecked": verdicts["unchecked"],
        "agreement": _rate(verdicts["agree"], checked),
        "by_tool": {tool: dict(c) for tool, c in sorted(by_tool.items())},
        "by_kind": {kind: dict(c) for kind, c in sorted(by_kind.items())},
        "note": "Claims checked against app.oracle at 0.05 over their evidence's own periods; the "
        "agent corrects for the tests in a run, so a borderline change it calls unclear can count "
        "as a disagreement.",
    }


# What a "has anything changed" answer missed


def _area(trace: AnswerTrace) -> tuple[str, ...]:
    """The metrics the question was about: the answering expert's, or every expert's."""
    route = next((s for s in trace.steps or () if s.get("type") == "route"), {})
    expert = EXPERTS.get(route.get("expert") or "")
    if expert and expert.owns:
        return expert.owns
    return tuple(m for e in EXPERTS.values() for m in e.owns)


def changes_in(frame: pd.DataFrame, metrics: Iterable[str], end) -> dict[str, str]:
    """What the answer key finds changed by `end`: {metric: direction}, after the correction."""
    found = {m: oracle.change_p(frame, m, end, RECENT_DAYS, BASELINE_DAYS) for m in metrics}
    tested = {m: p for m, (_, p) in found.items() if p is not None}
    return {m: found[m][0] for m in oracle.discoveries(tested)}


def recall_section(db, people, start, end, frames: dict) -> dict:
    counts: Counter = Counter()
    for message, trace in _answers(db, people, start, end):
        if trace is None or trace.question_type != "change" or trace.outcome not in SUCCESS:
            continue
        frame = frames.get(message.user_id)
        if frame is None:
            continue
        asked_on = pd.Timestamp(_aware(message.created_at).date())
        last_day = frame.index[frame.index < asked_on].max()  # the data the answer could see
        if pd.isna(last_day):
            continue
        changed = changes_in(frame, _area(trace), last_day)
        claims = message.claims or []
        named = {c["metric"]: c.get("direction") for c in claims if c.get("kind") == "change"}
        counts["questions"] += 1
        counts["changes"] += len(changed)
        counts["named"] += sum(1 for m, d in changed.items() if named.get(m) == d)
        counts["wrong_direction"] += sum(
            1 for m, d in changed.items() if m in named and named[m] != d
        )
        counts["missed"] += sum(1 for m in changed if m not in named)
        counts["said_changed_key_did_not"] += sum(1 for m in named if m not in changed)
        if not changed:
            counts["nothing_changed"] += 1
            counts["nothing_changed_and_said_so"] += 0 if named else 1
    return {
        "questions_checked": counts["questions"],
        "changes_found_by_key": counts["changes"],
        "named": counts["named"],
        "wrong_direction": counts["wrong_direction"],
        "missed": counts["missed"],
        "recall": _rate(counts["named"], counts["changes"]),
        "said_changed_key_did_not": counts["said_changed_key_did_not"],
        "nothing_changed": counts["nothing_changed"],
        "nothing_changed_and_said_so": counts["nothing_changed_and_said_so"],
        "note": f"Answered change questions only; the key compares the last {RECENT_DAYS} days "
        f"with the {BASELINE_DAYS} before, over the answering expert's metrics, corrected for "
        "testing them all at once. A question about another period is still judged on this one.",
    }


# The recovery score against how people said they felt


def recovery_section(db, people, start, end, frames: dict) -> dict:
    rhos, too_few = [], 0
    for person in people:
        frame = frames.get(person)
        ratings = {
            c.day: c.rating
            for c in db.scalars(select(CheckIn).where(CheckIn.user_id == person))
            if start.date() <= c.day < end.date()
        }
        if not ratings:
            continue
        if frame is None or RECOVERY not in frame.columns:
            too_few += 1
            continue
        pairs = pd.DataFrame(
            {RECOVERY: frame[RECOVERY], CHECKIN_RATING: pd.Series(ratings).rename(pd.Timestamp)}
        ).dropna()
        if len(pairs) < MIN_PAIRED_DAYS or pairs.nunique().min() < 2:
            too_few += 1
            continue
        rho, p = stats.spearmanr(pairs[RECOVERY], pairs[CHECKIN_RATING])
        rhos.append((float(rho), float(p), len(pairs)))
    return {
        "people_with_check_ins": len(rhos) + too_few,
        "people_compared": len(rhos),
        "too_few_days": too_few,
        "min_days": MIN_PAIRED_DAYS,
        "days_per_person": _spread((n for _, _, n in rhos)),
        "median_rho": round(median(r for r, _, _ in rhos), 2) if rhos else None,
        "positive": sum(1 for r, _, _ in rhos if r > 0),
        "positive_significant": sum(1 for r, p, _ in rhos if r > 0 and p < oracle.ALPHA),
        "negative_significant": sum(1 for r, p, _ in rhos if r < 0 and p < oracle.ALPHA),
    }


# What the agent proposed and how people responded


def proposals_section(db, people, start, end) -> dict:
    def within(rows, at="created_at"):
        return [r for r in rows if start <= _aware(getattr(r, at)) < end]

    alarms = within(db.scalars(select(Alarm).where(Alarm.user_id.in_(people))).all())
    sent = [a for a in alarms if a.status == "sent"]
    feedback = Counter(a.feedback for a in sent if a.feedback)
    reminders = within(
        db.scalars(
            select(Reminder).where(Reminder.user_id.in_(people), Reminder.source == "agent")
        ).all()
    )
    facts = within(db.scalars(select(MemoryFact).where(MemoryFact.user_id.in_(people))).all())
    asked = [f for f in facts if f.status in ("proposed", "approved", "declined")]
    return {
        "alerts": {
            "raised": len(alarms),
            "sent": len(sent),
            "useful": feedback["useful"],
            "not_useful": feedback["not_useful"],
            "useful_rate": _rate(feedback["useful"], sum(feedback.values())),
        },
        "agent_reminders": {
            "proposed": len(reminders),
            "kept": sum(1 for r in reminders if r.status in ("active", "paused", "done")),
            "declined": sum(1 for r in reminders if r.status == "declined"),
        },
        "memory_cards": {
            "shown": len(asked),
            "kept": sum(1 for f in asked if f.status == "approved"),
            "declined": sum(1 for f in asked if f.status == "declined"),
            "waiting": sum(1 for f in asked if f.status == "proposed"),
        },
    }


# Teams


def team_section(db, people, start, end) -> dict:
    teams = db.scalars(select(Team)).all()
    rows = []
    for team in teams:
        members = db.scalars(select(TeamMembership).where(TeamMembership.team_id == team.id)).all()
        in_pilot = [m for m in members if m.user_id in people]
        if not in_pilot:
            continue
        alerts = [
            a
            for a in db.scalars(select(TeamAlert).where(TeamAlert.team_id == team.id))
            if start <= _aware(a.raised_at) < end
        ]
        actions = [
            a
            for a in db.scalars(select(TeamAction).where(TeamAction.team_id == team.id))
            if start <= _aware(a.proposed_at) < end
        ]
        answers = db.execute(
            select(TeamChatMessage, AnswerTrace)
            .outerjoin(AnswerTrace, AnswerTrace.team_message_id == TeamChatMessage.id)
            .where(TeamChatMessage.team_id == team.id, TeamChatMessage.role == "agent")
        ).all()
        answers = [(m, t) for m, t in answers if start <= _aware(m.created_at) < end]
        rows.append(
            {
                "team": f"team {len(rows) + 1}",
                "members": sum(1 for m in members if m.left_at is None),
                "alerts_raised": len(alerts),
                "proposals": dict(Counter(a.status for a in actions)),
                "agent": _traced([t for _, t in answers if t is not None]),
                "thumbs": _thumbs([m.rating for m, _ in answers]),
                "agent_cost_usd": round(sum(m.cost_usd or 0.0 for m, _ in answers), 4),
            }
        )
    return {"teams": rows}


def report(db: Session, since: date, until: date, include_admins: bool = False) -> dict:
    start = datetime.combine(since, time(), UTC)
    end = datetime.combine(until + timedelta(days=1), time(), UTC)  # until is included
    days = (until - since).days + 1
    people = {p.id for p in participants(db, include_admins)}
    names = _pseudonyms(people)
    frames = {}
    for person in people:
        frame = load_daily(db, person, SOURCE)
        if not frame.empty:
            frames[person] = with_scores(frame)
    return {
        "period": {"since": since.isoformat(), "until": until.isoformat(), "days": days},
        "people": len(people),
        "people_with_data": len(frames),
        "chat": chat_section(db, people, names, start, end, days),
        "accuracy": accuracy_section(db, people, start, end, frames),
        "recall": recall_section(db, people, start, end, frames),
        "recovery_vs_check_ins": recovery_section(db, people, start, end, frames),
        "proposals": proposals_section(db, people, start, end),
        "teams": team_section(db, people, start, end),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="The pilot's totals; prints JSON, nothing else.")
    parser.add_argument("--since", type=date.fromisoformat, required=True)
    parser.add_argument("--until", type=date.fromisoformat, default=None, help="included")
    parser.add_argument("--include-admins", action="store_true", help="the owner too")
    args = parser.parse_args(argv)
    until = args.until or datetime.now(UTC).date()
    if until < args.since:
        parser.error("--until is before --since")
    with session_scope() as db:
        result = report(db, args.since, until, args.include_admins)
        db.rollback()  # it only reads; nothing is ever written
    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
