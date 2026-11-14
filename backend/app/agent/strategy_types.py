"""The kinds of question the router tells apart, for the strategy each one gets (strategy.py).

Kept apart from strategy.py, which imports the agent and its tools, so the router can import it.
"""

import re

QUESTION_TYPES = ("day", "lookup", "change", "why", "pattern", "coaching", "world", "chat")
DEFAULT_TYPE = "why"  # the most thorough, when the type is unclear
QUESTION_CRITERIA = {
    "day": "about one day (today, last night, this morning or yesterday), even a single value on "
    "that day",
    "lookup": "a value over a period: a range, an average, what is usual, or the best or worst "
    "days",
    "change": "whether something changed or is trending, and since when",
    "why": "what explains a change or a pattern",
    "pattern": "how metrics relate, weekdays against weekends, which day of the week, or a "
    "check-in tag's effect",
    "coaching": "how to improve: sleep better, recover faster, eat better, train smarter, tips or "
    "advice, or anything where the right answer depends on the person (how much they need, what "
    "they should do)",
    "world": "general knowledge, not their own data: what is in a food or dish, how many calories "
    "it has, what a tracker metric means, how to do an exercise, or how much of something adults "
    "generally need: answers that are the same for everyone. Not what they themselves should "
    "do or need, which is coaching",
    # Without it "hi", "thanks" or "I'm a student, that's why I slept little" defaulted to why and
    # got a statistical answer to something nobody asked.
    "chat": "not a request for their data or for advice: a greeting, thanks, a reaction to an "
    "answer (agreeing, disagreeing, saying it is wrong), small talk, what the app can do, or "
    "telling you something about themselves or their life, including why something happened, "
    "without asking anything",
}
QUESTION_INSTRUCTIONS = (
    "What kind of answer does the current question need? Earlier questions only show what it may "
    "refer to."
)


# Small talk, recognised by code: the keyword router's rule when Jev is down, and the check that
# keeps the chat reply to messages that ask nothing of the data.
_TALK = r"(?:hi|hello|hey|hiya|yo|good (?:morning|afternoon|evening|night)|thanks?|thank you|"
_TALK += r"thx|ty|cheers|ok(?:ay)?|k|cool|great|nice|got it|sounds good|perfect|awesome|bye|"
_TALK += r"see you|lol|haha|wow|no|nope|alright)"
SMALL_TALK = re.compile(rf"^\s*{_TALK}\b[\s\W]*(?:\w+[\s\W]*){{0,4}}$", re.IGNORECASE)
REACTION = re.compile(
    r"^\s*(?:(?:that|this|it)(?:'s| is| was| seems| looks)? (?:wrong|not right|incorrect|off|"
    r"weird|strange|useless|not helpful|helpful|useful|right|correct|interesting)|"
    r"you(?:'re| are) (?:wrong|useless|not helpful|helpful|great|right)|"
    r"(?:(?:that|this|it) )?makes? (?:no )?sense|"
    r"not what i asked|(?:that|this) (?:doesn't|does not|didn't) (?:help|answer|make sense))\b",
    re.IGNORECASE,
)
CAPABILITIES = re.compile(
    r"\b(?:what (?:can|do) you do|what are you|who are you|what is this app|how do(?:es)? "
    r"(?:you|this app|patterns) work|what can i ask)\b",
    re.IGNORECASE,
)
_ASKS = re.compile(
    r"^\s*(?:and |but |so |also |please |pls )?(?:how|what|what's|whats|why|when|where|which|who|"
    r"did|do|does|is|are|was|were|can|could|should|would|will|have|has|show|tell|give|compare|"
    r"log|remind|set|add|track|help|find|check|look)\b",
    re.IGNORECASE,
)
_ABOUT_THEM = re.compile(r"\b(?:i|i'm|im|i've|ive|i'd|my|me|we|we're|our)\b", re.IGNORECASE)
_WANTS = re.compile(
    r"\b(?:can you|could you|please|pls|i want to know|tell me|show me|i(?:'d| would) like|"
    r"advice|tips?|how (?:do|can|should) i|log|remind)\b",
    re.IGNORECASE,
)


def is_statement(text: str) -> bool:
    """Telling something about themselves, asking nothing: "I'm a student, I had projects"."""
    return (
        "?" not in text
        and not _ASKS.match(text)
        and not _WANTS.search(text)
        and bool(_ABOUT_THEM.search(text))
    )


