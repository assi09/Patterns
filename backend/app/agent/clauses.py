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
from collections.abc import Sequence
from datetime import date
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.actions.exercises import TYPES
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


class SameAsEarlier(Fields):
    """All of an earlier result's periods, unchanged: the same days, or the same comparison of
    two periods ("why did that happen?", "what could I try, given those findings?", a new
    threshold on the same days). Reusing a whole comparison is this, never an edit of each of
    its periods (both wordings of "why" after a two-period look came back as two edits, the
    9228fe6 audit)."""

    kind: Literal["same_as_earlier"]


class EdgeDay(Fields):
    """One day of the new period, counted from one of the earlier period's days."""

    counted_from: Literal["its_first_day", "its_last_day"]
    days_after: int = Field(
        ge=-3660,
        le=3660,
        description="Days from that day: +1 the day after, -1 the day before, 0 that day itself.",
    )


class FromEarlier(Fields):
    """Days placed against an earlier period: the new period's first day, its last day, or
    both, each counted from the earlier period's first or last day, and its length.

    One offset with a separate "starts there / ends there" flag was misread one way, every
    time: for a period that ends somewhere, the offset given was where it starts. "The five
    dates immediately before that range" came back as its first day -5, ends there, five days
    long, four days too early; "its final two dates" as its last day -1, ends there (the 689fa7c
    audit, seven inputs). Each day now names what it is, so the number the reader works out
    belongs to the day it worked it out for. Code does the rest, and checks that two days and
    a length agree.

    A block right after or before it, or the whole period moved, has its own kind
    (block_after, block_before, whole_shifted). After a five-day period: its last three
    days: new_last_day its_last_day 0, length 3. Four days starting on its second day:
    new_first_day its_first_day +1, length 4. Three days whose last day is its first day:
    new_last_day its_first_day 0, length 3. Without its first and last day: new_first_day
    its_first_day +1 and new_last_day its_last_day -1, length null."""

    kind: Literal["from_earlier"]
    new_first_day: EdgeDay | None = Field(
        default=None, description="The new period's first day, when the message places it."
    )
    new_last_day: EdgeDay | None = Field(
        default=None, description="The new period's last day, when the message places it."
    )
    # Required with one day placed: left optional, "three calendar days" and "four days up to
    # the day before" came back with no length (the matched comparison on the b730 and a196
    # inputs, 2026-11-21). With both days placed, they give it.
    length: int | None = Field(
        default=None,
        ge=1,
        le=3660,
        description="Days in the new period: the number of days said, or the earlier period's "
        "own number of days (earlier_results) when none is said. Null only when both days are "
        "placed.",
    )
    relative_to: Literal["earlier_result", "this_clause"] = Field(
        default="earlier_result",
        description="earlier_result: a result computed before this message. this_clause: the "
        "period named first in this same clause ('Oct 9-31 compared with the 4 weeks before').",
    )

    @model_validator(mode="before")
    @classmethod
    def _one_offset(cls, value):
        """A reading recorded with the single-offset form (older replays and fixtures): its
        offset was the day its boundary names, so it is that day."""
        if isinstance(value, dict) and "boundary" in value:
            value = dict(value)
            day = {"counted_from": value.pop("landmark"), "days_after": value.pop("offset")}
            edge = "new_first_day" if value.pop("boundary") == "starts_there" else "new_last_day"
            value[edge] = day
        return value


class AfterEarlier(Fields):
    """A block of days after an earlier period, its boundary worked out by code: "the next four
    days" is length 4; "four days beginning two days after its last day" is length 4, starting 2
    days after it. Placed as a new last day, "the next four days after that block" ended on the
    day after it, nine of twelve times (the review of e1c1eec)."""

    kind: Literal["block_after"]
    length: int = Field(ge=1, le=3660, description="Days in the new block.")
    starts_days_after_its_last_day: int = Field(
        default=1,
        ge=1,
        le=3660,
        description="1: it starts the day after the earlier period's last day.",
    )
    relative_to: Literal["earlier_result", "this_clause"] = "earlier_result"


class BeforeEarlier(Fields):
    """A block of days before an earlier period, its boundary worked out by code: "the five days
    before it" is length 5; "four days ending two days before its first day" ends 2 days before."""

    kind: Literal["block_before"]
    length: int = Field(ge=1, le=3660, description="Days in the new block.")
    ends_days_before_its_first_day: int = Field(
        default=1,
        ge=1,
        le=3660,
        description="1: it ends the day before the earlier period's first day.",
    )
    relative_to: Literal["earlier_result", "this_clause"] = "earlier_result"


