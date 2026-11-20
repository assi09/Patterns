"""What the request reader returns: the message as an ordered list of clauses, each with only its
own fields and the words it came from.

One flat reading with every domain's fields, all required by the strict schema, made the reader
fill in placeholders: a data part on "draft my 26-minute walk" (every cold workout draft then asked
"which earlier measurement?"), "forget my goal" also marked don't-save, and "repeat the count and
say if it's saved" squeezed into one kind, losing the count. A period had fields its kind ignored:
"the 5 complete days before today" came out as one day with `days: 5` (the reader replay of
2026-11-19). Here each clause kind and each period kind carries only what it uses.

`reading_from` turns the clauses into the internal `Reading` that `resolve` already handles, so
dates, references and statistics are still worked out by the same code.
"""

import calendar
import re
from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from app.agent.requests import Fields, Operation, Part, Period, Reading, RetryReading

# ---- periods: one kind per meaning ----


class Dates(Fields):
    """Dates the person wrote out: a single day has the same start and end."""

    kind: Literal["dates"]
    start: date
    end: date


class CalendarPeriod(Fields):
    """'this week' (offset 0), 'last month' (offset -1), 'the week before last' (-2). Weeks
    start on Monday."""

    kind: Literal["calendar"]
    unit: Literal["week", "month", "year"]
    offset: int = Field(ge=-100, le=0)


class DaysEnding(Fields):
    """`length` consecutive days ending on a day counted from today, plus `offset`. 'yesterday':
    1, -1. 'two days before today': 1, -2. 'the last 7 days' (today included): 7, 0. 'the 5
    complete days before today': 5, -1. Days placed against an earlier result are
    from_earlier."""

    kind: Literal["days_ending"]
    length: int = Field(ge=1, le=3660)
    ending: Literal["today"] = "today"
    offset: int = Field(ge=-3660, le=366)


class FromEarlier(Fields):
    """Days placed against an earlier period, every part of the edit said, and one computation
    for all of them: from the earlier period's first or last day (`landmark`), move `offset`
    days (+1 the day after, -1 the day before, 0 that day); the new period starts there or ends
    there (`boundary`); it is `length` days long: the number said, or the earlier period's own
    number of days when none is said.
    After a five-day period: the same days again: its_first_day, 0, starts_there, 5. The whole
    period two days earlier: its_first_day, -2, starts_there, 5. The next four days:
    its_last_day, +1, starts_there, 4. Four days ending the day before it began: its_first_day,
    -1, ends_there, 4. Its last three days: its_last_day, 0, ends_there, 3. Four days starting on
    its second day: its_first_day, +1, starts_there, 4."""

    kind: Literal["from_earlier"]
    landmark: Literal["its_first_day", "its_last_day"]
    offset: int = Field(ge=-3660, le=3660)
    boundary: Literal["starts_there", "ends_there"]
    # Required: left optional, "three calendar days" and "four days up to the day before" came
    # back with no length, so the earlier length was kept or the four went into the offset (the
    # matched comparison on the b730 and a196 inputs, 2026-11-21).
    length: int = Field(
        ge=1,
        le=3660,
        description="Days in the new period: the number of days said, or the earlier period's own "
        "number of days (earlier_results) when no number is said.",
    )
    relative_to: Literal["earlier_result", "this_clause"] = Field(
        default="earlier_result",
        description="earlier_result: a result computed before this message. this_clause: the "
        "period named first in this same clause ('Oct 9-31 compared with the 4 weeks before').",
    )


class Month(Fields):
    """A month named with its year, past or future: 'January 2027', 'in March 2026'."""

    kind: Literal["month"]
    year: int = Field(ge=1970, le=2100)
    month: int = Field(ge=1, le=12)


class AllHistory(Fields):
    """No period named in a new question: all of their data."""

    kind: Literal["all_history"]


Span = Annotated[
    Dates | CalendarPeriod | Month | FromEarlier | DaysEnding | AllHistory,
    Field(discriminator="kind"),
]