def certain_talk(text: str) -> bool:
    """Small talk code is sure of, whatever the router says: "hi", "thanks", "that's wrong", "what
    can you do?". A greeting with a question ("Hello! How did I sleep?") is the question."""
    if CAPABILITIES.search(text):
        return True
    return "?" not in text and bool(SMALL_TALK.match(text) or REACTION.match(text))


def is_small_talk(text: str) -> bool:
    """A greeting, thanks or a reaction, a question about the app, or a statement about them."""
    text = text.strip()
    if not text:
        return False
    if certain_talk(text):
        return True
    return is_statement(text)


# "Yes" to the agent's own offer ("Want some ideas that fit around it?") takes the offer up.
AFFIRM = re.compile(
    r"^\s*(?:yes|yeah|yep|yup|sure|ok(?:ay)?|please|go ahead|do it|sounds good|why not|"
    r"absolutely|definitely)\b[\s\W]*(?:please|do|thanks?|go ahead|sure)?[\s\W]*$",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")


def offer_in(answer: str) -> str | None:
    """The question the answer ended on, if it was an offer: "Want some ideas …?"."""
    sentences = [
        m.group().strip()
        for m in _SENTENCE.finditer(answer)
        if m.group().strip() and "tap keep" not in m.group().lower()  # the memory card's note
    ]
    for sentence in reversed(sentences[-2:]):
        if sentence.endswith("?") or _OFFERS.match(sentence):
            return sentence
    return None


_OFFER_OPENING = re.compile(
    r"^\s*(?:if you(?:'d)? (?:want|like),?\s*)?(?:(?:do you )?want (?:me )?to|would you like "
    r"(?:me )?to|shall i|should i|can i|i can(?: also)?)\s+",
    re.IGNORECASE,
)
_WANTS_SOME = re.compile(r"^\s*(?:do you )?want (?=some\b|a\b|an\b|a few\b)", re.IGNORECASE)
# Where a second option starts: ", or just keep an eye", ", or help you test it", ", or a look at".
# A list keeps its "or": "bedtime, sleep efficiency, or time asleep".
_SECOND_OPTION = re.compile(
    r",?\s+or\s+(?=(?:just|maybe|perhaps|help|look|check|see|set|compare|keep|get|think|try|"
    r"give|show|start|do|go|a|an|some|would|should)\b)",
    re.IGNORECASE,
)
_SECOND_PERSON = (
    (re.compile(r"\byour\b", re.I), "my"),
    (re.compile(r"\byours\b", re.I), "mine"),
    (re.compile(r"\byou(?:'re| are)\b", re.I), "I'm"),
    (re.compile(r"\byou\b", re.I), "me"),
)


def as_request(offer: str) -> str:
    """The person's "yes" to "Want me to look at how this week compares with your usual sleep?",
    said as their request: "Look at how this week compares with my usual sleep." Only the first
    option of an "A, or B?" offer: a plain yes takes the first."""
    text = _WANTS_SOME.sub("Give me ", offer.strip().rstrip("?."))
    text = _OFFER_OPENING.sub("", text)
    # "A, or B": the first. A plain "or" may join two nouns ("activity or recovery"): kept.
    text = _SECOND_OPTION.split(text, maxsplit=1)[0]
    for pattern, word in _SECOND_PERSON:
        text = pattern.sub(word, text)
    return text[:1].upper() + text[1:] + "."


# Something they just did or ate, which could be logged: "just had a chicken salad", "did legs".
# "Training for a half marathon" or "I work night shifts" is about their life, not an entry.
LOGGABLE = re.compile(
    r"\b(?:just|had|ate|eaten|drank|drunk|did|done|went (?:for|to)|ran|walked|swam|cycled|biked|"
    r"rode|lifted|finished|played|completed|for (?:breakfast|lunch|dinner))\b",
    re.IGNORECASE,
)
# An offer said without a question mark: "If you want, I can look at your week."
_OFFERS = re.compile(
    r"^\s*(?:if you(?:'d)? (?:want|like),?\s*|want\b|would you like\b|shall i\b|"
    r"i can (?:also )?(?:look|check|compare|help|show|set|give))",
    re.IGNORECASE,
)
