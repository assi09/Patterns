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
    no_clock_bedtime: bool = False


@dataclass(frozen=True)
class LifeRule:
    says: re.Pattern
    levers: frozenset[str]
    options: frozenset[str]
    note: str
    no_clock_bedtime: bool = False


REGULAR = frozenset(("regular_bedtime",))
ROUTINE_OPTIONS = frozenset(("weekend_shift", "bedtime_spread"))
LIFE_RULES = (
    LifeRule(
        NIGHT_WORK,
        BEDTIME_LEVERS,
        BEDTIME_OPTIONS,
        "They work nights, so advice built on a clock-time bedtime does not fit: plan around "
        "their shifts and their sleep after them.",
        no_clock_bedtime=True,
    ),
    LifeRule(
        re.compile(r"\b(?:newborn|new baby|baby at home|feed(?:s|ing)? the baby)\b", re.I),
        REGULAR,
        ROUTINE_OPTIONS | frozenset(("best_nights",)),
        "Their nights are set by a baby, so a regular bedtime is not theirs to choose: keep to "
        "what they can control, such as naps and sharing the night feeds.",
    ),
    LifeRule(
        re.compile(r"\b(?:injur\w*|sprain\w*|broke|broken|torn|hurt (?:my|their))\b", re.I),
        frozenset(("active_days",)),
        frozenset(("quiet_day", "heavy_week")),
        "They are injured, so nothing that asks them to move more or train harder.",
    ),
    LifeRule(
        re.compile(r"\b(?:travel\w*|on a trip|abroad|jet ?lag|flying)\b", re.I),
        REGULAR,
        ROUTINE_OPTIONS,
        "They are travelling, so their usual routine is not a fair yardstick for now.",
    ),
)


def fit_to_life(lines: Sequence[str]) -> Fit:
    """What someone's life rules out, however well it scores in their numbers."""
    fit = Fit()
    for rule in LIFE_RULES:
        if any(rule.says.search(line) and not NO_LONGER.search(line) for line in lines):
            fit.levers |= rule.levers
            fit.options |= rule.options
            fit.notes.append(rule.note)
            fit.no_clock_bedtime = fit.no_clock_bedtime or rule.no_clock_bedtime
    return fit


# About eating, sleep habits are a different subject: only the lever about meals stays.
NOT_ABOUT_EATING_LEVERS = frozenset(
    ("earlier_bedtime", "regular_bedtime", "rest_after_hard_day", "active_days", "wind_down")
)
NOT_ABOUT_EATING_OPTIONS = frozenset(
    ("best_nights", "weekend_shift", "bedtime_spread", "time_in_bed", "heavy_week", "recent_dip")
)
MAX_POINTS = 5
NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
ASKED_POINTS = re.compile(
    r"\b(\d+|two|three|four|five|six|seven|eight)\s+(?:\w+\s+)?"
    r"(?:points?|tips?|things?|ways?|suggestions?|ideas?)\b",
    re.IGNORECASE,
)
VAGUE = re.compile(
    r"\b(?:balanced (?:meals?|diet)|enough nutrients|healthy (?:meals?|foods?|eating)|"
    r"eat(?:ing)? well|good nutrition)\b",
    re.IGNORECASE,
)
FILLER = re.compile(
    r"\b(?:held steady|stayed steady|(?:with)?in your usual range|no clear change|"
    r"did not clearly)\b",
    re.IGNORECASE,
)
ACTIONABLE = re.compile(r"\b(?:could|try|might|worth|aim)\b", re.IGNORECASE)
TIP_LENGTH = (30, 200)
MAX_SHARED = 0.6
DOES_SOMETHING = re.compile(
    r"^(?:try|avoid|keep|limit|make|choose|eat|drink|add|get|go|set|plan|start|use|walk|stretch|"
    r"take|cut|swap|include|have|put|finish|do)\b|\b(?:try to|can help|helps?|it is best)\b",
    re.IGNORECASE,
)
INLINE_BULLET = re.compile(r"(?<=[.!?])\s+-\s+")
POINT_BREAK = re.compile(r"\n+|(?<=[.!?:])\s+-\s+")  # a new line, or a dash starting a point
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z-])")
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


def asked_count(question: str) -> int:
    """How many points the person asked for, at most `MAX_POINTS`; 0 if they named no number."""
    match = ASKED_POINTS.search(question)
    if not match:
        return 0
    word = match[1].lower()
    return min(int(word) if word.isdigit() else NUMBER_WORDS[word], MAX_POINTS)


