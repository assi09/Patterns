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
from app.agent.present import ALIASES, METRICS, label

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

COUNT = (
    r"(\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fourteen|fifteen|"
    r"twenty|twenty-one|twenty-eight|thirty)"
)
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
    "eleven": 11,
    "twelve": 12,
    "fourteen": 14,
    "fifteen": 15,
    "twenty": 20,
    "twenty-one": 21,
    "twenty-eight": 28,
    "thirty": 30,
}
EARLIER = ("earlier", "back", "before", "sooner")


def _number(word: str) -> int:
    return WORDS.get(word.lower()) or int(word)


def shift_said(text: str) -> int | None:
    """The days a follow-up moves by: -2 for "two days earlier", +3 for "forward 3 days". None
    for none, for more than one, or for a shift counted from today ("two days before today")."""
    if adjacent_said(text) is not None:
        return None  # "the 5 days before that block" is a block next to it, not a shift
    found = SHIFT.findall(text)
    if len(found) != 1:
        return None
    a, way_a, way_b, b = found[0]
    count, way = (a, way_a) if a else (b, way_b)
    return -_number(count) if way.lower() in EARLIER else _number(count)


# "The six days immediately following that block", "the next 7 days after that", "the 5 days
# before those": a block of days next to an earlier one, starting the day after its last day or
# ending the day before its first. Not a shift: "move that range forward one day" is a shift.
_NIGHTS = r"(?:calendar |whole |full |complete |consecutive )?(?:days|nights|dates)"
_RIGHT = r"(?:immediately |right |just |directly )"
ADJACENT_AFTER = re.compile(
    rf"\b(?:next|following|subsequent|succeeding) {COUNT} {_NIGHTS}\b|"
    rf"\bthe {COUNT} {_NIGHTS} {_RIGHT}?(?:after|following)\b|"
    rf"\b{COUNT} {_NIGHTS} {_RIGHT}(?:after|following)\b",
    re.IGNORECASE,
)
ADJACENT_BEFORE = re.compile(
    rf"\b(?:previous|preceding|prior) {COUNT} {_NIGHTS}\b|"
    rf"\bthe {COUNT} {_NIGHTS} {_RIGHT}?(?:before|preceding|prior to|leading up to)\b|"
    rf"\b{COUNT} {_NIGHTS} {_RIGHT}(?:before|preceding|prior to|leading up to)\b",
    re.IGNORECASE,
)


def adjacent_said(text: str) -> tuple[str, int] | None:
    """("after", 6) for "the six days immediately following that block", ("before", 5) for "the
    5 days before those"; None for none, for both, or for a block counted from today ("the
    previous 7 days" alone is the last 7 days: `from_today` and `LAST_N` read that)."""
    after, before = _counts(ADJACENT_AFTER, text), _counts(ADJACENT_BEFORE, text)
    if len(after) + len(before) != 1 or not REFERS_TO_EARLIER.search(text):
        return None
    if AROUND.search(text):
        return None  # "that date and the three dates before it" includes that date
    return ("after", after[0]) if after else ("before", before[0])


def _counts(pattern: re.Pattern, text: str) -> list[int]:
    """The number in each match, whichever alternative of the pattern matched."""
    return [_number(next(g for g in m.groups() if g)) for m in pattern.finditer(text)]


# "Five consecutive days", "the 3 days": a stated length. "2 days ago" and "two days earlier"
# are a point and a shift, not a length.
LENGTH = re.compile(
    rf"\b{COUNT} {_NIGHTS}\b(?! (?:ago|earlier|later|back|forward|sooner|ahead|from today|"
    r"before today|after today))",
    re.IGNORECASE,
)


def length_said(text: str) -> int | None:
    found = _counts(LENGTH, text)
    if len(found) != 1 or shift_said(text) is not None:
        return None
    return found[0]


# "Same week" after a question about Sep 1-7 is Sep 1-7, not the calendar week holding today (the
# v6 audit counted Aug 31-Sep 6).
_PERIOD_NOUNS = (
    r"(?:date|day|night|interval|stretch|period|range|window|span|dates|days|nights|week|weeks|"
    r"month|fortnight|weekend|block|timeframe|time frame)"
)
SAME_DAYS = re.compile(
    rf"\b(?:that|those)(?: same| identical| whole| entire)? {_PERIOD_NOUNS}\b|"
    rf"\b(?:the )?(?:same|identical) {_PERIOD_NOUNS}\b|\bkeep (?:its|their|the)"
    r"(?: \w+)? dates\b",
    re.IGNORECASE,
)
# Any of these and "that day" may be a point to count from, not the days themselves.
MOVED = re.compile(
    r"\b(?:earlier|later|before|after|ago|prior|previous|next|following|hours?|back|forward|"
    r"ahead|since|until)\b",
    re.IGNORECASE,
)


