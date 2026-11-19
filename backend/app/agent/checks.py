"""Facts code reads from the words of each request, and checks the request reader against.

Code used to rewrite the reader's output wherever a phrase matched ("that day", "this week",
"two days earlier"). Where the reader was right, that broke it: "24 hours earlier than that day"
lost its shift to "that day" (Codex's live review, 2026-11-19). Code never rewrites a reading from
words: it checks the **resolved** request against what the words fix, so a correct reading passes
however the reader expressed it. A contradiction is sent back to the reader once, stating it; if
the reader keeps it, the person is asked.

Each check runs on the words of the clause it belongs to (`Part.said`, the reader's copy of them):
a check that only looked for dates anywhere in the message passed steps and heart rate with their
date ranges swapped (Codex's review of 84db5f5). A reading with no clause words, from older scripts,
is checked against the whole question, and a check then holds if any part satisfies it.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from app.agent.periods import period_range
from app.agent.present import METRICS, label

DATA_KINDS = ("data", "causality", "investigate")


@dataclass(frozen=True)
class Conflict:
    code: str  # which check, for the private trace: "written_date", "shift", ...
    retry: str  # told to the reader: the fact its reading contradicts
    ask: str  # asked of the person when the reader keeps it


def _day(day: date, today: date) -> str:
    text = f"{day:%b} {day.day}"
    return text if day.year == today.year else f"{text}, {day.year}"


def _span(start: date, end: date, today: date) -> str:
    if start == end:
        return _day(start, today)
    return f"{_day(start, today)} to {_day(end, today)}"


def _ends(windows) -> tuple[date, date]:
    return windows[0].start, windows[-1].end


def _windows(part: dict) -> list:
    from app.analysis.evidence import Window

    return [Window.model_validate(w) for w in part.get("windows", [])]


def _moved(window, days: int):
    from app.analysis.evidence import Window

    shift = timedelta(days=days)
    return Window(start=window.start + shift, end=window.end + shift)


# ---- dates and ranges written out ----

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
# Whole month names only: "decided 3 times" is not Dec 3.
MONTH = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
YEAR = r"(?:,? (\d{4}))?"
TO = r"\s*(?:–|—|-|to|through|thru|until|till)\s*"
AND = r"\s+and\s+"  # a range only after "between": "on Nov 3 and Nov 8" is two days
ISO = r"(\d{4})-(\d{2})-(\d{2})"
ISO_DAY = re.compile(rf"\b{ISO}\b")
MONTH_DAY = re.compile(rf"\b{MONTH} (\d{{1,2}})(?:st|nd|rd|th)?\b{YEAR}", re.I)
DAY_MONTH = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)? (?:of )?{MONTH}\b{YEAR}", re.I)
# "Oct 6–12, 2026", "Nov 2 to Nov 9, 2026", "2026-10-06 to 2026-10-12".
SAME_MONTH_RANGE = re.compile(
    rf"\b{MONTH} (\d{{1,2}})(?:st|nd|rd|th)?{TO}(\d{{1,2}})(?:st|nd|rd|th)?\b{YEAR}", re.I
)
TWO_MONTH_RANGE = re.compile(
    rf"\b{MONTH} (\d{{1,2}})(?:st|nd|rd|th)?{YEAR}{TO}{MONTH} (\d{{1,2}})(?:st|nd|rd|th)?\b{YEAR}",
    re.I,
)
ISO_RANGE = re.compile(rf"\b{ISO}\s*(?:–|—|to|through|thru|until|till)\s*{ISO}\b", re.I)
BETWEEN_TWO_MONTHS = re.compile(
    rf"\bbetween {MONTH} (\d{{1,2}})(?:st|nd|rd|th)?{YEAR}{AND}"
    rf"{MONTH} (\d{{1,2}})(?:st|nd|rd|th)?\b{YEAR}",
    re.I,
)
BETWEEN_SAME_MONTH = re.compile(
    rf"\bbetween {MONTH} (\d{{1,2}})(?:st|nd|rd|th)?{AND}(\d{{1,2}})(?:st|nd|rd|th)?\b{YEAR}", re.I
)
BETWEEN_ISO = re.compile(rf"\bbetween {ISO}{AND}{ISO}\b", re.I)
# "the week of Nov 2" names a day inside the period, not one of its ends.
INSIDE = re.compile(r"\b(?:week|month) of\b|\baround\b|\bnear\b", re.I)

Day = tuple[int | None, int, int]  # (year or None, month, day)


def _month(name: str) -> int:
    return MONTHS.index(name[:3].lower()) + 1


def _year(text: str | None) -> int | None:
    return int(text) if text else None


def written(text: str) -> tuple[list[tuple[Day, Day, str]], list[tuple[Day, str]]]:
    """The ranges written out, start and end, and the single dates outside them. A range's year
    written once at its end belongs to its start too, unless the start's month is later
    ("Dec 29 – Jan 1, 2027" starts in 2026)."""
    ranges, taken = [], []

    def add(start: Day, end: Day, match: re.Match) -> None:
        if any(a <= match.start() < b for a, b in taken):
            return
        if start[0] is None and end[0] is not None:
            start = (end[0] - (start[1] > end[1]), start[1], start[2])
        ranges.append((start, end, match.group(0)))
        taken.append(match.span())

    for pattern in (BETWEEN_ISO, ISO_RANGE):
        for m in pattern.finditer(text):
            g = list(map(int, m.groups()))
            add((g[0], g[1], g[2]), (g[3], g[4], g[5]), m)
    for pattern in (BETWEEN_TWO_MONTHS, TWO_MONTH_RANGE):
        for m in pattern.finditer(text):
            a, d1, y1, b, d2, y2 = m.groups()
            add((_year(y1), _month(a), int(d1)), (_year(y2), _month(b), int(d2)), m)
    for pattern in (BETWEEN_SAME_MONTH, SAME_MONTH_RANGE):
        for m in pattern.finditer(text):
            a, d1, d2, y = m.groups()
            add((_year(y), _month(a), int(d1)), (_year(y), _month(a), int(d2)), m)
    singles = []
    for pattern, order in ((ISO_DAY, None), (MONTH_DAY, (0, 1, 2)), (DAY_MONTH, (1, 0, 2))):
        for m in pattern.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            if order is None:
                y, mo, d = map(int, m.groups())
            else:
                name, d, y = (m.groups()[i] for i in order)
                y, mo, d = _year(y), _month(name), int(d)
            singles.append(((y, mo, d), m.group(0)))
            taken.append(m.span())
    valid = [r for r in ranges if all(1 <= x[1] <= 12 and 1 <= x[2] <= 31 for x in r[:2])]
    return valid, [s for s in singles if 1 <= s[0][1] <= 12 and 1 <= s[0][2] <= 31]


def written_dates(text: str) -> list[tuple[int | None, int, int, str]]:
    """Every date written out, range ends included: (year or None, month, day, as written)."""
    ranges, singles = written(text)
    days = [(*end, words) for start, end, words in ranges for end in (start, end)]
    return days + [(*day, words) for day, words in singles]


def _is(day: date, wanted: Day) -> bool:
    year, month, number = wanted
    return day.month == month and day.day == number and (year is None or day.year == year)


def _written(text, part, resolved, state, today) -> Conflict | None:
    ranges, singles = written(text)
    if not (ranges or singles) or INSIDE.search(text):
        return None
    windows = resolved.windows
    wrong = [
        words
        for start, end, words in ranges
        if not any(_is(w.start, start) and _is(w.end, end) for w in windows)
    ] + [
        words
        for day, words in singles
        if not any(_is(w.start, day) or _is(w.end, day) for w in windows)
    ]
    if not wrong:
        return None
    said = ", ".join(wrong)
    return Conflict(
        "written_date",
        f"The words '{text}' name {said}. The period of exactly that request must start and end "
        "on those dates, as written (a range's first and last day included); do not move them, "
        "give them to another request, or inherit old dates.",
        f"I want to be sure of the dates: should I use {said}?",
    )


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


def _number(word: str) -> int:
    return WORDS.get(word.lower()) or int(word)


def shift_said(text: str) -> int | None:
    """The days a follow-up moves by: -2 for "two days earlier", +3 for "forward 3 days". None
    for none, for more than one, or for a shift counted from today ("two days before today")."""
    found = SHIFT.findall(text)
    if len(found) != 1:
        return None
    a, way_a, way_b, b = found[0]
    count, way = (a, way_a) if a else (b, way_b)
    return -_number(count) if way.lower() in EARLIER else _number(count)


SAME_DAYS = re.compile(
    r"\b(?:that|those)(?: same| identical| whole| entire)? (?:date|day|night|interval|stretch|"
    r"period|range|window|span|dates|days|nights)\b|"
    r"\b(?:the )?(?:same|identical) (?:date|day|night|dates|days|period|interval|stretch|range|"
    r"window|span)\b|\bkeep (?:its|their|the) dates\b",
    re.IGNORECASE,
)
# Any of these and "that day" may be a point to count from, not the days themselves.
MOVED = re.compile(
    r"\b(?:earlier|later|before|after|ago|prior|previous|next|following|hours?|back|forward|"
    r"ahead|since|until)\b",
    re.IGNORECASE,
)


def _previous(state: dict) -> list[list]:
    return [w for p in state.get("data", []) for w in [_windows(p)] if w]


def _shift(text, part, resolved, state, today) -> Conflict | None:
    previous, shift = _previous(state), shift_said(text)
    if not previous or shift is None or written(text) != ([], []):
        return None
    moved = [[_moved(w, shift) for w in ws] for ws in previous]
    if list(resolved.windows) in moved:
        return None
    target = moved[0] if len(moved) == 1 else None
    way = "earlier" if shift < 0 else "later"
    return Conflict(
        "shift",
        f"'{text}' moves the earlier result's days {abs(shift)} day(s) {way}: shift both ends "
        "of that period by exactly that (a shift of the earlier period), nothing else.",
        f"Do you mean {_span(*_ends(target), today)}?"
        if target
        else "Which earlier dates should I move, and by how much?",
    )


def _same_days(text, part, resolved, state, today) -> Conflict | None:
    previous = _previous(state)
    if not previous or written(text) != ([], []) or shift_said(text) is not None:
        return None
    if not SAME_DAYS.search(text) or MOVED.search(text) or from_today(text):
        return None
    if list(resolved.windows) in previous:
        return None
    target = previous[0] if len(previous) == 1 else None
    return Conflict(
        "same_days",
        f"'{text}' keeps the earlier result's dates exactly: use the same days as that result "
        "(say which result if there are several), not new dates.",
        f"Do you mean the same dates as before, {_span(*_ends(target), today)}?"
        if target
        else "Which of the earlier dates do you mean?",
    )


# "That date and the three dates immediately before it": an earlier day widened, not kept as it is.
AROUND = re.compile(
    rf"\b(?:that|this|the same) (?:date|day)\b.*?\band the {COUNT} (?:dates|days) "
    r"(?:immediately |just |right )?(before|preceding|prior to|after|following) (?:it|that)\b",
    re.IGNORECASE,
)


def _around_earlier(text, part, resolved, state, today) -> Conflict | None:
    found, previous = AROUND.search(text), _previous(state)
    if not found or not previous or len(resolved.windows) != 1:
        return None
    index = part.reference if part.reference is not None else 0
    if index >= len(previous) or (part.reference is None and len(previous) != 1):
        return None
    earlier = previous[index][-1]
    days = _number(found.group(1))
    before = found.group(2).lower() in ("before", "preceding", "prior to")
    start, end = (
        (earlier.end - timedelta(days=days), earlier.end)
        if before
        else (earlier.start, earlier.start + timedelta(days=days))
    )
    window = resolved.windows[0]
    if (window.start, window.end) == (start, end):
        return None
    return Conflict(
        "around_earlier",
        f"'{text}' is {days + 1} days, {start} to {end}: the earlier date with the {days} days "
        f"{'before' if before else 'after'} it, as one days_ending period.",
        f"Do you mean {_span(start, end, today)}?",
    )


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
CALENDAR = re.compile(r"\b(this week|last week|this month|last month)\b", re.IGNORECASE)
CALENDAR_MODIFIED = re.compile(
    r"\b(?:before|after|ago|prior to|earlier than|following)\b", re.IGNORECASE
)
# "the last 7 days", "the past fourteen days", "the 5 complete days before today".
LAST_N = re.compile(
    rf"\b(?:last|past|previous|prior) {COUNT} (?:complete |full |whole )?days?\b|"
    rf"\b{COUNT} (?:complete|full|whole) days? (?:before|ending|up to|until) (today|yesterday)\b",
    re.IGNORECASE,
)
ENDING_YESTERDAY = re.compile(
    r"\bcomplete days?\b|\bfull days?\b|\bending yesterday\b|\bup to yesterday\b", re.I
)


def from_today(text: str) -> bool:
    return bool(FROM_TODAY.search(text)) and not REFERS_TO_EARLIER.search(text)


def _anchored_today(text, part, resolved, state, today) -> Conflict | None:
    if not from_today(text) or shift_said(text) is not None or SAME_DAYS.search(text):
        return None
    if not any(p.anchor == "previous" for p in part.periods):
        return None
    return Conflict(
        "anchor_today",
        f"'{text}' counts its days from today ('yesterday', 'last 7 days', 'this week'): count "
        "from today, not from the earlier request.",
        "Do you mean counted back from today?",
    )


def _last_n_days(text, part, resolved, state, today) -> Conflict | None:
    found = LAST_N.search(text)
    if not found or REFERS_TO_EARLIER.search(text) or len(resolved.windows) != 1:
        return None
    length = _number(found.group(1) or found.group(2))
    yesterday = bool(ENDING_YESTERDAY.search(text)) or (found.group(3) or "").lower() in (
        "today",
        "yesterday",
    )
    end = today - timedelta(days=1) if yesterday else today
    if (found.group(3) or "").lower() == "yesterday":
        end = today - timedelta(days=2)  # "complete days before yesterday"
    window = resolved.windows[0]
    if (window.end - window.start).days + 1 == length and window.end == end:
        return None
    start = end - timedelta(days=length - 1)
    return Conflict(
        "last_days",
        f"'{text}' is the {length} days from {start} to {end}: {length} days long, ending "
        f"{'the day before today' if end < today else 'today'} (complete days end yesterday; "
        "'the last N days' includes today in this app).",
        f"Do you mean {_span(start, end, today)}?",
    )


def _calendar(text, part, resolved, state, today) -> Conflict | None:
    named = CALENDAR.findall(text)
    if len(named) != 1 or CALENDAR_MODIFIED.search(text) or REFERS_TO_EARLIER.search(text):
        return None
    phrase = named[0].lower()
    span = period_range(phrase, today)
    monday = today - timedelta(days=today.weekday())
    calendar = {"this week": (monday, today), "this month": (today.replace(day=1), today)}.get(
        phrase, span
    )
    ends = (resolved.windows[0].start, resolved.windows[-1].end) if resolved.windows else None
    if not span or ends in (span, calendar):
        return None
    return Conflict(
        "calendar",
        f"'{phrase}' is the calendar period {span[0]} to {span[1]} (weeks start on Monday).",
        f"Do you mean {phrase}, {_span(span[0], span[1], today)}?",
    )


# ---- a metric called by its catalog name ----

NEGATED = re.compile(
    r"\b(?:not|no|instead of|rather than|except|without|excluding|other than|besides|apart from)"
    r"\b[\w\s'-]{0,20}$",
    re.IGNORECASE,
)


def catalog_named(text: str) -> list[str]:
    """Metrics the words call by their catalog name ("time in the cardio heart-rate zone"),
    longest first so a shorter name inside a longer one does not count; a name after "not",
    "instead of" or inside quotes is not asked for."""
    lowered = text.lower().replace("heart rate", "heart-rate")
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


def _metric(text, part, resolved, state, today) -> Conflict | None:
    named = catalog_named(text)
    metrics = part.metrics
    if len(named) != 1 or not metrics or named[0] in metrics or metrics == ["food_logs"]:
        return None
    return Conflict(
        "metric",
        f"'{text}' names '{label(named[0])}', registry id {named[0]}; the reading has "
        f"{', '.join(metrics)}. Use the metric the words name.",
        f"Do you mean your {label(named[0])}?",
    )


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


def _meal(text, part, resolved, state, today) -> Conflict | None:
    if part.metrics != ["food_logs"]:
        return None
    named = {MEALS[m.lower()] for m in MEAL.findall(text)}
    if part.meal_type and part.meal_type not in named and not SAME_MEAL.search(text):
        return Conflict(
            "meal_unnamed",
            f"'{text}' names no meal: leave meal_type null (every meal) unless the words name a "
            "meal or say 'the same meal'.",
            f"Should I look at {part.meal_type.lower()} only, or every meal?",
        )
    if len(named) == 1 and part.meal_type is None and not EVERY_MEAL.search(text):
        meal = next(iter(named))
        return Conflict(
            "meal_named",
            f"'{text}' names a meal: set meal_type {meal}.",
            f"Should I look at {meal.lower()} only?",
        )
    return None


# ---- a stated comparison on a count of days ----

# Each phrase's meaning, and its meaning after "no" or "not": "no higher than 7100" is at most.
COMPARATORS = {
    "above": (">", "<="),
    "over": (">", "<="),
    "more than": (">", "<="),
    "greater than": (">", "<="),
    "higher than": (">", "<="),
    "exceeding": (">", "<="),
    "at least": (">=", None),
    "below": ("<", ">="),
    "under": ("<", ">="),
    "less than": ("<", ">="),
    "fewer than": ("<", ">="),
    "lower than": ("<", ">="),
    "at most": ("<=", None),
    "exactly": ("==", None),
    "equal to": ("==", None),
}
COMPARED = re.compile(
    r"\b(?:(not|no) )?(" + "|".join(sorted(COMPARATORS, key=len, reverse=True)) + r") "
    r"(\d[\d,]*(?:\.\d+)?)(?![\d,]|\.\d)(?! ?(?:days?|nights?|weeks?|months?|years?|times)\b)"
    r"(?!k\b)",
    re.IGNORECASE,
)
SAID = {">": "above", ">=": "at or above", "<": "below", "<=": "at or below", "==": "exactly"}


def _comparison(text, part, resolved, state, today) -> Conflict | None:
    stated = COMPARED.findall(text)
    if len(stated) != 1 or part.operation != "count":
        return None
    negated, words, number = stated[0]
    plain, flipped = COMPARATORS[words.lower()]
    sign = flipped if negated else plain
    if sign is None:  # "not at least": too unusual to hold the reader to
        return None
    value = float(number.replace(",", ""))
    if part.comparison == sign and part.threshold == value:
        return None
    said = f"{negated + ' ' if negated else ''}{words} {number}"
    return Conflict(
        "comparison",
        f"'{said}' is comparison {sign}, threshold {value:g} (in the unit the user said).",
        f"Should I count the days {SAID[sign]} {value:g}?",
    )


Check = Callable[..., Conflict | None]
CHECKS: tuple[Check, ...] = (
    _written,
    _shift,
    _same_days,
    _around_earlier,
    _anchored_today,
    _last_n_days,
    _calendar,
    _metric,
    _meal,
    _comparison,
)


def _own_words(part, question: str) -> str | None:
    """The clause's words, if the reader copied them from the message (spacing and case aside)."""
    said = " ".join((getattr(part, "said", "") or "").split())
    if len(said) < 3:
        return None
    return said if said.casefold() in " ".join(question.split()).casefold() else None


def conflicts(reading, request, question: str, state: dict, today: date) -> list[Conflict]:
    """Every fact in the words the resolved request contradicts; empty when it agrees."""
    if request.subject != "self" or not reading.parts:
        return []
    pairs = list(zip(reading.parts, request.parts, strict=False))
    if not pairs or len(reading.parts) != len(request.parts):
        return []
    own = [_own_words(part, question) for part, _ in pairs]
    found: list[Conflict] = []
    if all(own):  # each clause against its own words
        for (part, resolved), text in zip(pairs, own, strict=True):
            found += [c for check in CHECKS if (c := check(text, part, resolved, state, today))]
        return found
    for check in CHECKS:  # the whole question: a check holds if any part satisfies it
        results = [check(question, part, resolved, state, today) for part, resolved in pairs]
        if all(results):
            found.append(results[0])
    return found
