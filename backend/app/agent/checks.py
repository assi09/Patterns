"""Facts code reads from the question, and checks the request reader against.

Code used to rewrite the reader's output wherever a phrase matched ("that day", "this week",
"two days earlier"). Where the reader was right, that broke it: "24 hours earlier than that day"
lost its shift to "that day" (Codex's live review, 2026-11-19). Now code never rewrites a reading
from words: it checks the **resolved** request against what the words fix, so a correct reading
passes however the reader expressed it. A contradiction is sent back to the reader once, stating
it; if the reader keeps it, the person is asked. Each check holds only where its phrase belongs
to one part unambiguously; otherwise it says nothing. Code still does all the date arithmetic.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.agent.periods import period_range
from app.agent.present import METRICS, label

DATA_KINDS = ("data", "causality", "investigate")


@dataclass(frozen=True)
class Conflict:
    retry: str  # told to the reader: the fact its reading contradicts
    ask: str  # asked of the person when the reader keeps it


def _day(day: date, today: date) -> str:
    text = f"{day:%b} {day.day}"
    return text if day.year == today.year else f"{text}, {day.year}"


def _span(start: date, end: date, today: date) -> str:
    if start == end:
        return _day(start, today)
    return f"{_day(start, today)} to {_day(end, today)}"


# ---- dates written out ----

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
# Whole month names only: "decided 3 times" is not Dec 3.
MONTH = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MONTH_DAY = re.compile(rf"\b{MONTH} (\d{{1,2}})(?:st|nd|rd|th)?\b(?:,? (\d{{4}}))?", re.I)
DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)? (?:of )?{MONTH}\b(?:,? (\d{{4}}))?", re.I)
# "the week of Nov 2" names a day inside the period, not one of its ends.
INSIDE = re.compile(r"\b(?:week|month) of\b|\baround\b|\bnear\b", re.I)


def written_dates(question: str) -> list[tuple[int | None, int, int, str]]:
    """(year or None, month, day, as written) for each date written out; a year left out stays
    unknown and only the month and day are checked."""
    found = []
    for match in ISO.finditer(question):
        y, m, d = map(int, match.groups())
        found.append((y, m, d, match.group(0)))
    for pattern, order in ((MONTH_DAY, (0, 1, 2)), (DAY_MONTH, (1, 0, 2))):
        for match in pattern.finditer(question):
            name, d, y = (match.groups()[i] for i in order)
            month = MONTHS.index(name[:3].lower()) + 1
            found.append((int(y) if y else None, month, int(d), match.group(0)))
    return [f for f in found if 1 <= f[1] <= 12 and 1 <= f[2] <= 31]


def _written(request, question: str) -> list[Conflict]:
    dates = written_dates(question)
    if not dates or INSIDE.search(question):
        return []
    ends = {day for p in request.parts for w in p.windows for day in (w.start, w.end)}
    missing = [
        text
        for y, m, d, text in dates
        if not any(e.month == m and e.day == d and (y is None or e.year == y) for e in ends)
    ]
    if not missing:
        return []
    said = ", ".join(missing)
    return [
        Conflict(
            f"The user wrote the date(s) {said}. Each written date must be the start or end of "
            "the period it belongs to, exactly as written; do not move it or inherit old dates.",
            f"I want to be sure of the dates: should I use {said}?",
        )
    ]


# ---- earlier days kept, or shifted by a number of days ----

COUNT = r"(\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|fourteen|thirty)"
NOT_FROM_TODAY = r"(?! (?:today|now|yesterday|tomorrow|this\b))"
SHIFT = re.compile(
    rf"\b{COUNT} (?:calendar |whole |full )?(?:days?|nights?) (earlier|later|back|forward|"
    rf"before|after|ahead|sooner){NOT_FROM_TODAY}\b|"
    rf"\b(back|forward|ahead|earlier|later)(?: by)? {COUNT} (?:calendar |whole |full )?"
    rf"(?:days?|nights?){NOT_FROM_TODAY}\b",
    re.IGNORECASE,
)
WORDS = {
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
EARLIER = ("earlier", "back", "before", "sooner")


def shift_said(question: str) -> int | None:
    """The days a follow-up moves by: -2 for "two days earlier", +3 for "forward 3 days". None
    for none, for more than one, or for a shift counted from today ("two days before today")."""
    found = SHIFT.findall(question)
    if len(found) != 1:
        return None
    a, way_a, way_b, b = found[0]
    count, way = (a, way_a) if a else (b, way_b)
    number = WORDS.get(count.lower()) or int(count)
    return -number if way.lower() in EARLIER else number


SAME_DAYS = re.compile(
    r"\b(?:that|those)(?: same| identical| whole| entire)? (?:date|day|night|interval|stretch|"
    r"period|range|window|span|dates|days|nights)\b|"
    r"\b(?:the )?(?:same|identical) (?:date|day|night|dates|days|period|interval|stretch|range|"
    r"window|span)\b",
    re.IGNORECASE,
)
# Any of these and "that day" may be a point to count from, not the days themselves.
MOVED = re.compile(
    r"\b(?:earlier|later|before|after|ago|prior|previous|next|following|hours?|back|forward|"
    r"ahead|since|until)\b",
    re.IGNORECASE,
)


def _earlier_days(request, question: str, state: dict, today: date) -> list[Conflict]:
    previous = [w for p in state.get("data", []) for w in [_windows(p)] if w]
    if not previous or written_dates(question):
        return []
    held = [tuple(p.windows) for p in request.parts]
    shift = shift_said(question)
    if shift is not None:
        moved = [tuple(_moved(w, shift) for w in ws) for ws in previous]
        if any(h in moved for h in held):
            return []
        target = moved[0] if len(moved) == 1 else None
        way = "earlier" if shift < 0 else "later"
        return [
            Conflict(
                f"The user moves the earlier request's days {abs(shift)} day(s) {way}: shift "
                "both ends of that period by exactly that, using a relative period anchored "
                "to previous, and leave other parts as they are.",
                f"Do you mean {_span(*_ends(target), today)}?"
                if target
                else "Which earlier dates should I move, and by how much?",
            )
        ]
    if SAME_DAYS.search(question) and not MOVED.search(question) and not from_today(question):
        if any(h in [tuple(ws) for ws in previous] for h in held):
            return []
        target = previous[0] if len(previous) == 1 else None
        return [
            Conflict(
                "The user keeps the earlier request's dates exactly ('that same day/interval'): "
                "use a period of kind inherit (with reference if several), not new dates.",
                f"Do you mean the same dates as before, {_span(*_ends(target), today)}?"
                if target
                else "Which of the earlier dates do you mean?",
            )
        ]
    return []


def _ends(windows) -> tuple[date, date]:
    return windows[0].start, windows[-1].end


def _windows(part: dict) -> list:
    from app.analysis.evidence import Window

    return [Window.model_validate(w) for w in part.get("windows", [])]


def _moved(window, days: int):
    from app.analysis.evidence import Window

    shift = timedelta(days=days)
    return Window(start=window.start + shift, end=window.end + shift)


# ---- periods counted from today ----

FROM_TODAY = re.compile(
    r"\b(?:yesterday|today|tonight|last night|this (?:week|month|year)|"
    r"(?:last|past|previous) (?:\d+|one|two|three|four|five|six|seven|ten|fourteen|thirty) "
    r"(?:days?|weeks?|months?)|(?:last|past) (?:week|month|year|fortnight)|\d+ days? ago)\b",
    re.IGNORECASE,
)
REFERS_TO_EARLIER = re.compile(
    r"\b(?:that|those|then|same|earlier than|before that|after that|previous (?:one|date|day)|"
    r"prior (?:one|date|day))\b",
    re.IGNORECASE,
)
LAST_DAYS = re.compile(r"\b(?:last|past) (?:\d+|[a-z]+) days?\b", re.IGNORECASE)
ENDING_YESTERDAY = re.compile(r"\bcomplete days?\b|\bending yesterday\b|\bup to yesterday\b", re.I)
CALENDAR = re.compile(r"\b(this week|last week|this month|last month)\b", re.IGNORECASE)
CALENDAR_MODIFIED = re.compile(
    r"\b(?:before|after|ago|prior to|earlier than|following)\b", re.IGNORECASE
)


def from_today(question: str) -> bool:
    return bool(FROM_TODAY.search(question)) and not REFERS_TO_EARLIER.search(question)


def _counted_from_today(reading, request, question: str, today: date) -> list[Conflict]:
    if not from_today(question):
        return []
    found = []
    # Which part "yesterday" belongs to is clear only with one part and no words about the
    # earlier days ("shift steps two days earlier, and my heart rate yesterday" has both).
    only_today = len(reading.parts) == 1 and shift_said(question) is None
    only_today = only_today and not SAME_DAYS.search(question)
    if only_today and any(p.anchor == "previous" for part in reading.parts for p in part.periods):
        found.append(
            Conflict(
                "The question counts its days from today ('yesterday', 'last 7 days', "
                "'this week'): anchor every such period to today, not to the earlier request.",
                "Do you mean counted back from today?",
            )
        )
    ends_yesterday = [
        p
        for part in reading.parts
        for p in part.periods
        if p.kind == "rolling" and p.anchor == "today" and p.offset_days != 0
    ]
    if ends_yesterday and LAST_DAYS.search(question) and not ENDING_YESTERDAY.search(question):
        found.append(
            Conflict(
                "'The last N days' ends today in this app (offset_days 0); only 'N complete "
                "days' or 'ending yesterday' ends yesterday.",
                "Should the period include today?",
            )
        )
    named = CALENDAR.findall(question)
    if len(named) == 1 and not CALENDAR_MODIFIED.search(question):
        phrase = named[0].lower()
        span = period_range(phrase, today)
        monday = today - timedelta(days=today.weekday())
        calendar = {
            "this week": (monday, today),
            "this month": (today.replace(day=1), today),
        }.get(phrase, span)
        ends = {(p.windows[0].start, p.windows[-1].end) for p in request.parts if p.windows}
        if span and request.parts and not ({span, calendar} & ends):
            found.append(
                Conflict(
                    f"'{phrase}' is the calendar period {span[0]} to {span[1]} (weeks start on "
                    "Monday): use a calendar period for the part it belongs to.",
                    f"Do you mean {phrase}, {_span(span[0], span[1], today)}?",
                )
            )
    return found


# ---- a metric called by its catalog name ----

NEGATED = re.compile(
    r"\b(?:not|no|instead of|rather than|except|without|excluding|other than|besides|apart from)"
    r"\b[\w\s'-]{0,20}$",
    re.IGNORECASE,
)


def catalog_named(question: str) -> list[str]:
    """Metrics the question calls by their catalog name ("time in the cardio heart-rate zone"),
    longest first so a shorter name inside a longer one does not count; a name after "not",
    "instead of" or inside quotes is not asked for."""
    lowered = question.lower().replace("heart rate", "heart-rate")
    found, taken = [], []
    for key, info in sorted(METRICS.items(), key=lambda item: -len(item[1].label)):
        name = info.label.lower().replace("heart rate", "heart-rate")
        at = lowered.find(name)
        if at < 0 or any(start <= at < end for start, end in taken):
            continue
        taken.append((at, at + len(name)))
        before = lowered[:at]
        if NEGATED.search(before) or before.count('"') % 2 or before.count("“") > before.count("”"):
            continue
        found.append(key)
    return found


def _metric(reading, question: str) -> list[Conflict]:
    named = catalog_named(question)
    if len(named) != 1 or len(reading.parts) != 1:
        return []
    metrics = reading.parts[0].metrics
    if not metrics or named[0] in metrics or metrics == ["food_logs"]:
        return []
    return [
        Conflict(
            f"The user names '{label(named[0])}', registry id {named[0]}; the reading has "
            f"{', '.join(metrics)}. Use the metric the user named.",
            f"Do you mean your {label(named[0])}?",
        )
    ]


# ---- meals ----

MEALS = {
    "breakfast": "BREAKFAST",
    "brunch": "BREAKFAST",
    "lunch": "LUNCH",
    "dinner": "DINNER",
    "supper": "DINNER",
    "snack": "SNACK",
    "snacks": "SNACK",
}
MEAL = re.compile(r"\b(" + "|".join(MEALS) + r")\b", re.IGNORECASE)
SAME_MEAL = re.compile(r"\b(?:same|that|this) meal\b", re.IGNORECASE)
EVERY_MEAL = re.compile(r"\b(?:all|every|each|any) meals?\b|\bexcept\b|\bbut not\b", re.I)


def _meal(reading, question: str) -> list[Conflict]:
    named = {MEALS[m.lower()] for m in MEAL.findall(question)}
    found = []
    for part in reading.parts:
        if part.metrics != ["food_logs"]:
            continue
        if part.meal_type and part.meal_type not in named and not SAME_MEAL.search(question):
            found.append(
                Conflict(
                    "No meal is named in this question: leave meal_type null (every meal) "
                    "unless the user names a meal or says 'the same meal'.",
                    f"Should I look at {part.meal_type.lower()} only, or every meal?",
                )
            )
        elif (
            len(named) == 1
            and part.meal_type is None
            and len(reading.parts) == 1
            and not EVERY_MEAL.search(question)
        ):
            meal = next(iter(named))
            found.append(
                Conflict(
                    f"The user names a meal: set meal_type {meal}.",
                    f"Should I look at {meal.lower()} only?",
                )
            )
    return found


# ---- a stated comparison on a count of days ----

COMPARATORS = {
    "above": ">",
    "over": ">",
    "more than": ">",
    "greater than": ">",
    "higher than": ">",
    "at least": ">=",
    "no less than": ">=",
    "below": "<",
    "under": "<",
    "less than": "<",
    "fewer than": "<",
    "lower than": "<",
    "at most": "<=",
    "no more than": "<=",
    "exactly": "==",
}
COMPARED = re.compile(
    r"\b(" + "|".join(sorted(COMPARATORS, key=len, reverse=True)) + r") "
    r"(\d[\d,]*(?:\.\d+)?)(?![\d,]|\.\d)(?! ?(?:days?|nights?|weeks?|months?|years?|times)\b)"
    r"(?!k\b)",
    re.IGNORECASE,
)
SAID = {">": "above", ">=": "at or above", "<": "below", "<=": "at or below", "==": "exactly"}


def _comparison(reading, question: str) -> list[Conflict]:
    stated = COMPARED.findall(question)
    counts = [p for p in reading.parts if p.operation == "count"]
    if len(stated) != 1 or len(counts) != 1:
        return []
    words, number = stated[0]
    sign, value = COMPARATORS[words.lower()], float(number.replace(",", ""))
    part = counts[0]
    if part.comparison == sign and part.threshold == value:
        return []
    return [
        Conflict(
            f"The user said '{words} {number}': comparison {sign}, threshold {value:g} (in the "
            "unit the user said). 'Above' never includes the value itself; 'at least' does.",
            f"Should I count the days {SAID[sign]} {value:g}?",
        )
    ]


def conflicts(reading, request, question: str, state: dict, today: date) -> list[Conflict]:
    """Every fact in the question the resolved request contradicts; empty when it agrees."""
    if request.subject != "self" or reading.kind not in DATA_KINDS:
        return []
    return [
        *_written(request, question),
        *_earlier_days(request, question, state, today),
        *_counted_from_today(reading, request, question, today),
        *_metric(reading, question),
        *_meal(reading, question),
        *_comparison(reading, question),
    ]