def _message(state: dict, text: str) -> str:
    """The whole message, for checks that a period is absent: what the clause's own words leave
    out may be in the rest of it."""
    return state.get(MESSAGE) or text


MESSAGE = "_message"


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
    previous, message = _previous(state), _message(state, text)
    if not previous or not SAME_DAYS.search(text):
        return None
    # Whatever moves or names days anywhere in the message: the reader's copy of a clause's words
    # can stop short of them (the v6 audit).
    if written(message) != ([], []) or shift_said(message) is not None:
        return None
    if MOVED.search(message) or from_today(message):
        return None
    # "Take that day as the last of five consecutive days": "that day" is an endpoint here, not
    # the interval to reuse (the v5 audit sent the right five-day reading back and got one day).
    if length_said(message) is not None or adjacent_said(message) is not None:
        return None
    if CALENDAR.search(message) and not re.search(r"\bsame\b", message, re.I):
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
    names = [(key, info.label) for key, info in METRICS.items()]
    names += [(key, alias) for key, aliases in ALIASES.items() for alias in aliases]
    for key, words in sorted(names, key=lambda item: -len(item[1])):
        if key in found:
            continue
        name = words.lower().replace("heart rate", "heart-rate")
        match = re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", lowered)
        at = match.start() if match else -1
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
    metrics = list(resolved.metrics) or part.metrics
    if metrics == ["food_logs"] and named and all(m in WEARABLE_ENERGY for m in named):
        # "Switch from intake to expenditure: calories burned?" read the meals again (the v6
        # audit): energy burned is the wearable's, never the food log's.
        return Conflict(
            "metric",
            f"'{text}' names {label(named[0])}, the wearable's registry id {named[0]}, not food "
            "eaten: read it as a data clause on that metric, not food_logs.",
            f"Do you mean your {label(named[0])} from your tracker?",
        )
    if len(named) != 1 or not metrics or named[0] in metrics or metrics == ["food_logs"]:
        return None
    return Conflict(
        "metric",
        f"'{text}' names '{label(named[0])}', registry id {named[0]}; the reading has "
        f"{', '.join(metrics)}. Use the metric the words name.",
        f"Do you mean your {label(named[0])}?",
    )


WEARABLE_ENERGY = ("calories",)

# ---- the statistic the words name ----

STATISTICS = {
    "min": re.compile(r"\b(?:lowest|minimum|min|smallest|(?<!at )least)\b", re.I),
    "max": re.compile(
        r"\b(?:highest|maximum|max|largest|biggest|peak(?! (?:heart[- ]rate )?zone)|top)\b", re.I
    ),
    "median": re.compile(r"\bmedian\b", re.I),
    "mean": re.compile(r"\b(?:average|mean|avg|per day on average)\b", re.I),
    "sum": re.compile(r"\b(?:total|sum|combined|altogether|in all)\b", re.I),
}


def _without_names(text: str) -> str:
    lowered = text.lower().replace("heart rate", "heart-rate")
    names = [info.label for info in METRICS.values()]
    names += [alias for aliases in ALIASES.values() for alias in aliases]
    for name in sorted(names, key=len, reverse=True):
        lowered = lowered.replace(name.lower().replace("heart rate", "heart-rate"), " ")
    return lowered


FREE_OPERATIONS = ("count", "compare", "correlate", "trend", "coverage", "food", "describe")


