"""The kinds of question the router tells apart, for the strategy each one gets (strategy.py).

Kept apart from strategy.py, which imports the agent and its tools, so the router can import it.
"""

QUESTION_TYPES = ("day", "lookup", "change", "why", "pattern", "coaching", "world")
DEFAULT_TYPE = "why"  # the most thorough, when the type is unclear
QUESTION_CRITERIA = {
    "day": "about one day: today, last night, this morning or yesterday",
    "lookup": "a value, a range, an average, what is usual, or the best or worst days",
    "change": "whether something changed or is trending, and since when",
    "why": "what explains a change or a pattern",
    "pattern": "how metrics relate, weekdays against weekends, or a check-in tag's effect",
    "coaching": "how to improve: sleep better, recover faster, train smarter, tips or advice",
    "world": "general knowledge, not their own data: what is in a food or dish, how many calories "
    "it has, or what a tracker metric means",
}
QUESTION_INSTRUCTIONS = (
    "What kind of answer does the current question need? Earlier questions only show what it may "
    "refer to."
)