class ShiftedEarlier(Fields):
    """The whole earlier period moved, its number of days kept by code: "the same block two days
    earlier" is -2. Placed with a length, a translation that kept its size came back with none
    (the review of e1c1eec)."""

    kind: Literal["whole_shifted"]
    days: int = Field(ge=-3660, le=3660, description="+2 two days later, -2 two days earlier.")


class Month(Fields):
    """A month named with its year, past or future: 'January 2027', 'in March 2026'."""

    kind: Literal["month"]
    year: int = Field(ge=1970, le=2100)
    month: int = Field(ge=1, le=12)


class AllHistory(Fields):
    """No period named in a new question: all of their data."""

    kind: Literal["all_history"]


Span = Annotated[
    Dates
    | CalendarPeriod
    | Month
    | SameAsEarlier
    | AfterEarlier
    | BeforeEarlier
    | ShiftedEarlier
    | FromEarlier
    | DaysEnding
    | AllHistory,
    Field(discriminator="kind"),
]


def period_of(span: Span) -> Period:
    """The internal period that `resolve` already works out dates for."""
    if isinstance(span, Dates):
        return Period(kind="explicit", start=span.start, end=span.end)
    if isinstance(span, CalendarPeriod):
        return Period(kind="calendar", unit=span.unit, offset_units=span.offset)
    if isinstance(span, SameAsEarlier):
        return Period(kind="inherit")
    if isinstance(span, AfterEarlier | BeforeEarlier):
        after = isinstance(span, AfterEarlier)
        return Period(
            kind="beside",
            anchor="own" if span.relative_to == "this_clause" else "previous",
            edge="last" if after else "first",
            starts=after,
            offset_days=span.starts_days_after_its_last_day
            if after
            else -span.ends_days_before_its_first_day,
            days=span.length,
        )
    if isinstance(span, ShiftedEarlier):
        return Period(
            kind="beside",
            anchor="previous",
            edge="first",
            starts=True,
            offset_days=span.days,
            keep_width=True,
        )
    if isinstance(span, FromEarlier):
        placed = span.new_first_day or span.new_last_day
        if placed is None:
            raise RetryReading(
                "A from_earlier period places its first day, its last day or both against the "
                "earlier period; this one placed neither."
            )
        if span.length is None and not (span.new_first_day and span.new_last_day):
            raise RetryReading(
                "A from_earlier period with one day placed needs its length: the number of days "
                "said, or the earlier period's own number of days when none is said."
            )
        other = span.new_last_day if span.new_first_day else None
        side = {"its_first_day": "first", "its_last_day": "last"}
        return Period(
            kind="beside",
            anchor="own" if span.relative_to == "this_clause" else "previous",
            edge="first" if placed.counted_from == "its_first_day" else "last",
            starts=span.new_first_day is not None,
            offset_days=placed.days_after,
            days=span.length or 1,
            sized=span.length is not None,
            end_edge=side[other.counted_from] if other else None,
            end_offset=other.days_after if other else 0,
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

Nutrient = Literal["energy", "protein", "carbohydrate", "fat"]
# What the reader may write as a food clause's metric for a nutrient: the same four, by name.
NUTRIENT_NAMES = {
    "energy": "energy",
    "calories": "energy",
    "protein": "protein",
    "carbohydrate": "carbohydrate",
    "carbohydrates": "carbohydrate",
    "carbs": "carbohydrate",
    "fat": "fat",
}

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
    # Null keeps an earlier result's lag: required as a number, "can that prove walking caused
    # it?" after a one-day-lag result came back 0 and was answered with a same-day test (the
    # 689fa7c audit).
    max_lag: int | None = Field(
        default=None,
        ge=0,
        le=14,
        description="Days of lag to test, when asked. Null keeps an earlier result's lag (none "
        "for a new question); 0 only when they ask for the same day.",
    )
    meal_type: Literal["BREAKFAST", "LUNCH", "DINNER", "SNACK"] | None = None
    source: Literal["tracker", "food_log"] = Field(
        default="tracker",
        description="food_log: the meals they logged (energy and nutrients eaten; metrics then "
        "empty). tracker: what the wearable records, calories burned included.",
    )
    # For food eaten: which nutrients the question is about. "Protein for that same entry?",
    # where protein was not recorded, was answered with energy, carbohydrate and fat, and never
    # said protein was missing (the 689fa7c audit).
    nutrients: list[Nutrient] = Field(
        default_factory=list,
        max_length=4,
        description="source food_log: the nutrients asked about; empty for all of them.",
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
    # Said by the reader, not counted from words: "give me three options" was never counted,
    # so a three-option request got one (the a196 and b3d64ca audits).
    points: int | None = Field(
        default=None, ge=1, le=5, description="How many options or points they ask for."
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
    # The base movement apart from its modifier: "pushups on a moving surfboard" came back as
    # topic "moving-surfboard variation", and "drop that variation, the standard floor movement"
    # then had no push-up to return to and taught a foam-roller stretch (the 689fa7c audit).
    movement: str = Field(
        default="",
        max_length=100,
        description="The base movement or routine the topic is a version of ('push-up' for "
        "'push-ups on a moving surfboard'); empty when it names none.",
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
    # The activity as the person named it, from the tracker's own types: the drafting model
    # once carded "prepare a run" as a generic workout (the 689fa7c audit).
    exercise_type: str | None = Field(
        default=None,
        max_length=40,
        description="For a workout: the tracker's exercise type for the activity they name, in "
        "its upper-case form (RUNNING, WALKING, BIKING, SWIMMING, HIKING, YOGA, "
        "STRENGTH_TRAINING, TENNIS ...); null when they name none.",
    )
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
    # A workout with a pause has two durations, and a new one is one of them: "active walking
    # was 33 minutes, with the same nine stopped" is 33 active and 42 in all. With no basis, a
    # paused card's edit could only be refused, and the fallback draft dropped the pause (the
    # 689fa7c audit).
    duration_is: Literal["active", "elapsed"] | None = Field(
        default=None,
        description="Which duration duration_minutes is: active (moving time) or elapsed (start "
        "to end, pauses included); null when they do not say.",
    )
    paused_minutes: float | None = Field(
        default=None,
        ge=0,
        le=1440,
        allow_inf_nan=False,
        description="A pause this message states, kept or new ('keep the 9-minute pause' is 9, "
        "'no pause' is 0); null when it says none.",
    )
    on_date: date | None = None
    days_from_today: int | None = Field(default=None, ge=-366, le=7)
    days_from_card: int | None = Field(
        default=None,
        ge=-366,
        le=366,
        description="An instruction to move the card, against its own day: 'move it a day "
        "later' is 1, 'move it back two days' is -2.",
    )
    # A report that the card's date is wrong is not an instruction to move it: "that was two
    # days too early" needs the card moved later, and as a signed move it went two days earlier
    # (the b3d64ca audit). The reader says which; code works out the sign.
    card_was: Literal["too_early", "too_late"] | None = Field(
        default=None,
        description="They report the card's date is wrong: too_early when the card is earlier "
        "than the day it happened ('that was two days too early'), too_late when later.",
    )
    by_days: int | None = Field(
        default=None, ge=1, le=366, description="With card_was: by how many days."
    )


class RedoClause(Fields):
    """An earlier answer again, changed only where this message changes it: the same request,
    in another form (more or fewer options, which are personal and which general, fewer words),
    or with new days, another statistic, measure, threshold or lag.

    A redo said only "keep the data" or not, and the same reader said it: "translate the
    complete block back by two dates" came back as a redo that kept the data, and the old days
    were repeated (the 689fa7c audit, twenty inputs over every family of date edit). So a redo
    now says the request it repeats, field by field, as a data clause does: its days (the same,
    or placed against the earlier ones), its statistic, its measures. Code inherits whatever it
    keeps from the earlier result, and works out the days."""

    type: Literal["redo"]
    said: str = SAID
    earlier_result: int | None = Field(
        default=None,
        ge=0,
        le=7,
        description="The earlier result it names, by its index in earlier_results ('the steps "
        "result', 'the all-measure comparison'); null for the last answer as a whole.",
    )
    periods: list[Span] = Field(
        min_length=1,
        max_length=2,
        description="The answer's days: same_as_earlier when this message keeps them; the new "
        "days when it changes them (from_earlier, dates, calendar, days_ending).",
    )
    operation: Operation = Field(
        description="inherit keeps the earlier statistic; the statistic this message asks for "
        "instead ('the median instead' is median)."
    )
    # What it is about, said apart from the statistic: with only an empty metric list, "every
    # measure, on those two blocks" inherited the last steps result, and a broad look edited to
    # a comparison lost its breadth (the review of e1c1eec).
    target: Literal["same", "named", "every_metric"] = Field(
        default="same",
        description="same: the earlier answer's own measures (all of them, if it looked at "
        "every one); named: the measures in metrics, which this message names; every_metric: "
        "every measure they have.",
    )
    metrics: list[str] = Field(
        max_length=8,
        description="With target named: the measures this message names. Otherwise empty.",
    )
    comparison: Literal[">", ">=", "<", "<=", "=="] | None = Field(
        default=None, description="Null keeps the earlier comparison."
    )
    threshold: float | None = Field(
        default=None, allow_inf_nan=False, description="Null keeps the earlier threshold."
    )
    threshold_unit: Literal["native", "hours", "minutes"] = "native"
    max_lag: int | None = Field(
        default=None, ge=0, le=14, description="Null keeps the earlier lag."
    )
    options: int | None = Field(
        default=None, ge=1, le=5, description="How many options or points they ask for."
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
    """About what they have told the app: what it keeps about them (approved, or waiting for a
    tap), and what they said earlier in this conversation, kept or not. Defined only as what the
    app keeps, "What day did I just mention?" after "Just for this chat I plan to walk on Friday.
    Don't save it." was read as outside the app: nothing about it was kept (the Fitbit replay's
    control P4, 2026-11-22)."""

    type: Literal["memory"]
    said: str = SAID
    action: Literal["remember", "recall", "forget"]
    recall: Literal["kept", "waiting", "this_chat", "all"] | None = Field(
        default=None,
        description="For recall: what they approved (kept), cards waiting for a tap, what they "
        "said earlier in this conversation (this_chat: including what they asked not to save, "
        "which is still part of this chat), or all of it.",
    )
    states_new_fact: bool = Field(
        default=False,
        description="For forget: the message also says what is true now ('it's Tuesdays now').",
    )


class OtherClause(Fields):
    """Small talk, thanks, something they tell about themselves, or something outside what the
    app does. Never a request about their data or about the last answer: those have their own
    clauses."""

    type: Literal["other"]
    said: str = SAID
    # Only something they tell about themselves may become a memory: "give me three options and
    # label the general tips" is how to answer now, and made two memory cards (the a196 audit).
    about_them: bool = Field(
        default=False,
        description="They tell something about themselves or their life ('I'm training for a "
        "10k', 'I generally prefer three options'). False for thanks and small talk.",
    )
    # Which kind of other it is: clear follow-ups ("use the preceding calendar day", "keep that
    # exact historical day", "read the pending workout's pause") came back as other and were
    # asked about (the 689fa7c audit, ten turns). One that is not small talk or about them goes
    # back once, with what a follow-up can be, before anyone is asked.
    message: Literal["small_talk", "about_them", "outside_the_app", "unsure"] = Field(
        default="small_talk",
        description="small_talk: thanks, greetings, chat. about_them: something they tell about "
        "themselves. outside_the_app: asks for something the app does not do (what the app keeps "
        "about them, removing it, and what they said earlier in this chat are memory). unsure: "
        "you cannot tell what it asks.",
    )


Clause = Annotated[
    RedoClause
    | DataClause
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
        description='They ask that nothing from this message be kept ("don\'t save this"): '
        "nothing is kept after this chat, but it is still part of this chat, to use and recall "
        "while it lasts.",
    )
    medical: bool = Field(
        default=False,
        description="This message asks for a diagnosis, whether they have an illness or "
        "condition, or for treatment or medication.",
    )
    # The words that make it medical, from this message: "return to my own daily step count"
    # after an urgent reply was refused as medical, the earlier message's pain carried over (the
    # 689fa7c audit). Words from an earlier message make nothing medical now.
    medical_said: str = Field(
        default="",
        max_length=300,
        description="With medical: the words of this message that ask it, copied exactly.",
    )
    # Said as a field, so the reply says why: answered as "unclear", a request to invent a
    # value and its evidence id got a generic rephrase (the 689fa7c audit, both wordings).
    fabricate: bool = Field(
        default=False,
        description="They ask to make up or pretend a value, evidence, an id or a citation.",
    )
    # One source per history: asked to join an export and the live sync, one wording claimed a
    # combined series no tool had read, the other answered from one source silently (the
    # 689fa7c audit).
    mix_sources: bool = Field(
        default=False,
        description="They ask to join records from different sources (an export and the live "
        "sync, two devices) into one series.",
    )
    clarification: str = Field(
        default="",
        max_length=300,
        description="Only when the message is genuinely unclear: the question to ask.",
    )


# ---- into the internal reading ----

# Which clause decides how the message is answered; the data clauses beside it are answered too.
PRIMARY = (
    "log",
    "correct",
    "confirm",
    "status",
    "memory",
    "investigate",
    "guidance",
    "data",
    "redo",
)
KIND = {
    "log": "logging",
    "correct": "correction",
    "confirm": "confirmation",
    "status": "status",
    "memory": "memory",
    "investigate": "investigate",
    "guidance": "guidance",
    "data": "data",
    "redo": "redo",
}


def _part(clause: DataClause | InvestigateClause, earlier: bool = False) -> Part:
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
        every_metric=_whole_registry(clause, earlier),
        nutrients=_nutrients(clause),
        **common,
    )


def _nutrients(clause: DataClause) -> list[str]:
    """The nutrients a food clause asks about: said as such, or written as its metrics."""
    if clause.source != "food_log":
        return []
    named = [*clause.nutrients, *(NUTRIENT_NAMES.get(m.casefold(), "") for m in clause.metrics)]
    return list(dict.fromkeys(n for n in named if n))


def _edit(redo: RedoClause) -> Part:
    """What a redo repeats, as a data part: what it keeps is left to inherit from the earlier
    result, what it changes is said. Measures it states are the ones used, whatever its target
    says (the reader restates an unchanged metric often, and that is no conflict). A target
    that contradicts its metrics, named with none or every measure with some, goes back."""
    if (redo.target == "named" and not redo.metrics) or (
        redo.target == "every_metric" and redo.metrics
    ):
        raise RetryReading(
            "A redo's target and metrics disagree: target named lists the measures the message "
            "names in metrics; every_metric leaves metrics empty."
        )
    return Part(
        every_metric=redo.target == "every_metric",
        metrics=redo.metrics,
        operation=redo.operation,
        periods=[period_of(s) for s in redo.periods],
        reference=redo.earlier_result,
        comparison=redo.comparison,
        threshold=redo.threshold,
        threshold_unit=redo.threshold_unit,
        max_lag=redo.max_lag,
        said=redo.said,
    )


def _day(clause: LogClause | CorrectClause) -> Period | None:
    if clause.on_date is not None:
        return Period(kind="explicit", start=clause.on_date, end=clause.on_date)
    if clause.days_from_today is not None:
        return Period(kind="relative", anchor="today", offset_days=clause.days_from_today)
    return None


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _share(said: list[str], text: str) -> float:
    words = set(_words(text))
    return sum(w in words for w in said) / len(said) if said else 1.0


def from_this_message(clause, question: str, before: Sequence[str] = ()) -> bool:
    """Whether a clause's words come from the current message. The reader once copied the
    previous message into a "remember" clause, answering "what have I told you?" with a new
    fact to keep (the smoke run of 2026-11-19); every clean clause had copied its words exactly.
    Words shared with the current message are not enough when an earlier message has them
    nearly all: "remove the preference about walking after lunch" shares most of its words with
    "is the after-lunch walking preference still in my profile?", and a status question became
    a forget card (the 689fa7c audit)."""
    said = _words(clause.said)
    if not said or not question:
        return True
    own = _share(said, question)
    copied = max((_share(said, text) for text in before), default=0.0)
    return own >= MIN_OWN_WORDS and not (copied >= COPIED_WORDS and copied > own)


def _medical_here(said: "Said", question: str, before: Sequence[str]) -> bool:
    """Medical when the words that make it so are this message's. A reading with no words
    quoted (older fixtures) keeps the flag; code's own medical checks still apply after it."""
    if not said.medical_said or not question:
        return True
    quoted = OtherClause(type="other", said=said.medical_said)
    return from_this_message(quoted, question, before)


def _covers(clauses: list, question: str) -> bool:
    """Whether these clauses' words cover the current message: nothing it asks is left out."""
    asked = _words(question)
    said = {w for c in clauses for w in _words(c.said)}
    return bool(asked) and sum(w in said for w in asked) / len(asked) >= MIN_OWN_WORDS


MIN_OWN_WORDS = 0.6
COPIED_WORDS = 0.9  # an earlier message with nearly all of a clause's words is where it came from


def _whole_registry(clause, earlier: bool = False) -> bool:
    """A data clause about every measure they have: said so, or, with nothing earlier to point
    at, a tracker read over named days that names no metric. With an earlier result, naming no
    metric keeps its metric: "use last week, Monday through Sunday" after a resting heart rate
    mean became a look at every measure (the 689fa7c audit, three date edits). A clause that
    repeats the earlier computation (inherit) points back whatever is there."""
    if not (
        isinstance(clause, DataClause)
        and clause.source == "tracker"
        and clause.meal_type is None
        and not clause.metrics
    ):
        return False
    unnamed = bool(clause.periods) and clause.earlier_result is None
    return clause.every_metric or (unnamed and not earlier and clause.operation != "inherit")


def _every_metric_looked_into(clauses: list, earlier: bool = False) -> list:
    """Data clauses about every measure ("contrast my full set of measurements for Oct 11-31
    with Sep 20-Oct 10") are one look across every metric over their days: read as data, the
    question got eight metrics' averages and no comparison (v8, and the b730 audit).

    Beside an investigation, the message has one look, written twice or split: an investigation
    that names no days takes the one scope its data clauses share, and a whole-registry clause
    over the investigation's own days is the same look, so it goes. Read as a side read, it
    named no metric and asked for an earlier result on a cold question (the 9228fe6 review). A
    side read of named metrics stays, and so does a whole-registry clause over other days."""
    wide = [c for c in clauses if _whole_registry(c, earlier)]
    looks = [c for c in clauses if isinstance(c, InvestigateClause)]
    if looks:
        scoped = [
            c.periods
            for c in clauses
            if isinstance(c, DataClause) and c.periods and c.earlier_result is None
        ]
        if scoped and all(periods == scoped[0] for periods in scoped):
            scope = scoped[0]
            clauses = [
                c.model_copy(update={"periods": list(scope)})
                if isinstance(c, InvestigateClause) and not c.periods and c.earlier_result is None
                else c
                for c in clauses
            ]
        looks = [c for c in clauses if isinstance(c, InvestigateClause)]
        # The same look: the same periods of the same result. Two "same as earlier" spans that
        # point at different results are not one look (the review of b3d64ca).
        same = [
            c
            for c in wide
            if any(
                c.periods == look.periods and c.earlier_result == look.earlier_result
                for look in looks
            )
        ]
        return [
            c.model_copy(update={"every_metric": True})
            if isinstance(c, InvestigateClause) and not c.metrics and same
            else c
            for c in clauses
            if c not in same
        ]
    if not wide:
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


def reading_from(
    said: Said, question: str = "", earlier: bool = False, before: Sequence[str] = ()
) -> Reading:
    """The internal reading: the primary clause's kind, every data clause's part in order (read
    beside a log, a confirmation, a status or a memory request as well), and its own fields.
    `earlier`: whether an earlier result is there for a clause to point at; `before`: the
    earlier messages, which no clause may come from.

    A clause copied from an earlier message is not asked now. When the clauses left cover the
    current message and none of them is other, they are the reading; otherwise it goes back."""
    clauses = list(said.clauses)
    strays = [c for c in clauses if not from_this_message(c, question, before)]
    if strays:
        rest = [c for c in clauses if c not in strays]
        placed = rest and not any(isinstance(c, OtherClause) for c in rest)
        if not (placed and _covers(rest, question)):
            raise RetryReading(
                f"A {strays[0].type} clause has words from an earlier message. Earlier messages "
                "are context only: make clauses only for what the current message asks, with "
                "said copied from it, and give every part of the current message its clause "
                "(what the app keeps, or what they said here, is memory recall)."
            )
        clauses = rest
    # "What outdoor preference is still saved?" asks what is kept, not about a tracker entry (the
    # v5 audit answered it about the tracker).
    clauses = [
        MemoryClause(type="memory", said=c.said, action="recall", recall="kept")
        if isinstance(c, StatusClause) and c.about == "memory"
        else c
        for c in clauses
    ]
    clauses = _every_metric_looked_into(clauses, earlier)
    types = [c.type for c in clauses]
    primary = next((t for t in PRIMARY if t in types), None)
    fields: dict = {
        "medical": said.medical and _medical_here(said, question, before),
        "fabricate": said.fabricate,
        "mix_sources": said.mix_sources,
        "unplaced": any(
            isinstance(c, OtherClause) and c.message in ("outside_the_app", "unsure")
            for c in clauses
        )
        or not clauses,
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
            if clause.source == "food_log":
                # Food eaten names no metric by design: what it lacks is its days. Told it needed
                # a metric, the retry added a snack filter from the waiting card and read the
                # wrong meals (the 689fa7c audit).
                error = RetryReading(
                    "A food_log clause names no metrics; it needs the days it reads: the date "
                    "written or referred to (the waiting card's day, from pending_draft, as "
                    "dates), or the earlier result it refers to."
                )
                error.keeps = ("source", "operation", "meal_type", "nutrients")
                raise error
            raise RetryReading(
                "A data clause needs the metrics it asks about or the earlier result it refers "
                "to. A log, correction, status, confirmation or memory request has no data "
                "clause unless the person also asks about their data in the same message."
            )
    parts = [_part(c, earlier) for c in data]
    if primary == "investigate":
        looked_into = [c for c in clauses if isinstance(c, InvestigateClause)]
        fields["focus"] = looked_into[0].focus
        fields["points"] = looked_into[0].points
        fields["also"] = parts  # precise reads asked beside the investigation
        parts = [_part(c) for c in looked_into]
    guidance = next((c for c in clauses if isinstance(c, GuidanceClause)), None)
    if guidance is not None:
        topics = [
            topic
            if not guidance.movement or set(_words(guidance.movement)) <= set(_words(topic))
            else f"{guidance.movement}, {topic}"
            for topic in guidance.topics
        ]
        fields |= {
            "topics": topics,
            "guidance_question": guidance.question,
            "guidance_reference": guidance.refers_back and not topics,
        }
    entry = next((c for c in clauses if isinstance(c, LogClause | CorrectClause)), None)
    if entry is not None:
        fields |= {"duration_minutes": entry.duration_minutes, "log_day": _day(entry)}
        if isinstance(entry, CorrectClause):
            fields |= {"duration_is": entry.duration_is, "paused_minutes": entry.paused_minutes}
        if isinstance(entry, LogClause) and entry.exercise_type in TYPES:
            fields["exercise_type"] = entry.exercise_type
        if isinstance(entry, CorrectClause) and entry.on_date is None:
            fields["card_day_offset"] = entry.days_from_card
            if entry.card_was is not None and entry.by_days is not None:
                # Too early: it happened later than the card says, so the card moves later.
                way = 1 if entry.card_was == "too_early" else -1
                fields["card_day_offset"] = way * entry.by_days
        if isinstance(entry, LogClause):
            fields["entry"] = entry.entry
    memory = next((c for c in clauses if isinstance(c, MemoryClause)), None)
    if memory is not None:
        fields |= {
            "memory_action": memory.action,
            "recall": memory.recall,
            "states_new_fact": memory.states_new_fact,
            # Only these words are the fact to keep or forget: given the whole message, the
            # listener kept "average time asleep Oct 3-9" beside the walk preference asked for
            # (the 689fa7c audit).
            "memory_said": memory.said,
        }
    redo = next((c for c in clauses if isinstance(c, RedoClause)), None)
    if redo is not None:
        fields["redo_options"] = redo.options
        if primary == "redo":
            parts = [_edit(redo)]
        else:
            # Beside a status, a recall or guidance, the redo is answered too: "say both again"
            # read as a redo and a status lost the repeated figure (the review of e1c1eec).
            fields["redo_part"] = _edit(redo)
    fields["status"] = "status" in types
    fields["clause_count"] = len(clauses)
    fields["told"] = any(
        (isinstance(c, OtherClause) and c.about_them)
        or (isinstance(c, MemoryClause) and c.action == "remember")
        or isinstance(c, LogClause | CorrectClause)
        for c in clauses
    )
    return Reading(kind=kind, parts=parts, **fields)