def _statistic(text, part, resolved, state, today) -> Conflict | None:
    """ "Back to the first result: give the lowest day's value" kept the mean (the v6 audit). One
    statistic named, and the reading computes another."""
    if resolved.operation in FREE_OPERATIONS or COMPARED.search(text):
        return None
    windows = resolved.windows
    if len(windows) == 1 and windows[0].start == windows[0].end:
        return None  # on one day every statistic is that day's value
    plain = _without_names(text)  # "time in the peak heart-rate zone" names no maximum
    named = [op for op, words in STATISTICS.items() if words.search(plain)]
    if len(named) != 1 or resolved.operation == named[0]:
        return None
    return Conflict(
        "statistic",
        f"'{text}' asks for the {named[0]}: operation {named[0]}, not {resolved.operation} "
        "(an earlier result's operation is kept only when the words name none).",
        f"Should I give the {named[0]}?",
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


# ---- relations to an earlier result, and lengths ----


def _earlier(part, state: dict) -> list | None:
    """The earlier result's windows this part refers to: the one it names, else the only one."""
    previous = _previous(state)
    if part.reference is not None:
        return previous[part.reference] if part.reference < len(previous) else None
    return previous[0] if len(previous) == 1 else None


def _adjacent(text, part, resolved, state, today) -> Conflict | None:
    said = adjacent_said(text)
    earlier = _earlier(part, state)
    if said is None or earlier is None or len(earlier) != 1 or written(text) != ([], []):
        return None  # two earlier periods: resolving asks which one
    way, days = said
    if way == "after":
        start = earlier[-1].end + timedelta(days=1)
        end = earlier[-1].end + timedelta(days=days)
    else:
        start = earlier[0].start - timedelta(days=days)
        end = earlier[0].start - timedelta(days=1)
    if [(w.start, w.end) for w in resolved.windows] == [(start, end)]:
        return None
    kind = "after_earlier" if way == "after" else "before_earlier"
    return Conflict(
        "adjacent",
        f"'{text}' is the {days} days right {way} the earlier result's days: {start} to {end} "
        f"(a {kind} period of length {days}), not that period moved by a day.",
        f"Do you mean {_span(start, end, today)}?",
    )


def _length(text, part, resolved, state, today) -> Conflict | None:
    days = length_said(text)
    if days is None or part.operation == "compare" or len(resolved.windows) != 1:
        return None
    if LAST_N.search(text) or adjacent_said(text) is not None or AROUND.search(text):
        return None  # their own checks say where the days end, too
    window = resolved.windows[0]
    if window.days == days:
        return None
    return Conflict(
        "length",
        f"'{text}' asks about {days} days: the period must be exactly {days} days long, first "
        "and last included, ending or starting where the words say (days_ending with length "
        f"{days} when they end on an earlier day).",
        f"Do you mean a period of {days} days?",
    )


# Words that name or move a period. A follow-up with none of them keeps the earlier days: "exclude
# the days right on the boundary and count again" got new dates (the v5 audit).
PERIOD_WORDS = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|march|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|monday|tuesday|wednesday|"
    r"thursday|friday|saturday|sunday|weekends?|weekdays?|week|month|year|fortnight|today|"
    r"yesterday|tomorrow|tonight|night|morning|evening|since|until|till|ago|history|ever|"
    r"all[- ]time|overall|recent(?:ly)?|lately|date|dates|period|range|window|span|stretch|"
    r"block|interval|first|last|previous|next|following|before|after|earlier|later|peak\w*|"
    r"best|worst|highest day|lowest day|day|calendar|back|forward|ahead|shift\w*|mov\w*|"
    r"push\w*|slid\w*|sooner|prior|preceding|start\w*|end\w*|through|from)\b|\d",
    re.IGNORECASE,
)
AGAIN = re.compile(
    r"\b(?:again|that|those|same|it|instead|too|also|recalculate|redo|repeat|recount|rerun|"
    r"re-?do|re-?count)\b",
    re.IGNORECASE,
)


def _unnamed_period(text, part, resolved, state, today) -> Conflict | None:
    previous = _previous(state)
    if not previous or not resolved.windows:
        return None
    follows = part.reference is not None or part.operation == "inherit" or AGAIN.search(text)
    message = _message(state, text)
    if not follows or PERIOD_WORDS.search(COMPARED.sub(" ", message)):
        return None
    if list(resolved.windows) in previous:
        return None
    target = _earlier(part, state)
    return Conflict(
        "kept_days",
        f"'{text}' names no dates and moves none: it keeps the earlier result's days exactly "
        "(same_as_earlier), with only what the words change.",
        f"Do you mean the same dates as before, {_span(*_ends(target), today)}?"
        if target
        else "Which dates do you mean?",
    )


# "Exclude the days right on the boundary", "not counting the ones exactly at it": the same count
# with the threshold made strict. The dates, metric and threshold stay (the v5 audit moved the
# dates and kept "at or below").
EXCLUDE_EQUAL = re.compile(
    r"\b(?:exclud\w*|without|not count\w*|leav\w* out|drop\w*|minus|remov\w*|ignor\w*|skip\w*|"
    r"not including|other than)\b[\w\s,'-]{0,40}?\b(?:boundary|threshold|cut-?off|line|limit|"
    r"exactly|equal\w*|tie[sd]?|right at|on the (?:mark|number))\b|"
    r"\bstrictly (?:above|below|over|under|more|less|greater|fewer|higher|lower)\b",
    re.IGNORECASE,
)
STRICT = {"<=": "<", ">=": ">", "<": "<", ">": ">"}


def _strictness(text, part, resolved, state, today) -> Conflict | None:
    if not EXCLUDE_EQUAL.search(text) or COMPARED.search(text):
        return None
    index = part.reference if part.reference is not None else 0
    earlier = state.get("data", [])
    if index >= len(earlier) or (part.reference is None and len(earlier) != 1):
        return None
    before = earlier[index]
    if before.get("operation") != "count" or before.get("comparison") not in STRICT:
        return None
    sign, windows = STRICT[before["comparison"]], _windows(before)
    if (
        resolved.operation == "count"
        and resolved.comparison == sign
        and resolved.threshold == before.get("threshold")
        and list(resolved.windows) == windows
    ):
        return None
    return Conflict(
        "strict",
        f"'{text}' repeats the earlier count leaving out the days exactly at its threshold: "
        f"keep its metric, its dates and threshold {before.get('threshold'):g}, and change the "
        f"comparison {before['comparison']} to {sign}. 'The boundary' here is the threshold, not "
        "the first and last day.",
        f"Should I count the same days again, {SAID[sign]} {before.get('threshold'):g}?",
    )


