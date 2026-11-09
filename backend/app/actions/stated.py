"""A draft must say what the person said: their duration, their clock time, their day.

The model fills in a log's fields, and when a value is refused it can be tempted to change the value
until it passes (a workout that had not finished yet, moved to the day before and shortened). The
confirmation card shows the result, but a wrong card is still a wrong card. So code compares the
draft with the person's own words, and refuses a draft that contradicts them.

It only checks what was stated: words it cannot read leave the draft alone. Any stated value may
match, since someone may mention several ("ran 5k in 30 min after a 1 hour nap") or correct
themselves, and all the replies in a logging request count.
"""

import re
from collections.abc import Sequence
from datetime import datetime, timedelta

from app.actions.schemas import FoodLog, WorkoutLog

NOT_YET_GRACE = timedelta(minutes=15)
RECENT = timedelta(hours=24)  # with no day named, "at 3 pm" is the latest 3 pm that has passed
TOLERANCE_S = 60

_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}
DURATION = re.compile(
    r"\b(?:"
    r"(?P<half>half (?:an? )?hour)"
    r"|(?P<one_half>(?:(?:an?|one|1) )?hour and (?:a )?half)"
    r"|(?:(?P<hours>\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b|(?P<word>an?|one|two|three) hours?\b)"
    r"(?:\s*(?:and\s*)?(?P<and_minutes>\d+)\s*(?:minutes?|mins?)\b)?"
    r"|(?P<minutes>\d+)\s*(?:minutes?|mins?)\b"
    r")",
    re.IGNORECASE,
)
CLOCK = re.compile(
    r"\b(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<half>am|pm)\b"
    r"|\b(?P<hour24>\d{1,2}):(?P<minute24>\d{2})\b",
    re.IGNORECASE,
)
UNTIL_NOW = re.compile(
    r"\b(?:just (?:finished|ended|done|now)|(?:un)?till? now|so far|finished now)\b", re.IGNORECASE
)
WORD = re.compile(r"[a-z0-9]+")
GENERIC_TYPES = ("WORKOUT", "OTHER")
REQUEST_WORDS = set(
    [
        "log",
        "add",
        "record",
        "track",
        "save",
        "enter",
        "it",
        "this",
        "that",
        "a",
        "an",
        "the",
        "my",
        "me",
        "please",
        "pls",
        "now",
        "just",
        "i",
        "im",
        "i'm",
        "m",
        "did",
        "do",
        "doing",
        "done",
        "had",
        "have",
        "was",
        "workout",
        "workouts",
        "exercise",
        "exercises",
        "session",
        "training",
        "yes",
        "ok",
        "okay",
        "for",
        "at",
        "started",
        "start",
        "from",
        "to",
        "it's",
        "its",
    ]
)
JUST_NOW = re.compile(r"\bjust (?:now|did|finished|ended|got back)\b", re.IGNORECASE)
CORRECTION = re.compile(r"\b(?:no wait|actually|sorry|i mean|make that|correction)\b", re.I)
OWN_OFFSET = re.compile(r"\b(?:utc|gmt)\b|[+-]\d{2}:\d{2}\b", re.IGNORECASE)
NAMED_DAY = re.compile(
    r"\b(?:yesterday|last (?:night|week)|\d+ days? ago|(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|"
    r"sat(?:ur)?|sun)(?:day)?|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
    r"aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|\d{1,2}(?:st|nd|rd|th)|"
    r"\d{1,2}[/-]\d{1,2})\b",
    re.IGNORECASE,
)


def _names_an_activity(text: str) -> bool:
    """Whether anything is left once the request's own words, times and durations are gone."""
    bare = CLOCK.sub(" ", DURATION.sub(" ", text.casefold()))
    return any(word not in REQUEST_WORDS and not word.isdigit() for word in WORD.findall(bare))


def durations(text: str) -> set[int]:
    """Every duration named in the text, in seconds."""
    found = set()
    for match in DURATION.finditer(text):
        if match["half"]:
            found.add(1800)
        elif match["one_half"]:
            found.add(5400)
        elif match["minutes"]:
            found.add(int(match["minutes"]) * 60)
        else:
            word = (match["word"] or "").lower()
            hours = float(match["hours"]) if match["hours"] else _NUMBER_WORDS[word]
            found.add(round(hours * 3600) + int(match["and_minutes"] or 0) * 60)
    return found


