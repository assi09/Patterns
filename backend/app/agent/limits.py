"""What the person's data cannot answer, recognised by code so the reply says so plainly.

The conversation evaluation (2026-11-16) found each of these answered badly: "how did my wife
sleep?" got the medical refusal, "how will I sleep tonight?" got shift-work tips, "how did I sleep
on January 3 2025?" (before the data starts) failed on the year, and "am I drinking more water?" got
"you haven't logged any food". Each is a class of question, so each has a rule here, not a phrase.
"""

import re
from datetime import date

from app.agent.verifier import MONTHS

RELATIONS = (
    r"wife|husband|partner|girlfriend|boyfriend|fianc[eé]e?|son|daughter|kids?|child(?:ren)?|"
    r"baby|mom|mum|mother|dad|father|parents?|friend|brother|sister|colleague|boss|roommate|"
    r"team ?mate|grand(?:ma|pa|mother|father)"
)
# The data word must be theirs: "how did my wife sleep", "my son's steps". "My sister visited, is
# my sleep worse?" is about the person's own sleep (a false trigger in the probe of 2026-11-16).
OTHER_PERSON = re.compile(
    rf"\b(?:my|his|her|our)\s+({RELATIONS})(?:'s)?\s+(?:\w+\s+){{0,2}}?"
    r"(?:sleep|slept|steps?|walk\w*|heart|hrv|recover\w*|stress\w*|data|calories|activity|"
    r"workouts?|ran|run|tired|rest\w*)\b",
    re.IGNORECASE,
)
ABOUT_THEIR_DATA = re.compile(
    r"\b(?:sleep|slept|steps?|walk|heart|hrv|recover\w*|stress|data|calories|active|activity|"
    r"workout|run|ran|tired|rest\w*)\b",
    re.IGNORECASE,
)
ASKING = re.compile(
    r"\?|^\s*(?:how|what|when|did|does|do|is|was|were|has|have|can|could|show|tell|compare)\b",
    re.IGNORECASE,
)
FUTURE = re.compile(
    r"\b(?:will i|am i going to|i'?m going to|going to be|predict|forecast)\b|"
    r"\b(?:tonight|tomorrow|next (?:week|month|night))\b",
    re.IGNORECASE,
)
_MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
DATED = re.compile(
    rf"\b(?:({_MONTH})\.? (\d{{1,2}})(?:st|nd|rd|th)?,? (\d{{4}})|"
    rf"(\d{{1,2}}) ({_MONTH}),? (\d{{4}})|"
    r"(\d{4})-(\d{2})-(\d{2}))\b",
    re.IGNORECASE,
)
# What a Fitbit through Google Health gives this app, and what it does not.
UNTRACKED = re.compile(
    r"\b(water(?: intake)?|hydrat\w*|(?:my|body) weight|weigh myself|body fat|my bmi|"
    r"blood pressure|glucose|blood sugar|spo2|blood oxygen|oxygen saturation|menstrua\w*|"
    r"my period|ovulat\w*|running (?:pace|speed)|my pace|pace per (?:km|mile)|vo2 ?max|"
    r"app (?:usage|sessions?)|use (?:the|this|my) app|engage with (?:my|the|this) app)\b",
    re.IGNORECASE,
)

OTHER_PERSON_REPLY = (
    "I can only see your own Fitbit data, so I can't tell you about your {who}. Want a look at "
    "yours instead?"
)
BEFORE_DATA_REPLY = (
    "Your data here starts on {start:%b %-d, %Y}, so I have nothing for {day:%b %-d, %Y}. Want a "
    "look at your earliest days instead?"
)
NOT_YET_REPLY = (
    "{day:%b %-d, %Y} hasn't happened yet, so there's no data for it. I can show you what's "
    "usual for you, if that helps."
)
FUTURE_GUIDE = (
    "How to work: they ask about something still to come. Open by saying plainly, in a few "
    "words, that you can't predict it. Then give the closest useful thing their data has: what "
    "is usual for them (usual_ranges or describe over recent weeks, with the figures), and, if "
    "an earlier answer or the snapshot shows something that usually goes with it, that one "
    "thing. No hypotheses. Then call submit_findings."
)
FUTURE_TOOLS = ("usual_ranges", "describe", "compare_day", "rank_days", "weekday_split")


