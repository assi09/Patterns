"""The nightly team pulse: one question to every team member, "How demanding was your day?"
(1 light to 5 very heavy), answered in the app.

The watch cannot say how heavy a week felt: the app's physical stress score showed no link with
self-reported stress (median rho -0.03 on PMData). The pulse is the team's own word on it. A
supervisor only sees a week's team figures, from at least MIN_MEMBERS people who answered that
week, never one person's answer and never a single day, which a few people could be picked out of.
Each person's week is their own average first, so someone who answers every night does not weigh
more than someone who answers twice.
"""

import uuid
from datetime import date, timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.evidence import Evidence, Window
from app.analysis.team import MIN_MEMBERS
from app.db.models import Pulse, Team, TeamMembership

QUESTION = "How demanding was your day?"
SCALE = ("Light", "Easy", "Moderate", "Heavy", "Very heavy")
WEEKS_BEFORE = 4  # the weeks a week is compared with


class PulseRejected(ValueError):
    """An answer that cannot be kept; the message is safe to show."""


def asked(db: Session, user_id: uuid.UUID) -> bool:
    """Whether the person is in a team, and so is asked."""
    return (
        db.scalar(
            select(TeamMembership.team_id).where(
                TeamMembership.user_id == user_id, TeamMembership.left_at.is_(None)
            )
        )
        is not None
    )


def answer_of(db: Session, user_id: uuid.UUID, day: date) -> int | None:
    found = db.get(Pulse, (user_id, day))
    return found.rating if found else None


def save(db: Session, user_id: uuid.UUID, day: date, rating: int, *, today: date) -> Pulse:
    """Sets or changes today's answer: only today's, only from someone in a team."""
    if day != today:
        raise PulseRejected("Only today's answer can be set or changed.")
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        raise PulseRejected("The answer is a whole number from 1 to 5.")
    if not asked(db, user_id):
        raise PulseRejected("The daily question is for people in a team.")
    found = db.get(Pulse, (user_id, day))
    if found is None:
        found = Pulse(user_id=user_id, day=day, rating=rating)
        db.add(found)
    else:
        found.rating = rating
    db.flush()
    return found


def _members(db: Session, team: Team) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(TeamMembership.user_id).where(
                TeamMembership.team_id == team.id, TeamMembership.left_at.is_(None)
            )
        )
    )


def week_figures(db: Session, team: Team, week: Window) -> dict:
    """One week's team figures: how many people answered, and the team's average, only from at
    least MIN_MEMBERS people; nothing else, never a person's own answer."""
    rows = db.execute(
        select(Pulse.user_id, Pulse.rating).where(
            Pulse.user_id.in_(_members(db, team)),
            Pulse.day >= week.start,
            Pulse.day <= week.end,
        )
    ).all()
    by_person: dict[uuid.UUID, list[int]] = {}
    for user_id, rating in rows:
        by_person.setdefault(user_id, []).append(rating)
    people = len(by_person)
    figures = {"start": week.start, "end": week.end, "respondents": people, "mean": None}
    if people >= MIN_MEMBERS:
        figures["mean"] = round(mean(mean(r) for r in by_person.values()), 2)
    return figures


def weeks(db: Session, team: Team, last_week: Window, count: int = WEEKS_BEFORE + 1) -> list[dict]:
    """The last `count` full weeks, oldest first."""
    found = []
    for back in range(count - 1, -1, -1):
        start = last_week.start - timedelta(weeks=back)
        found.append(week_figures(db, team, Window(start=start, end=start + timedelta(days=6))))
    return found


def pulse_evidence(db: Session, team: Team, last_week: Window) -> Evidence:
    """The week's pulse against the weeks before, for the team agent to cite: descriptive, with
    each figure only from a week at least MIN_MEMBERS people answered."""
    found = weeks(db, team, last_week)
    latest, before = found[-1], [w["mean"] for w in found[:-1] if w["mean"] is not None]
    stats: dict = {
        "question": QUESTION,
        "scale": "1 light to 5 very heavy",
        "respondents": latest["respondents"],
        "minimum_members": MIN_MEMBERS,
    }
    if latest["mean"] is not None:
        stats["mean"] = latest["mean"]
        if before:
            stats["before_mean"] = round(mean(before), 2)
            stats["weeks_before"] = len(before)
    return Evidence(
        tool="team_pulse",
        metrics=(),
        windows=(last_week,),
        n=latest["respondents"],
        sufficient=latest["mean"] is not None,
        stats=stats,
    )
