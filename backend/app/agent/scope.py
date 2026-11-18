"""What a follow-up's "those dates", "that same night" or "and the median?" refers to, by code.

An independent audit (2026-11-18) found the numbers right but the dates wrong: "the daily average
for exactly those dates", after a seven-day total, was answered over the whole history (7,685
against 13,438); "that same night" became today, and went back to today after a correction. The
model rewrite of a follow-up is not allowed to add numbers, so the dates were lost before the agent
ever saw them.

Each question's **scope** (the metrics it names, and the days it covers) is worked out by code
from the person's own words, replaying the conversation, so it never depends on what the answer
happened to say. A later question **reuses** it only when it refers back:

- by words that point at it: "those dates", "that week", "the same history", "that same day";
- or by leaving things out: a short question naming an operation and no metric or period
  ("and the median?", "what about the average?").

A question that stands on its own resolves its own scope as a first question would: "what's my
average HRV?" after a steps-this-week answer is not about that week. A period named in the question
always wins. When a reference cannot be resolved (it points at dates nothing gave, or at "that day"
after a week), the person is asked.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta

from app.agent.context import Turn
from app.agent.followup import DAY_AFTER, DAY_BEFORE
from app.agent.periods import asked_period
from app.agent.present import label
from app.agent.strategy import ASKED_ABOUT
from app.agent.verifier import MONTHS

ISO = r"(\d{4})-(\d{2})-(\d{2})"
MONTH_NAME = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"
RANGE_WORDS = r"\s*(?:to|through|thru|until|till|and|-|–)\s*"
ISO_RANGE = re.compile(ISO + RANGE_WORDS + ISO)
ISO_DAY = re.compile(ISO)
NAMED_RANGE = re.compile(
    rf"\b{MONTH_NAME}\s+(\d{{1,2}}){RANGE_WORDS}(?:{MONTH_NAME}\s+)?(\d{{1,2}})\b", re.IGNORECASE
)
NAMED_DAY = re.compile(rf"\b{MONTH_NAME}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", re.I)
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "fourteen": 14,
    "thirty": 30,
}
# "The seven complete days ending yesterday": a span, not yesterday alone.
DAYS_ENDING = re.compile(
    r"\b(\d{1,3}|" + "|".join(NUMBER_WORDS) + r") (?:complete |full |whole )?(?:days|nights) "
    r"(?:ending|up to|through|until) (yesterday|today|last night)\b",
    re.IGNORECASE,
)
YESTERDAY = re.compile(r"\byesterday\b", re.IGNORECASE)
TODAY = re.compile(r"\b(?:today|last night|this morning)\b", re.IGNORECASE)
ALL_DATA = re.compile(
    r"\b(?:all (?:the )?(?:available )?(?:history|dates|data|days|nights)|all[- ]time|ever|"
    r"everything you have|(?:my )?whole history|all my data)\b",
    re.IGNORECASE,
)
# Words that point back at the days of an earlier question.
DATES_BACK = re.compile(
    r"\b(?:those|these|the same|that same|that|same) (?:dates?|days|nights|period|weeks?|months?|"
    r"span|range|window|history|stretch|time)\b|\bof those\b|\bfrom that answer\b|"
    r"\bin that answer\b|\bover those\b",
    re.IGNORECASE,
)
# ... and at its single day: "that same day", "that night". "The day before that" is not one of
# these: followup.with_relative_day turns it into its date first.
DAY_BACK = re.compile(
    r"\b(?:that|the same|that same) (?:day|night|date|morning|evening)\b(?! (?:before|after))",
    re.IGNORECASE,
)
# A short question that names only an operation: "and the median?", "what about the average?".
ELLIPTICAL = re.compile(
    r"^\s*(?:(?:and|or|but|so|now|then|ok|okay)[ ,]+)?(?:what about|how about|instead,?\s*)?"
    r"(?:just |only )?(?:the |my |its )?(?:daily |nightly )?"
    r"(?:median|average|mean|total|sum|max(?:imum)?|min(?:imum)?|highest|lowest|best|worst|"
    r"range|count|spread)\b",
    re.IGNORECASE,
)
MAX_ELLIPTICAL_WORDS = 10
# "Now use the seven days ending yesterday instead": the same thing over other days.
INSTEAD = re.compile(r"\b(?:instead|rather than|same for|now use|switch to|do the same)\b", re.I)
# Any word for an area: such a question is about that, whatever the last one was.
AREA = re.compile(
    r"\b(?:sleep\w*|slept|nap|bed\w*|steps?|walk\w*|run\w*|ran|heart|hrv|pulse|calori\w*|burn\w*|"
    r"active|activity|exercis\w*|workouts?|weight|protein|food|ate|eat\w*|stress\w*|recovery|"
    r"readiness|strain|score|rem|deep|light|resting|temperature|breathing|respirat\w*|zone)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Scope:
    """The metrics a question is about and the days it covers (both None when it named none)."""

    metrics: tuple[str, ...] = ()
    start: date | None = None
    end: date | None = None
    all_data: bool = False

    @property
    def days(self) -> bool:
        return self.start is not None or self.all_data

    @property
    def one_day(self) -> bool:
        return self.start is not None and self.start == self.end


@dataclass(frozen=True)
class Resolved:
    """A question's own scope, what it took from earlier, and a question to ask instead."""

    scope: Scope
    inherited: bool = False  # it reused an earlier question's days or metrics
    ask: str | None = None  # the reference could not be resolved: ask this instead


