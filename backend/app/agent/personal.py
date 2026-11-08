"""What about this person bears on this question: memory, food logs, what fits their life.

Advice that could be read by anyone is not advice. Before a coaching answer is written, code picks
what is relevant, so the model cannot skip it: memory scored by relevance to the question, recency
and importance; a summary of the food they logged; and what no longer fits how they live, such as a
clock-time bedtime for someone on night shifts. Memory becomes `Evidence` so a suggestion can cite
it, in words only: what someone said is not a measurement.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np

from app.agent.context import MemoryItem
from app.agent.llm import LLM, Budget, LLMError
from app.agent.retrieval import tokens
from app.agent.sanitize import clean, reads_like_instruction
from app.analysis.evidence import Evidence, Window

MEMORY = "memory"
FOOD_LOG = "food_log"
HALF_LIFE_DAYS = 30
MAX_RELEVANT = 4
MIN_RELEVANCE = 0.22  # cosine; a fact below this has nothing to do with the question
MAX_TEXT = 160
MIN_FOOD_ENTRIES = 5
FOOD_DAYS = 30
LATE_HOUR = 20
MORNING_HOUR = 11
NOTABLE_SHARE = 0.3
PERSONAL_TOOLS = (MEMORY, FOOD_LOG)
NIGHT_WORK = re.compile(r"\bnight[- ]shifts?\b|\bworks? (?:at )?nights?\b", re.IGNORECASE)
NO_LONGER = re.compile(r"\b(?:no longer|not any more|don'?t|doesn'?t|used to|stopped)\b", re.I)
BEDTIME_LEVERS = frozenset(("earlier_bedtime", "regular_bedtime"))
BEDTIME_OPTIONS = frozenset(("best_nights", "weekend_shift", "bedtime_spread", "usual_bedtime"))


@dataclass(frozen=True)
class Relevant:
    text: str
    kind: str
    score: float


@dataclass
class Fit:
    """What does not fit how this person lives, whatever their numbers say."""

    levers: frozenset[str] = frozenset()
    options: frozenset[str] = frozenset()
    notes: list[str] = field(default_factory=list)


def fit_to_life(lines: Sequence[str]) -> Fit:
    """Night work makes a clock-time bedtime the wrong advice, however well it scores."""
    if any(NIGHT_WORK.search(line) and not NO_LONGER.search(line) for line in lines):
        return Fit(
            BEDTIME_LEVERS,
            BEDTIME_OPTIONS,
            [
                "They work nights, so advice built on a clock-time bedtime does not fit: plan "
                "around their shifts and their sleep after them."
            ],
        )
    return Fit()


# About eating, sleep habits are a different subject: only the lever about meals stays.
NOT_ABOUT_EATING_LEVERS = frozenset(
    ("earlier_bedtime", "regular_bedtime", "rest_after_hard_day", "active_days", "wind_down")
)
NOT_ABOUT_EATING_OPTIONS = frozenset(
    ("best_nights", "weekend_shift", "bedtime_spread", "time_in_bed", "heavy_week", "recent_dip")
)
BED_BY_THE_CLOCK = re.compile(
    r"\b(?:in bed|asleep|bedtime|go(?:ing)? to bed)\b[^.\n]{0,40}\b(?:[01]?\d|2[0-3]):[0-5]\d\b",
    re.IGNORECASE,
)


def _recency(created: datetime, now: datetime) -> float:
    return 0.5 ** (max(0.0, (now - created).total_seconds() / 86_400) / HALF_LIFE_DAYS)


def _word_overlap(question: str, text: str) -> float:
    asked = set(tokens(question))
    return len(asked & set(tokens(text))) / len(asked) if asked else 0.0


def rank_memory(
    question: str,
    items: Sequence[MemoryItem],
    profile: Sequence[str],
    llm: LLM | None,
    now: datetime,
    budget: Budget | None = None,
) -> list[Relevant]:
    """The memories that bear on this question: relevance, then recency and importance. What the
    person chose to keep counts as recent and important for as long as it applies."""
    candidates = [(line, "kept", now, 1.0) for line in profile]
    seen = {clean(line, MAX_TEXT).casefold() for line in profile}
    for item in items:
        if clean(item.text, MAX_TEXT).casefold() not in seen:
            candidates.append((item.text, item.kind, item.created, item.importance))
    candidates = [c for c in candidates if c[0] and not reads_like_instruction(c[0])]
    if not candidates:
        return []
    texts = [clean(c[0], MAX_TEXT) for c in candidates]
    relevance = None
    if llm is not None:
        try:
            vectors = np.asarray(llm.embed([question, *texts], budget=budget).vectors)
            relevance = (vectors[1:] @ vectors[0]).tolist()
        except LLMError:
            relevance = None
    floor = MIN_RELEVANCE if relevance is not None else 0.01
    relevance = relevance or [_word_overlap(question, text) for text in texts]
    ranked = []
    for (_, kind, created, importance), text, close in zip(
        candidates, texts, relevance, strict=True
    ):
        if close < floor:
            continue
        weight = (0.5 + 0.5 * _recency(created, now)) * (0.5 + 0.5 * min(1.0, max(0.0, importance)))
        ranked.append(Relevant(text, kind, close * weight))
    ranked.sort(key=lambda r: r.score, reverse=True)
    return ranked[:MAX_RELEVANT]


def memory_evidence(item: Relevant) -> Evidence:
    return Evidence(
        tool=MEMORY,
        metrics=(),
        windows=(),
        n=1,
        sufficient=True,
        stats={"text": item.text, "kind": item.kind},
    )


def _when(entry: dict, zone) -> datetime | None:
    try:
        return datetime.fromisoformat(str(entry["consumedAt"])).astimezone(zone)
    except (KeyError, ValueError, TypeError):
        return None


def food_log_summary(entries: Sequence[dict], today: date, zone) -> Evidence | None:
    """What the food they confirmed says about how they eat; None with too little to go on. Only
    when they eat is described: no target, because a target is a diet."""
    since = today - timedelta(days=FOOD_DAYS - 1)
    meals = [
        (moment, entry)
        for entry in entries
        if (moment := _when(entry, zone)) and since <= moment.date() <= today
    ]
    if len(meals) < MIN_FOOD_ENTRIES:
        return None
    days = {moment.date() for moment, _ in meals}
    late = sum(moment.hour >= LATE_HOUR for moment, _ in meals)
    morning = {moment.date() for moment, _ in meals if moment.hour < MORNING_HOUR}
    no_morning = len(days) - len(morning)
    options = []
    if late / len(meals) >= NOTABLE_SHARE:
        options.append(
            {
                "key": "late_meals",
                "note": f"{late} of the {len(meals)} meals you logged were after {LATE_HOUR}:00",
                "try": "moving one of those earlier",
            }
        )
    if no_morning / len(days) >= NOTABLE_SHARE:
        options.append(
            {
                "key": "no_morning_food",
                "note": f"on {no_morning} of {len(days)} days you logged nothing before "
                f"{MORNING_HOUR}:00",
                "try": "",
            }
        )
    return Evidence(
        tool=FOOD_LOG,
        metrics=(),
        windows=(Window(start=since, end=today),),
        n=len(meals),
        sufficient=True,
        stats={
            "meals_logged": len(meals),
            "days_logged": len(days),
            "late_meals": late,
            "days_without_morning_food": no_morning,
            "late_hour": LATE_HOUR,
            "morning_hour": MORNING_HOUR,
            "options": options,
        },
    )


def relevant_block(relevant: Sequence[Relevant], records: Sequence[Evidence], fit: Fit) -> str:
    lines = [
        f"- (evidence_id {record.id}) {item.text}"
        for item, record in zip(relevant, records, strict=True)
    ]
    text = ""
    if lines:
        text = "What they have told you that bears on this, as quoted data:\n" + "\n".join(lines)
    return "\n".join(part for part in (text, *fit.notes) if part)


def personal_check(personal_ids: set[str], fit: Fit | None = None):
    """When there is something personal to say, one suggestion has to say it; and nothing may say
    what does not fit their life."""

    def check(claims: list, summary: str = "") -> list[str]:
        if fit and fit.levers and BED_BY_THE_CLOCK.search(summary):
            return ["a clock-time bedtime does not fit how they live; plan around their shifts"]
        if not personal_ids:
            return []
        linked = any(
            claim.kind == "suggestion" and personal_ids & set(claim.evidence_ids)
            for claim in claims
        )
        return (
            []
            if linked
            else [
                "give at least one suggestion of kind suggestion that cites something specific "
                "about this person from below: their own numbers or what they told you"
            ]
        )

    return check