def period_of(span: Span) -> Period:
    """The internal period that `resolve` already works out dates for."""
    if isinstance(span, Dates):
        return Period(kind="explicit", start=span.start, end=span.end)
    if isinstance(span, CalendarPeriod):
        return Period(kind="calendar", unit=span.unit, offset_units=span.offset)
    if isinstance(span, FromEarlier):
        return Period(
            kind="beside",
            anchor="own" if span.relative_to == "this_clause" else "previous",
            edge="first" if span.landmark == "its_first_day" else "last",
            starts=span.boundary == "starts_there",
            offset_days=span.offset,
            days=span.length,
        )
    if isinstance(span, Month):
        last = calendar.monthrange(span.year, span.month)[1]
        return Period(
            kind="explicit",
            start=date(span.year, span.month, 1),
            end=date(span.year, span.month, last),
        )
    if isinstance(span, DaysEnding):
        return Period(kind="rolling", anchor="today", offset_days=span.offset, days=span.length)
    return Period(kind="history")


# ---- clauses ----

SAID = Field(
    description="All the words of the message this clause comes from, copied exactly, with its "
    "dates and periods."
)


class DataClause(Fields):
    """A precise statistic from their own data: a value, total, average, count past a threshold,
    comparison of two periods, trend, relationship or days recorded. One clause per operation."""

    type: Literal["data"]
    said: str = SAID
    metrics: list[str] = Field(default_factory=list, max_length=8)
    operation: Operation
    periods: list[Span] = Field(default_factory=list, max_length=2)
    earlier_result: int | None = Field(
        default=None,
        ge=0,
        le=7,
        description="Zero-based index of the earlier result this refers to, when it refers to one.",
    )
    comparison: Literal[">", ">=", "<", "<=", "=="] | None = None
    threshold: float | None = Field(default=None, allow_inf_nan=False)
    threshold_unit: Literal["native", "hours", "minutes"] = "native"
    max_lag: int = Field(default=0, ge=0, le=14)
    meal_type: Literal["BREAKFAST", "LUNCH", "DINNER", "SNACK"] | None = None
    source: Literal["tracker", "food_log"] = Field(
        default="tracker",
        description="food_log: the meals they logged (energy and nutrients eaten; metrics then "
        "empty). tracker: what the wearable records, calories burned included.",
    )
    asks_cause: bool = Field(
        default=False, description="Asks whether one thing causes another, not just goes with it."
    )
    every_metric: bool = Field(
        default=False,
        description="They ask about every measure they have ('my full set of measurements', "
        "'everything you track'), not only ones they name.",
    )


class InvestigateClause(Fields):
    """Why something in their data happened, what changed, how they have been, or what they
    could try (coaching), without a precise statistic."""

    type: Literal["investigate"]
    said: str = SAID
    focus: Literal["what_changed", "why", "overview", "coaching"]
    metrics: list[str] = Field(default_factory=list, max_length=8)
    periods: list[Span] = Field(default_factory=list, max_length=2)
    earlier_result: int | None = Field(default=None, ge=0, le=7)
    every_metric: bool = Field(
        default=False, description="Look across every metric over those days."
    )


class GuidanceClause(Fields):
    """A general how-to from public sources, about no one's data ('how do I do a plank?')."""

    type: Literal["guidance"]
    said: str = SAID
    topics: list[str] = Field(
        default_factory=list,
        max_length=1,
        description="The one movement, variant or routine asked about, its qualifiers in the same "
        "phrase ('basic floor push-up, no equipment'); empty when it refers back or names none.",
    )
    refers_back: bool = Field(
        default=False,
        description="It is about the previous guidance answer's subject ('that version', 'it').",
    )
    question: str = Field(max_length=1000, description="The standalone question, details kept.")


class LogClause(Fields):
    """Prepare a new entry (a workout or food) for them to confirm on a card."""

    type: Literal["log"]
    said: str = SAID
    entry: Literal["workout", "food"]
    duration_minutes: float | None = Field(default=None, gt=0, le=1440, allow_inf_nan=False)
    on_date: date | None = Field(default=None, description="A date they wrote.")
    days_from_today: int | None = Field(
        default=None, ge=-366, le=7, description="'tomorrow' is 1, 'yesterday' -1."
    )


class CorrectClause(Fields):
    """Change the card waiting for their tap."""

    type: Literal["correct"]
    said: str = SAID
    duration_minutes: float | None = Field(default=None, gt=0, le=1440, allow_inf_nan=False)
    on_date: date | None = None
    days_from_today: int | None = Field(default=None, ge=-366, le=7)
    days_from_card: int | None = Field(
        default=None,
        ge=-366,
        le=366,
        description="A day said against the card's own day: 'a day later' is 1.",
    )