def _named_day(month: str, day: str, year: str | None, today: date) -> date | None:
    number = MONTHS[month.lower()[:3]]
    for candidate_year in [int(year)] if year else [today.year, today.year - 1]:
        try:
            candidate = date(candidate_year, number, int(day))
        except ValueError:
            return None
        if year or candidate <= today:
            return candidate
    return None


def own_days(question: str, today: date) -> tuple[date | None, date | None, bool]:
    """The days a question names itself: (start, end, all the data)."""
    if found := ISO_RANGE.search(question):
        y1, m1, d1, y2, m2, d2 = map(int, found.groups())
        try:
            return date(y1, m1, d1), date(y2, m2, d2), False
        except ValueError:
            pass
    if found := NAMED_RANGE.search(question):
        month, first, second_month, last = found.groups()
        start = _named_day(month, first, None, today)
        end = _named_day(second_month or month, last, None, today)
        if start and end and start <= end:
            return start, end, False
    if found := ISO_DAY.search(question):
        try:
            day = date(*map(int, found.groups()))
            return day, day, False
        except ValueError:
            pass
    found = NAMED_DAY.search(question)
    if found and (day := _named_day(found.group(1), found.group(2), found.group(3), today)):
        return day, day, False
    if found := DAYS_ENDING.search(question):
        count = NUMBER_WORDS.get(found.group(1).lower()) or int(found.group(1))
        end = today - timedelta(days=1) if found.group(2).lower() == "yesterday" else today
        if 0 < count <= 366:
            return end - timedelta(days=count - 1), end, False
    if YESTERDAY.search(question):
        day = today - timedelta(days=1)
        return day, day, False
    if span := asked_period(question, today):
        return span[0], span[1], False
    if TODAY.search(question):
        return today, today, False
    if ALL_DATA.search(question):
        return None, None, True
    return None, None, False


def own_scope(question: str, today: date) -> Scope:
    start, end, all_data = own_days(question, today)
    metrics = tuple(m for m, pattern in ASKED_ABOUT.items() if pattern.search(question))
    return Scope(metrics, start, end, all_data)


def resolve(question: str, earlier: Scope | None, today: date) -> Resolved:
    """This question's scope, reusing `earlier` only where the question refers back to it."""
    own = own_scope(question, today)
    if own.days:  # a period named in the question always wins
        same_thing = _elliptical(question) or INSTEAD.search(question)
        if (
            not own.metrics
            and earlier
            and earlier.metrics
            and same_thing
            and not AREA.search(question)
        ):
            return Resolved(replace(own, metrics=earlier.metrics), inherited=True)
        return Resolved(own)
    # "And the day before that?": the day before the one the conversation is on.
    shift = -1 if DAY_BEFORE.search(question) else 1 if DAY_AFTER.search(question) else 0
    if shift and earlier and earlier.one_day and earlier.start:
        day = earlier.start + timedelta(days=shift)
        if day <= today:
            metrics = own.metrics or (earlier.metrics if not AREA.search(question) else ())
            return Resolved(Scope(metrics, day, day), inherited=True)
    day_back, dates_back = DAY_BACK.search(question), DATES_BACK.search(question)
    elliptical = _elliptical(question)
    if not (day_back or dates_back or elliptical):
        return Resolved(own)  # stands on its own
    if earlier is None or not earlier.days:
        if day_back or dates_back:
            which = "day do you mean? Name it" if day_back else "dates do you mean? Name them"
            return Resolved(own, ask=f"Which {which} and I'll look.")
        return Resolved(own)
    if day_back and not earlier.one_day:
        return Resolved(
            own,
            ask=(
                f"Which day do you mean? The last answer covered {_span(earlier)}: "
                "name the one you want."
            ),
        )
    metrics = own.metrics or (earlier.metrics if not AREA.search(question) else ())
    return Resolved(
        Scope(metrics, earlier.start, earlier.end, earlier.all_data),
        inherited=True,
    )


def _elliptical(question: str) -> bool:
    return bool(ELLIPTICAL.match(question)) and len(question.split()) <= MAX_ELLIPTICAL_WORDS


def replay(history: Sequence[Turn], today: date) -> Scope | None:
    """The scope the conversation is on: each question resolved in turn, in its own day. A turn
    that names nothing (a plank question, "log it") leaves the last one in place."""
    scope: Scope | None = None
    for turn in history:
        if turn.refused:
            continue
        on = turn.at.date() if turn.at else today
        found = resolve(turn.question, scope, on)
        if found.ask is None and (found.scope.days or found.scope.metrics):
            scope = found.scope
    return scope


def _span(scope: Scope) -> str:
    if scope.all_data:
        return "all your data"
    assert scope.start and scope.end
    if scope.one_day:
        return f"{scope.start:%a %b %-d} ({scope.start.isoformat()})"
    return (
        f"{scope.start:%a %b %-d} to {scope.end:%a %b %-d} "
        f"({scope.start.isoformat()} to {scope.end.isoformat()}, inclusive)"
    )


def with_scope(question: str, history: Sequence[Turn], today: date) -> Resolved:
    """The question resolved against the conversation, for the caller to use or ask from."""
    return resolve(question, replay(history, today), today)


def note(resolved: Resolved, first: date | None, today: date) -> str:
    """What the question's reference means, said after the person's words."""
    scope = resolved.scope
    if scope.all_data and first:
        scope = replace(scope, start=first, end=today, all_data=False)
    parts = []
    if scope.metrics:
        parts.append(", ".join(label(m) for m in scope.metrics))
    if scope.days:
        parts.append(_span(scope))
    return f"(From this conversation: {'; '.join(parts)}. Use exactly these days and name them.)"
