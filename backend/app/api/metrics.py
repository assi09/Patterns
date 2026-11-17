"""The operations page's numbers, for admins: how the agent is used, how well and how fast it
answers, what it costs against the caps, how syncing goes, and how often people answer the daily
questions.

Everything is a total, a rate or a spread over the pilot's people, built on the pilot report
(`app.pilot_report`), which never names a person or prints a message, a claim or a health value.
The per-person rows of that report are dropped here: the page shows the whole pilot only. Admins
are left out by default, so the owner's own use does not count as the pilot's.
"""

import time as clock
from collections import Counter
from datetime import UTC, datetime, time, timedelta
from statistics import median
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app import pilot_report
from app.api.auth import Db, Now, admin_user
from app.config import settings
from app.db.models import (
    AnswerTrace,
    ChatMessage,
    CheckIn,
    GoogleConnection,
    Pulse,
    Spend,
    SyncRun,
    TeamMembership,
    User,
)

router = APIRouter(prefix="/admin", tags=["metrics"])

PERIODS = (1, 7, 14, 30)
CACHE_SECONDS = 60  # the accuracy check reads every person's data: not on every refresh
_cache: dict[tuple, tuple[float, dict]] = {}
# Maps whose keys are data (an outcome, a question type), not field names: kept as they are.
DATA_KEYS = {"outcomes", "question_types", "statuses", "by_tool", "by_kind", "thumbs_by_outcome"}


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


