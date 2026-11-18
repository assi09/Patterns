"""Periods and parts of the day worked out by code, so every answer means the same dates.

Told in the prompt what "last week" means, two runs of one question still averaged different weeks
(7 h 22 min against 6 h 41 min, 2026-11-16), and "I ran this morning, log it" was drafted at 08:00,
at 11:29, or met with a question. The model is better at language than at calendars: code names the
dates, and the model only has to use them. The note goes after the person's words, which are kept.
"""

import re
from datetime import date, datetime, timedelta

PERIODS = re.compile(
    r"\b(this week|last week|past week|this month|last month|yesterday|last night|"
    r"the (?:last|past) (\d{1,3}) days|lately|recently)\b",
    re.IGNORECASE,
)
# A part of the day, for logging: the typical time drafted when they gave no clock time.
PARTS = (
    ("this morning", 8, 0),
    ("at lunch", 12, 30),
    ("lunchtime", 12, 30),
    ("this afternoon", 15, 0),
    ("this evening", 19, 0),
    ("tonight", 21, 0),
)
MAX_DAYS = 366
# A week or month only just begun is too short to say anything about: one Monday read as "this week"
# answered "did I hit 10k steps this week?" with today alone (2026-11-16).
MIN_WEEK_DAYS, MIN_MONTH_DAYS = 3, 7


def _span(start: date, end: date) -> str:
    return f"{start:%a %b %-d} to {end:%a %b %-d}"


# A value over days: "my total REM minutes?", "my highest steps?". With no period named, PHIA's
# questions on real people mean every day there is data; read as last night they were answered
# with one night (2026-11-16).
AGGREGATE = re.compile(
    r"\b(total|sum|average|mean|median|highest|lowest|maximum|minimum|most|least|fewest|"
    r"how many days|in all)\b",
    re.IGNORECASE,
)
ONE_DAY = re.compile(
    r"\b(today|tonight|yesterday|last night|this morning|this evening|day before|"
    r"on (?:mon|tue|wed|thu|fri|sat|sun)\w*|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"\w*\.? \d{1,2}|\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)
SPAN = re.compile(
    r"\b(week|month|year|weekend|weekday|since|days?|nights|lately|recently|so far|ever|"
    r"all time)\b",
    re.IGNORECASE,
)


def asks_over_days(question: str) -> bool:
    """A value over several days (a total, average or extreme), not about one day."""
    return bool(AGGREGATE.search(question)) and not ONE_DAY.search(question)


def names_no_period(question: str) -> bool:
    """An aggregate with no period at all: "my total REM minutes?", not "this week"."""
    return asks_over_days(question) and not SPAN.search(question)


def period(name: str, today: date, days: str | None = None) -> str | None:
    """What one period phrase means, given today."""
    name = name.lower()
    monday = today - timedelta(days=today.weekday())
    if name == "this week":
        if (today - monday).days + 1 < MIN_WEEK_DAYS:  # on a Monday people mean the last 7 days
            return f"the last 7 days, {_span(today - timedelta(days=6), today)}"
        return _span(monday, today)
    if name in ("last week", "past week"):
        return _span(monday - timedelta(days=7), monday - timedelta(days=1))
    if name == "this month":
        if today.day < MIN_MONTH_DAYS:  # early in a month: the last 30 days
            return f"the last 30 days, {_span(today - timedelta(days=29), today)}"
        return _span(today.replace(day=1), today)
    if name == "last month":
        end = today.replace(day=1) - timedelta(days=1)
        return _span(end.replace(day=1), end)
    if name == "yesterday":
        return f"{today - timedelta(days=1):%a %b %-d}"
    if name == "last night":
        return f"the night ending the morning of {today:%a %b %-d}"
    if name in ("lately", "recently"):
        return _span(today - timedelta(days=13), today)
    if days and 0 < int(days) <= MAX_DAYS:
        return _span(today - timedelta(days=int(days) - 1), today)
    return None


def period_range(name: str, today: date, days: str | None = None) -> tuple[date, date] | None:
    """The first and last day one period phrase means: the dates `period` names, as dates. A
    night or a single day is not a span to compare and gives None."""
    name = name.lower()
    monday = today - timedelta(days=today.weekday())
    if name == "this week":
        if (today - monday).days + 1 < MIN_WEEK_DAYS:
            return today - timedelta(days=6), today
        return monday, today
    if name in ("last week", "past week"):
        return monday - timedelta(days=7), monday - timedelta(days=1)
    if name == "this month":
        if today.day < MIN_MONTH_DAYS:
            return today - timedelta(days=29), today
        return today.replace(day=1), today
    if name == "last month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if name in ("lately", "recently"):
        return today - timedelta(days=13), today
    if days and 0 < int(days) <= MAX_DAYS:
        return today - timedelta(days=int(days) - 1), today
    return None


def asked_period(question: str, today: date) -> tuple[date, date] | None:
    """The span the first period phrase in a question means, if it names one."""
    for found in PERIODS.finditer(question):
        if span := period_range(found.group(1), today, found.group(2)):
            return span
    return None


def part_of_day(name: str, hour: int, minute: int, now: datetime) -> str:
    at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if at > now:
        if name in ("this morning", "at lunch", "lunchtime"):
            return f"today, earlier than {at:%H:%M}: use a time before now ({now:%H:%M})"
        return f"later today, about {at:%H:%M}, which has not happened yet"
    return f"today, {now:%a %b %-d}, about {at:%H:%M} unless they said a time"


def with_dates(question: str, now: datetime, first: date | None = None) -> str:
    """The question with a note naming the dates and times its phrases mean, or as it was. A
    total, average or extreme with no period means every day there is data, from `first`."""
    today = now.date()
    if first and first < today and names_no_period(question):
        return (
            f"{question}\n(Worked out from today, {today:%a %b %-d}: no period is named, so "
            f"all the data, {_span(first, today)}; name those dates in the answer.)"
        )
    meanings: dict[str, str] = {}
    for found in PERIODS.finditer(question):
        phrase = found.group(1).lower()
        if (meaning := period(phrase, today, found.group(2))) and phrase not in meanings:
            meanings[phrase] = meaning
    lowered = question.lower()
    for name, hour, minute in PARTS:
        if name in lowered and name not in meanings:
            meanings[name] = part_of_day(name, hour, minute, now)
    if not meanings:
        return question
    said = "; ".join(f"{phrase} = {meaning}" for phrase, meaning in meanings.items())
    return f"{question}\n(Worked out from today, {today:%a %b %-d}: {said}.)"
