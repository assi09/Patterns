"""What is left of reading facts from the words with patterns.

Checks here once read dates, shifts, lengths, months, statistics and meals from a request's words
and sent back readings that disagreed. Patterns cannot read meaning: they sent back right readings
("the next two dates" when the copied clause stopped short of them, "February of 2027") and let
wrong ones through ("same week", "calories burned"), one wording at a time (v5, v6 and v7 audits).
Whether a resolved request means what the message asks is now read back by a small model
(readback.py). Only `from_today` stays, for the one rule code is sure of: with nothing computed
earlier, a period counted "from the earlier request" in a question about recent days can only mean
today (requests.anchored_by_code).
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Conflict:
    code: str  # which check, for the private trace
    retry: str  # told to the reader: the fact its reading contradicts
    ask: str  # asked of the person when the reader keeps it


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


def from_today(text: str) -> bool:
    return bool(FROM_TODAY.search(text)) and not REFERS_TO_EARLIER.search(text)