class StatusClause(Fields):
    """Asks whether something has been saved. Read-only."""

    type: Literal["status"]
    said: str = SAID
    about: Literal["entry", "memory"] = Field(
        default="entry",
        description="entry: a workout or food entry on the tracker; memory: a preference, goal "
        "or fact the app keeps about them.",
    )


class ConfirmClause(Fields):
    """Asks to save the waiting card ('go ahead', 'log it')."""

    type: Literal["confirm"]
    said: str = SAID


class MemoryClause(Fields):
    """About what the app keeps about them."""

    type: Literal["memory"]
    said: str = SAID
    action: Literal["remember", "recall", "forget"]
    recall: Literal["kept", "waiting", "this_chat", "all"] | None = Field(
        default=None,
        description="For recall: what they approved (kept), cards waiting for a tap, what they "
        "said in this conversation, or all of it.",
    )
    states_new_fact: bool = Field(
        default=False,
        description="For forget: the message also says what is true now ('it's Tuesdays now').",
    )


class OtherClause(Fields):
    """Small talk, thanks, an instruction for this answer, something they tell about
    themselves, or something outside what the app does."""

    type: Literal["other"]
    said: str = SAID
    # Only something they tell about themselves may become a memory: "give me three options and
    # label the general tips" is how to answer now, and made two memory cards (the a196 audit).
    about_them: bool = Field(
        default=False,
        description="They tell something about themselves or their life ('I'm training for a "
        "10k', 'I generally prefer three options'). False for thanks, small talk and "
        "instructions for this answer ('give me three options here').",
    )


Clause = Annotated[
    DataClause
    | InvestigateClause
    | GuidanceClause
    | LogClause
    | CorrectClause
    | StatusClause
    | ConfirmClause
    | MemoryClause
    | OtherClause,
    Field(discriminator="type"),
]


class Said(Fields):
    """The whole message."""

    subject: Literal["self", "other", "general"] = Field(
        description="other: asks to see another person's records."
    )
    clauses: list[Clause] = Field(min_length=0, max_length=6)
    store_nothing: bool = Field(
        description='They ask that nothing from this message be kept ("don\'t save this").'
    )
    medical: bool = Field(
        default=False,
        description="They ask for a diagnosis, whether they have an illness or condition, or for "
        "treatment or medication.",
    )
    clarification: str = Field(
        default="",
        max_length=300,
        description="Only when the message is genuinely unclear: the question to ask.",
    )


# ---- into the internal reading ----

# Which clause decides how the message is answered; the data clauses beside it are answered too.
PRIMARY = ("log", "correct", "confirm", "status", "memory", "investigate", "guidance", "data")
KIND = {
    "log": "logging",
    "correct": "correction",
    "confirm": "confirmation",
    "status": "status",
    "memory": "memory",
    "investigate": "investigate",
    "guidance": "guidance",
    "data": "data",
}


def _part(clause: DataClause | InvestigateClause) -> Part:
    common = {
        "metrics": clause.metrics,
        "periods": [period_of(s) for s in clause.periods],
        "reference": clause.earlier_result,
        "said": clause.said,
    }
    if isinstance(clause, InvestigateClause):
        return Part(operation="describe", every_metric=clause.every_metric, **common)
    return Part(
        operation=clause.operation,
        comparison=clause.comparison,
        threshold=clause.threshold,
        threshold_unit=clause.threshold_unit,
        max_lag=clause.max_lag,
        meal_type=clause.meal_type,
        source=clause.source,
        **common,
    )


def _day(clause: LogClause | CorrectClause) -> Period | None:
    if clause.on_date is not None:
        return Period(kind="explicit", start=clause.on_date, end=clause.on_date)
    if clause.days_from_today is not None:
        return Period(kind="relative", anchor="today", offset_days=clause.days_from_today)
    return None


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def from_this_message(clause, question: str) -> bool:
    """Whether a clause's words come from the current message. The reader once copied the
    previous message into a "remember" clause, answering "what have I told you?" with a new
    fact to keep (the smoke run of 2026-11-19); every clean clause had copied its words exactly."""
    said, asked = _words(clause.said), set(_words(question))
    return not said or not asked or sum(w in asked for w in said) / len(said) >= MIN_OWN_WORDS


MIN_OWN_WORDS = 0.6