def without_filler(summary: str) -> str:
    """Advice does not need telling that other numbers held steady; the model keeps adding it. A
    list stays a list, one point per line."""
    if summary.lstrip().startswith("- "):
        summary = INLINE_BULLET.sub("\n- ", summary)
    lines = []
    for line in summary.splitlines():
        kept = [
            sentence
            for sentence in SENTENCE_END.split(line)
            if not FILLER.search(sentence) or ACTIONABLE.search(sentence)
        ]
        if kept or not line.strip():
            lines.append(" ".join(kept))
    return "\n".join(lines).strip() or summary


def _tip(text: str, said: set[str]) -> str:
    """A passage's most actionable sentence, if it adds something not already said."""
    for sentence in SENTENCE_END.split(text):
        if TIP_LENGTH[0] <= len(sentence) <= TIP_LENGTH[1] and DOES_SOMETHING.search(sentence):
            words = set(tokens(sentence))
            if words and len(words & said) / len(words) < MAX_SHARED:
                return sentence.strip()
    return ""


@dataclass(frozen=True)
class Added:
    tip: str
    record: Evidence


def top_up(summary: str, wanted: int, have: int, records: Sequence[Evidence]) -> list[Added]:
    """Points from passages already retrieved, when the answer fell short of what was asked: code
    picks them, so they are exactly what the source says."""
    said = set(tokens(summary))
    added: list[Added] = []
    for record in records:
        if have + len(added) >= wanted:
            break
        if tip := _tip(str(record.stats.get("text", "")), said):
            added.append(Added(tip, record))
            said |= set(tokens(tip))
    return added


def as_points(summary: str) -> str:
    """One point per line."""
    if summary.lstrip().startswith("- "):
        return summary
    lines = []
    pieces = [
        sentence for part in POINT_BREAK.split(summary) for sentence in SENTENCE_END.split(part)
    ]
    for piece in pieces:
        # A point that already has its dash keeps one ("- - You could try" in the 2026-11-14
        # run), and a lead-in ("Three things fit your shifts:") is no point of its own.
        text = piece.strip().lstrip("-").strip()
        if text:
            lines.append(text if text.endswith(":") else f"- {text}")
    return "\n".join(lines)


def draft_check(made_a_draft):
    """A request to log ends with a draft, or with a question about what is missing."""

    def check(claims: list, summary: str = "") -> list[str]:
        if made_a_draft() or "?" in summary:
            return []
        return [
            "no draft was prepared: call the tool again with what it said was missing (look up "
            "the food if it has no values), or ask for the missing detail"
        ]

    return check


# Points with nothing to do in them, written to reach a count ("You could try doing the same with
# your HRV data, since no habit clearly stood out there either": the run of 2026-11-14).
EMPTY_POINT = re.compile(
    r"\b(?:no habit (?:clearly )?stood out|nothing (?:clearly )?stood out|"
    r"(?:doing|do) the same (?:with|for)|without overemphasi[sz]\w*|focus(?:ing)? on recovery|"
    r"keep (?:doing )?what you(?:'re| are) doing)\b",
    re.IGNORECASE,
)


def personal_check(
    personal_ids: set[str],
    fit: Fit | None = None,
    wanted: int = 0,
    passage_ids: frozenset[str] = frozenset(),
):
    """What makes a coaching answer one worth giving: it fits their life, it says something about
    them, it gives what they asked for, it is concrete, and its how-to names where it came from."""

    def check(claims: list, summary: str = "") -> list[str]:
        if fit and fit.no_clock_bedtime and BED_BY_THE_CLOCK.search(summary):
            return ["a clock-time bedtime does not fit how they live; plan around their shifts"]
        problems = []
        points = [c for c in claims if c.kind in ("suggestion", "guidance")]
        if wanted and len(points) < wanted:
            problems.append(
                f"they asked for {wanted} points and there are {len(points)}: give {wanted} "
                "different ones, personal ones first, then what the passages say to do, each as a "
                "claim and one per line in the summary, starting with '- '"
            )
        empty = [c.text for c in points if EMPTY_POINT.search(c.text)]
        if empty:
            problems.append(
                "a point must say one concrete thing to do; drop points such as 'no habit stood "
                "out' or 'do the same with another metric', and give fewer points instead"
            )
        if VAGUE.search(summary):
            problems.append(
                "too vague: say which foods, how much or when, using the passages, instead of "
                "general words like balanced meals or enough nutrients"
            )
        if passage_ids and points and not any(passage_ids & set(c.evidence_ids) for c in points):
            problems.append("cite in evidence_ids the passage each how-to comes from")
        if personal_ids and not any(
            c.kind == "suggestion" and personal_ids & set(c.evidence_ids) for c in claims
        ):
            problems.append(
                "give at least one suggestion of kind suggestion that cites something specific "
                "about this person from below: their own numbers or what they told you. Advise "
                "first; a question alone is not an answer"
            )
        return problems

    return check