UNTRACKED_REPLY = (
    "Your Fitbit data here doesn't include {thing}, so I can't tell you that from it. I can look "
    "at what it does have, like your sleep, activity or recovery, if that helps."
)


def untracked_note(thing: str) -> str:
    return (
        f"Their question involves {thing}, which this app does not have: their data comes from a "
        "Fitbit through Google Health and has no water, weight, menstrual cycle, blood pressure, "
        "blood oxygen, running pace or app usage. Say so plainly in the first sentence. Then "
        "answer only the part their data covers, if there is one, or offer the closest thing it "
        "does have. Never estimate the missing thing."
    )


# Someone else as the one who slept or walked, whatever the word for them: "how did my coworker
# sleep?", "how many steps did my neighbour take?". The audit of 2026-11-18 had a coworker's
# sleep called a medical question; a list of relations can never be complete, the sentence's
# shape can. The words that only describe the person's own data are not someone else.
THEIR_ACTION = re.compile(
    r"\b(?:did|does|do|has|have|is|was|were)\s+(?:my|his|her|our)\s+([a-z][a-z-]*)\s+"
    r"(?:sleep|slept|walk\w*|run|ran|rest|recover\w*|do|did|take|took|get|got|burn\w*|train\w*)\b",
    re.IGNORECASE,
)
THEIR_DATA = re.compile(
    r"\b(?:my|his|her|our)\s+([a-z][a-z-]*)'s\s+(?:\w+\s+)?(?:sleep|steps?|heart|hrv|data|"
    r"calories|activity|workouts?|rest\w*|recover\w*|stress\w*)\b",
    re.IGNORECASE,
)
OWN_WORDS = frozenset(
    [
        "own",
        "average",
        "total",
        "daily",
        "deep",
        "light",
        "rem",
        "night",
        "nightly",
        "weekly",
        "usual",
        "resting",
        "body",
        "heart",
        "sleep",
        "step",
        "steps",
        "recovery",
        "overall",
        "fitbit",
        "watch",
        "tracker",
        "data",
        "last",
        "first",
        "best",
        "worst",
    ]
)


def other_person(text: str) -> str | None:
    """ "How did my wife sleep?": whose data they ask about, when it is not theirs."""
    found = OTHER_PERSON.search(text)
    if found and ABOUT_THEIR_DATA.search(text) and ASKING.search(text):
        return found.group(1).lower()
    for pattern in (THEIR_ACTION, THEIR_DATA):
        found = pattern.search(text)
        if found and found.group(1).lower() not in OWN_WORDS and ASKING.search(text):
            return found.group(1).lower()
    return None


def dates_named(text: str) -> list[date]:
    """Days named with a year: "January 3 2025", "3 January 2025", "2025-01-03"."""
    days = []
    for m in DATED.finditer(text):
        try:
            if m.group(1):
                days.append(date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))))
            elif m.group(4):
                days.append(date(int(m.group(6)), MONTHS[m.group(5).lower()], int(m.group(4))))
            else:
                days.append(date(int(m.group(7)), int(m.group(8)), int(m.group(9))))
        except (ValueError, KeyError):
            continue
    return days


def outside_the_data(text: str, start: date, today: date) -> str | None:
    """The fixed reply when every day the message names with a year is outside the data."""
    days = dates_named(text)
    if not days:
        return None
    if all(day < start for day in days):
        return BEFORE_DATA_REPLY.format(start=start, day=days[0])
    if all(day > today for day in days):
        return NOT_YET_REPLY.format(day=days[0])
    return None


def asks_future(text: str) -> bool:
    return bool(FUTURE.search(text) and ASKING.search(text))


def untracked(text: str) -> str | None:
    found = UNTRACKED.search(text)
    return found.group(1).lower() if found else None