def camel(value, keep: bool = False):
    """Field names in camelCase, as the rest of the API sends them."""
    if isinstance(value, dict):
        return {
            (k if keep else _camel(k)): camel(v, keep=k in DATA_KEYS or keep)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [camel(v, keep) for v in value]
    return value


def _day_series(db, people: set, start: datetime, days: int) -> list[dict]:
    """Per day: questions, answers, success, median latency, thumbs and every dollar spent."""
    end = start + timedelta(days=days)
    rows = {
        d: {"questions": 0, "answers": 0, "answered": 0, "latency": [], "up": 0, "down": 0}
        for d in (start.date() + timedelta(days=i) for i in range(days))
    }
    for message in pilot_report._questions(db, people, start, end):
        rows[pilot_report._aware(message.created_at).date()]["questions"] += 1
    for message, trace in pilot_report._answers(db, people, start, end):
        row = rows[pilot_report._aware(message.created_at).date()]
        row["answers"] += 1
        if message.rating in ("up", "down"):
            row[message.rating] += 1
        if trace is not None:
            row["answered"] += trace.outcome in pilot_report.SUCCESS
            row["latency"].append(trace.latency_ms / 1000)
    spent = db.execute(
        select(Spend.at, Spend.cost_usd).where(
            Spend.user_id.in_(people), Spend.at >= start, Spend.at < end
        )
    ).all()
    cost: Counter = Counter()
    for at, usd in spent:
        cost[pilot_report._aware(at).date()] += usd
    return [
        {
            "day": day.isoformat(),
            "questions": row["questions"],
            "answers": row["answers"],
            "success_rate": pilot_report._rate(row["answered"], len(row["latency"])),
            "median_latency_s": round(median(row["latency"]), 2) if row["latency"] else None,
            "thumbs_up": row["up"],
            "thumbs_down": row["down"],
            "cost_usd": round(cost[day], 4),
        }
        for day, row in rows.items()
    ]


def _spend(db, people: set, now: datetime) -> dict:
    """Today's spending against the daily caps, and everything so far against the overall cap."""
    today = datetime.combine(now.date(), time(), UTC)
    by_person = dict(
        db.execute(
            select(Spend.user_id, func.sum(Spend.cost_usd))
            .where(Spend.at >= today)
            .group_by(Spend.user_id)
        ).all()
    )
    today_total = sum(by_person.values())
    pilot_today = [v for k, v in by_person.items() if k in people]
    everything = db.scalar(select(func.sum(Spend.cost_usd))) or 0.0
    return {
        "today_usd": round(today_total, 4),
        "today_cap_usd": settings.chat_daily_cap_total_usd,
        "highest_person_today_usd": round(max(pilot_today, default=0.0), 4),
        "person_cap_usd": settings.chat_daily_cap_per_user_usd,
        "people_at_their_cap_today": sum(
            1 for v in pilot_today if v >= settings.chat_daily_cap_per_user_usd
        ),
        "all_time_usd": round(everything, 4),
        "all_time_cap_usd": settings.llm_spend_cap_usd,
    }


def _syncs(db, people: set, start: datetime, end: datetime) -> dict:
    runs = db.scalars(
        select(SyncRun).where(
            SyncRun.user_id.in_(people), SyncRun.started_at >= start, SyncRun.started_at < end
        )
    ).all()
    seconds = [
        (pilot_report._aware(r.finished_at) - pilot_report._aware(r.started_at)).total_seconds()
        for r in runs
        if r.finished_at is not None and r.status == "succeeded"
    ]
    statuses = Counter(r.status for r in runs)
    connections = Counter(
        db.scalars(
            select(GoogleConnection.status).where(GoogleConnection.user_id.in_(people))
        ).all()
    )
    return {
        "runs": len(runs),
        "statuses": dict(sorted(statuses.items())),
        "success_rate": pilot_report._rate(statuses["succeeded"], len(runs)),
        "seconds": pilot_report._spread(seconds, 1),
        "connected": connections["active"],
        "reconnect_needed": connections["reconnect_needed"],
    }


def _engagement(db, people: set, start: datetime, days: int) -> dict:
    """How often people answer the morning check-in and, in a team, the evening question."""
    first, last = start.date(), start.date() + timedelta(days=days - 1)
    check_ins = db.scalar(
        select(func.count())
        .select_from(CheckIn)
        .where(CheckIn.user_id.in_(people), CheckIn.day >= first, CheckIn.day <= last)
    )
    members = set(
        db.scalars(
            select(TeamMembership.user_id).where(
                TeamMembership.user_id.in_(people), TeamMembership.left_at.is_(None)
            )
        ).all()
    )
    pulses = db.scalar(
        select(func.count())
        .select_from(Pulse)
        .where(Pulse.user_id.in_(members), Pulse.day >= first, Pulse.day <= last)
    )
    return {
        "check_ins": check_ins,
        "check_in_rate": pilot_report._rate(check_ins, len(people) * days),
        "team_members": len(members),
        "evening_answers": pulses,
        "evening_rate": pilot_report._rate(pulses, len(members) * days),
    }


def metrics(db, now: datetime, days: int, include_admins: bool) -> dict:
    until = now.date()
    since = until - timedelta(days=days - 1)
    start = datetime.combine(since, time(), UTC)
    end = datetime.combine(until + timedelta(days=1), time(), UTC)
    base = pilot_report.report(db, since, until, include_admins)
    people = {p.id for p in pilot_report.participants(db, include_admins)}
    chat = {k: v for k, v in base["chat"].items() if k != "per_person"}
    return {
        "period": base["period"],
        "made_at": now.isoformat(),
        "people": {
            "approved": base["people"],
            "with_data": base["people_with_data"],
            "asked_this_period": chat["people_who_asked"],
            "waiting_for_approval": db.scalar(
                select(func.count()).select_from(User).where(User.status == "pending")
            ),
        },
        "chat": chat,
        "days": _day_series(db, people, start, days),
        "spend": _spend(db, people, now),
        "accuracy": base["accuracy"],
        "recall": base["recall"],
        "syncs": _syncs(db, people, start, end),
        "engagement": _engagement(db, people, start, days),
        "proposals": base["proposals"],
        "teams": base["teams"],
        "traced_answers_all_time": db.scalar(select(func.count()).select_from(AnswerTrace)),
        "answers_all_time": db.scalar(
            select(func.count()).select_from(ChatMessage).where(ChatMessage.role == "assistant")
        ),
    }


@router.get("/metrics")
def get_metrics(
    db: Db,
    now: Now,
    _: Annotated[User, Depends(admin_user)],
    days: Annotated[int, Query(ge=1, le=30)] = 7,
    include_admins: bool = False,
) -> dict:
    """Totals for the operations page; cached a minute, as the accuracy check reads everyone's
    data."""
    key = (days, include_admins, now.date())
    cached = _cache.get(key)
    if cached and clock.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    result = camel(metrics(db, now, days, include_admins))
    _cache[key] = (clock.monotonic(), result)
    return result