def _every_metric_looked_into(clauses: list) -> list:
    """Data clauses about every measure ("contrast my full set of measurements for Oct 11-31
    with Sep 20-Oct 10") are one look across every metric over their days: read as data, the
    question got eight metrics' averages and no comparison (v8, and the b730 audit)."""
    wide = [c for c in clauses if isinstance(c, DataClause) and c.every_metric]
    if not wide or any(isinstance(c, InvestigateClause) for c in clauses):
        return clauses
    widest = max(wide, key=lambda c: len(c.periods))
    looked = InvestigateClause(
        type="investigate",
        said=widest.said,
        focus="overview",
        periods=widest.periods,
        earlier_result=widest.earlier_result,
        every_metric=True,
    )
    first = clauses.index(wide[0])
    rest = [c for c in clauses if c not in wide]
    return [*rest[:first], looked, *rest[first:]]


def reading_from(said: Said, question: str = "") -> Reading:
    """The internal reading: the primary clause's kind, every data clause's part in order (read
    beside a log, a confirmation, a status or a memory request as well), and its own fields."""
    clauses = list(said.clauses)
    if question and (strays := [c for c in clauses if not from_this_message(c, question)]):
        raise RetryReading(
            f"A {strays[0].type} clause has words from an earlier message. Earlier messages are "
            "context only: make clauses only for what the current message asks, with said "
            "copied from it."
        )
    # "What outdoor preference is still saved?" asks what is kept, not about a tracker entry (the
    # v5 audit answered it about the tracker).
    clauses = [
        MemoryClause(type="memory", said=c.said, action="recall", recall="kept")
        if isinstance(c, StatusClause) and c.about == "memory"
        else c
        for c in clauses
    ]
    clauses = _every_metric_looked_into(clauses)
    types = [c.type for c in clauses]
    primary = next((t for t in PRIMARY if t in types), None)
    fields: dict = {
        "medical": said.medical,
        "subject": said.subject,
        "memory": "deny" if said.store_nothing else "unspecified",
        "clarification": said.clarification,
    }
    if said.clarification or primary is None:
        kind = "clarify" if said.clarification or not clauses else "other"
        told = any(isinstance(c, OtherClause) and c.about_them for c in clauses)
        return Reading(kind=kind, clause_count=len(clauses), told=told, **fields)
    data = [c for c in clauses if isinstance(c, DataClause)]
    kind = KIND[primary]
    if primary == "data" and any(c.asks_cause for c in data):
        kind = "causality"
    for clause in data:
        if not (clause.metrics or clause.earlier_result is not None or clause.periods):
            raise RetryReading(
                "A data clause needs the metrics it asks about or the earlier result it refers "
                "to. A log, correction, status, confirmation or memory request has no data "
                "clause unless the person also asks about their data in the same message."
            )
    parts = [_part(c) for c in data]
    if primary == "investigate":
        looked_into = [c for c in clauses if isinstance(c, InvestigateClause)]
        fields["focus"] = looked_into[0].focus
        fields["also"] = parts  # precise reads asked beside the investigation
        parts = [_part(c) for c in looked_into]
    guidance = next((c for c in clauses if isinstance(c, GuidanceClause)), None)
    if guidance is not None:
        fields |= {
            "topics": guidance.topics,
            "guidance_question": guidance.question,
            "guidance_reference": guidance.refers_back and not guidance.topics,
        }
    entry = next((c for c in clauses if isinstance(c, LogClause | CorrectClause)), None)
    if entry is not None:
        fields |= {"duration_minutes": entry.duration_minutes, "log_day": _day(entry)}
        if isinstance(entry, CorrectClause) and entry.on_date is None:
            fields["card_day_offset"] = entry.days_from_card
        if isinstance(entry, LogClause):
            fields["entry"] = entry.entry
    memory = next((c for c in clauses if isinstance(c, MemoryClause)), None)
    if memory is not None:
        fields |= {
            "memory_action": memory.action,
            "recall": memory.recall,
            "states_new_fact": memory.states_new_fact,
        }
    fields["status"] = "status" in types
    fields["clause_count"] = len(clauses)
    fields["told"] = any(
        (isinstance(c, OtherClause) and c.about_them)
        or (isinstance(c, MemoryClause) and c.action == "remember")
        or isinstance(c, LogClause | CorrectClause)
        for c in clauses
    )
    return Reading(kind=kind, parts=parts, **fields)