# "In January 2027", "during March": a named month is that whole month, never recent days (the v5
# audit answered January 2027 with November).
MONTH_NAMED = re.compile(
    r"(?<!\bof )(?<!\d )\b(january|february|march|april|june|july|august|september|october|"
    r"november|december|may(?=,? (?:of )?\d{4})|(?:jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|"
    r"dec)(?=\.?,? (?:of )?\d{4}))\.?(?:,? (?:of )?(\d{4}))?\b(?! ?\d{1,2}\b)",
    re.IGNORECASE,
)


MONTH_TO = re.compile(r"\s*(?:–|—|-|to|through|thru|until|till|and)\s*$", re.IGNORECASE)


def months_named(text: str) -> list[tuple[tuple[int | None, int], tuple[int | None, int]]]:
    """Each span of whole months the words name, as (first month, last month), each (year or
    None, month): "January 2027" is one month, "from January through March 2026" one span of
    three, "compare January with March" two. Dates and "the first week of November" are left out.
    """
    plain = text
    ranges, singles = written(text)
    for words in [w for *_, w in ranges] + [w for _, w in singles]:
        plain = plain.replace(words, " " * len(words))
    if INSIDE.search(plain):
        return []
    found = list(MONTH_NAMED.finditer(plain))
    spans, at = [], 0
    while at < len(found):
        first = found[at]
        start = (_year(first.group(2)), _month(first.group(1)))
        if at + 1 < len(found):
            second = found[at + 1]
            between = plain[first.end() : second.start()]
            joined = MONTH_TO.match(between) and (
                "and" not in between.lower() or BETWEEN_WORD.search(plain[: first.start()])
            )
            if joined:
                end = (_year(second.group(2)), _month(second.group(1)))
                if start[0] is None and end[0] is not None:  # "January through March 2026"
                    start = (end[0] - (start[1] > end[1]), start[1])
                spans.append((start, end))
                at += 2
                continue
        spans.append((start, start))
        at += 1
    return spans


BETWEEN_WORD = re.compile(r"\bbetween\s*$", re.IGNORECASE)


def _whole_month(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)


def _month_windows(year: int, month: int, today: date) -> list[tuple[date, date]]:
    """The whole month, and for the current one also up to today (as "this month" is)."""
    start, end = _whole_month(year, month)
    return [(start, end), (start, today)] if start <= today < end else [(start, end)]


def _named_month(text, part, resolved, state, today) -> Conflict | None:
    named = months_named(text)
    if not named or len(named) > 2:
        return None
    ends = [(w.start, w.end) for w in resolved.windows]
    wrong = []
    for (first_year, first), (last_year, last) in named:
        if last_year is None:  # "in February": the whole month is checked, its year is not
            starts = {(w.start.month, w.start.day) for w in resolved.windows}
            if (first, 1) in starts:
                continue
        years = [last_year] if last_year else [today.year, today.year - 1]
        fits = []
        for year in years:
            start_year = first_year or year - (first > last)
            start = _whole_month(start_year, first)[0]
            fits += [(start, end) for _, end in _month_windows(year, last, today)]
        if not any(fit in ends for fit in fits):
            past = [f for f in fits if f[0] <= today]
            wrong.append(past[0] if past else fits[0])
    if not wrong:
        return None
    start, end = wrong[0]
    whole = (
        f"{start:%B %Y}"
        if (start.year, start.month) == (end.year, end.month)
        else (f"{start:%B %Y} through {end:%B %Y}")
    )
    return Conflict(
        "named_month",
        f"'{text}' names {whole}: its period is those whole months, {start} to {end}, as one "
        "period (dates, or a month period with its year), past or future, never other days.",
        f"Do you mean {whole}?",
    )


Check = Callable[..., Conflict | None]
CHECKS: tuple[Check, ...] = (
    _written,
    _shift,
    _same_days,
    _around_earlier,
    _adjacent,
    _length,
    _unnamed_period,
    _strictness,
    _named_month,
    _statistic,
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
    state = {**state, MESSAGE: question}
    own = [_own_words(part, question) for part, _ in pairs]
    if getattr(reading, "clause_count", 0) == 1:
        # One clause is the whole message: the reader's copy of its words can stop short of the
        # dates ("what does the same statistic come out to" without "on the next two dates").
        own = [question]
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