def clock_times(text: str) -> set[tuple[int, int]]:
    """Every time of day named in the text, as (hour, minute) on a 24-hour clock."""
    found = set()
    for match in CLOCK.finditer(text):
        if match["hour"]:
            hour = int(match["hour"]) % 12 + (12 if match["half"].lower() == "pm" else 0)
            found.add((hour, int(match["minute"] or 0)))
        else:
            hour = int(match["hour24"])
            found.add((hour, int(match["minute24"])))
            if 1 <= hour <= 12:  # "at 3:30" with no am or pm can be either
                found.add(((hour % 12) + 12, int(match["minute24"])))
    return {(h, m) for h, m in found if h < 24 and m < 60}


def _on_the_clock(moment: datetime, times: set[tuple[int, int]]) -> bool:
    minutes = moment.hour * 60 + moment.minute
    return any(abs(minutes - (h * 60 + m)) <= 1 for h, m in times)


def _shifted(value: object, days: int) -> object:
    return (datetime.fromisoformat(str(value)) - timedelta(days=days)).isoformat()


def latest_past(given: dict, said: Sequence[str], local_now: datetime) -> dict:
    """A clock time with no day that has not come yet today means yesterday: at 1 am, "at 7 am"
    is the morning that has gone. Corrected here, so an answer does not depend on the model."""
    key = "startTime" if "startTime" in given else "consumedAt"
    try:
        start = datetime.fromisoformat(str(given[key]))
    except (KeyError, ValueError):
        return given
    words = "\n".join(said)
    named = NAMED_DAY.search(words)
    if start.tzinfo is None:
        return given
    if "endTime" in given and JUST_NOW.search(words):
        # "20 minutes just now" ended now; the model often starts it now instead.
        try:
            over = datetime.fromisoformat(str(given["endTime"])) - local_now
        except ValueError:
            return given
        if over > timedelta(0) and start <= local_now + NOT_YET_GRACE:
            return {
                **given,
                key: (start - over).isoformat(),
                "endTime": local_now.isoformat(),
            }
        return given
    if named or start <= local_now + NOT_YET_GRACE:
        return given
    moved = {**given, key: _shifted(given[key], 1)}
    if "endTime" in given:
        moved["endTime"] = _shifted(given["endTime"], 1)
    return moved


def lacks_a_duration(said: Sequence[str]) -> bool:
    """Nothing in their words says how long it lasted, so there is no point drafting it yet."""
    text = "\n".join(said)
    return not durations(text) and len(clock_times(text)) < 2 and not UNTIL_NOW.search(text)


def _corrected(said: Sequence[str]) -> set[int]:
    """After "no wait" or "actually", only what comes next counts as the duration."""
    for words in reversed(said):
        parts = CORRECTION.split(words)
        if len(parts) > 1 and (latest := durations(parts[-1])):
            return latest
    return set()


def mismatch(log: FoodLog | WorkoutLog, said: Sequence[str], local_now: datetime) -> str | None:
    """What the draft gets wrong against the person's words, for the model to put right; None if
    nothing contradicts them."""
    text = "\n".join(said)
    zone = local_now.tzinfo
    start = (log.start_time if isinstance(log, WorkoutLog) else log.consumed_at).astimezone(zone)
    moments = [start]
    if isinstance(log, WorkoutLog):
        moments.append(log.end_time.astimezone(zone))
        stated = _corrected(said) or durations(text)
        if not stated and len(clock_times(text)) < 2 and not UNTIL_NOW.search(text):
            return "The person did not say how long it lasted. Ask them; never make up a duration."
        if log.exercise_type in GENERIC_TYPES and not _names_an_activity(text):
            return "The person did not say what kind of workout it was. Ask them."
        lengths = (log.active_seconds, (log.end_time - log.start_time).total_seconds())
        if stated and not any(abs(s - t) <= TOLERANCE_S for s in stated for t in lengths):
            return (
                "The duration does not match what the person said. Use the duration in their "
                "words, unchanged."
            )
    # With an offset of their own ("12:00, UTC+3") the time is theirs to place, not ours to check.
    times = set() if OWN_OFFSET.search(text) else clock_times(text)
    if times and not any(_on_the_clock(moment, times) for moment in moments):
        return (
            "The time does not match what the person said. Use the time in their words, in their "
            "local time at the top of the task."
        )
    if not NAMED_DAY.search(text) and local_now - start > RECENT:
        return (
            "The person did not name another day, so this must be within the last 24 hours. Do "
            "not move it to an earlier day."
        )
    return None
