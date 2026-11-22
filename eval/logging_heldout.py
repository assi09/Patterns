"""Held-out logging test: new foods, workout types, wordings and days, fixed before any run.

`eval/logging_eval.py` is the development set (250 requests, 2026-11-18): its failures ("tomorrow"
drafted as today, "football" read as American football) were looked at and the code changed
since, so it can no longer give an unbiased number. This set shares none of its foods, workout
words or sentence forms, adds the day before yesterday, spoken durations ("half an hour", "1h15")
and a sixth reason a request must not become a draft (negated or not-yet: "I didn't...",
"don't log it yet"). It is graded by the same code, field by field, and run once.

    PYTHONPATH=backend:eval python eval/logging_heldout.py --list          # the requests, free
    PYTHONPATH=backend:eval python eval/logging_heldout.py --limit 20      # a trial, to price it
    PYTHONPATH=backend:eval python eval/logging_heldout.py --half          # the run, 180
    PYTHONPATH=backend:eval python eval/logging_heldout.py                 # all 360

How many: 120 meals, 120 workouts and 120 that must not become a draft (6 reasons, 20 each).
Per kind, 120 requests estimate an accuracy near 90% within about +-5.5 points (95% Wilson); if
none of the 120 must-not requests is drafted, the 95% upper bound on that rate is 3/120 = 2.5%.

Everything is made up, so requests and drafts may be printed. Results go to `eval/results/`.
"""

import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config import settings
from logging_eval import MEAL_HOURS, clock, run

SEED = 1122
STOP_AT_USD = 1.5
HERE = Path(__file__).parent
DAY = datetime.now(UTC).date()
OUT = HERE / "results" / f"logging_heldout_{DAY}.jsonl"
SUMMARY = HERE / "results" / f"logging_heldout_{DAY}.json"

FOODS = [  # (name in the request, word the draft's name must contain); none in the dev set
    ("a bowl of quinoa", "quinoa"),
    ("a baked potato", "potato"),
    ("a plate of pad thai", "pad thai"),
    ("a cup of black coffee", "coffee"),
    ("a pear", "pear"),
    ("a bagel with cream cheese", "bagel"),
    ("a bowl of tabbouleh", "tabbouleh"),
    ("a beef taco", "taco"),
    ("a slice of banana bread", "bread"),
    ("a bowl of chicken noodle soup", "soup"),
    ("a cup of green tea", "tea"),
    ("a plate of sushi", "sushi"),
    ("a vanilla milkshake", "milkshake"),
    ("a bowl of granola", "granola"),
    ("a grilled cheese sandwich", "cheese"),
    ("a peach", "peach"),
    ("a plate of chicken tikka masala", "tikka"),
    ("a blueberry muffin", "muffin"),
    ("a cup of cottage cheese", "cottage"),
    ("a bowl of ramen", "ramen"),
    ("a bowl of couscous", "couscous"),
    ("two pancakes", "pancake"),
    ("an avocado toast", "avocado"),
    ("a bowl of popcorn", "popcorn"),
    ("a kiwi", "kiwi"),
    ("a plate of mashed potatoes", "potato"),
    ("a glass of chocolate milk", "milk"),
    ("a veggie burger", "burger"),
    ("a bowl of strawberries", "strawberr"),
    ("a plate of beef lasagna", "lasagna"),
]
MEALS = {
    "breakfast": "BREAKFAST",
    "lunch": "LUNCH",
    "dinner": "DINNER",
    "a snack": "SNACK",
}

WORKOUTS = [  # (words, types accepted, minutes per km when a distance may be given)
    ("a soccer match", ("SOCCER",), None),
    ("a rowing machine session", ("ROWING_MACHINE", "ROWING"), None),
    ("a pilates class", ("PILATES",), None),
    ("a boxing session", ("BOXING", "KICKBOXING"), None),
    ("an elliptical session", ("ELLIPTICAL",), None),
    ("a spin class", ("SPINNING", "STATIONARY_BIKE"), None),
    ("a badminton game", ("BADMINTON",), None),
    ("a HIIT workout", ("HIIT", "INTERVAL_WORKOUT", "TABATA_WORKOUT"), None),
    ("a jog", ("RUNNING", "TRAIL_RUN"), 6),
    ("a stretching session", ("STRETCHING",), None),
    ("a squash game", ("SQUASH",), None),
    ("a treadmill walk", ("TREADMILL_WALK", "TREADMILL", "WALKING"), 11),
]

SPANS = {  # minutes: ways of saying it
    20: ("20 minutes", "20 min"),
    25: ("25 minutes", "25 mins"),
    30: ("half an hour", "30 minutes"),
    40: ("40 minutes", "40 min"),
    45: ("45 minutes", "three quarters of an hour"),
    60: ("an hour", "1 hour"),
    75: ("1h15", "an hour and 15 minutes"),
    90: ("an hour and a half", "1.5 hours"),
}
DAYS = (("yesterday", 1), ("the day before yesterday", 2), ("two days ago", 2))


def generate(now: datetime) -> list[dict]:
    """The requests, every value known; every meal and workout is at least a day old."""
    rng = random.Random(SEED)
    today = now.date()
    items: list[dict] = []
    for i, (said, word) in enumerate(FOODS * 4):
        meal_said, meal = list(MEALS.items())[i % 4]
        day_said, back = DAYS[(i // 4) % 3]
        low, high = MEAL_HOURS[meal]
        hour, minute = rng.randint(low, high - 1), rng.choice((0, 10, 20, 30, 40, 50))
        twelve, twentyfour = clock(hour, minute)
        at = twentyfour if i % 3 else twelve
        kcal = rng.choice((None, None, 90, 300, 520, 780))
        values = f" ({kcal} kcal)" if kcal else ""
        text = (
            f"add {said}{values} as {meal_said} {day_said} at {at}",
            f"{day_said.capitalize()} I ate {said} at {at} for {meal_said}{values}, can you log that?",
            f"track {said} for {meal_said}, {day_said} {at}{values}",
            f"put {said} in my log: {meal_said}, {day_said} at {at}{values}",
        )[(i // 3) % 4]
        items.append(
            {
                "m": text,
                "kind": "food",
                "word": word,
                "meal": meal,
                "day": str(today - timedelta(days=back)),
                "hour": hour,
                "minute": minute,
                "kcal": kcal,
            }
        )
    for i, (said, types, pace) in enumerate(WORKOUTS * 10):
        day_said, back = DAYS[(i // 5) % 3]
        hour, minute = rng.randint(6, 20), rng.choice((0, 15, 30, 45))
        length = rng.choice(sorted(SPANS))
        span = SPANS[length][i % 2]
        twelve, twentyfour = clock(hour, minute)
        at = twelve if i % 2 else twentyfour
        km = round(length / pace) if pace and rng.random() < 0.6 else None
        distance = f", {km} km" if km else ""
        text = (
            f"log {said} from {day_said}, started {at}, lasted {span}{distance}",
            f"{day_said.capitalize()} I did {said} at {at} for {span}{distance}, add it please",
            f"record {said}: {day_said}, {at}, {span}{distance}",
            f"can you add {said} I did {day_said} at {at}? it took {span}{distance}",
        )[(i // 3) % 4]
        items.append(
            {
                "m": text,
                "kind": "workout",
                "types": list(types),
                "day": str(today - timedelta(days=back)),
                "hour": hour,
                "minute": minute,
                "minutes": length,
                "km": km,
            }
        )
    # Must not become a draft: 20 of each of six reasons, worded four ways each.
    reasons = (
        (
            "no length: ask for it",
            (
                "add {w} I did yesterday at {at}",
                "log {w} from two days ago",
                "record my {b} from this morning",
                "put in {w} I did yesterday evening",
            ),
        ),
        (
            "not happened yet",
            (
                "log {w} tomorrow at {at}, 40 minutes",
                "add {f} as lunch tomorrow",
                "log {w} next Friday at {at} for an hour",
                "record {f} for dinner the day after tomorrow",
            ),
        ),
        (
            "a statement: ask what they want",
            (
                "yesterday I had {f}",
                "did {w} this morning, felt great",
                "{f} for breakfast today",
                "finally did {w} again",
            ),
        ),
        (
            "a question, not a log",
            (
                "what's a good time of day for {w}?",
                "how many calories does {w} burn?",
                "what's in {f}?",
                "how long should I rest after {w}?",
            ),
        ),
        (
            "a question about data",
            (
                "how did I sleep after {w} yesterday?",
                "what was my step count the day I did {w}?",
                "is my heart rate higher on days with {w}?",
                "did {f} for dinner change my sleep?",
            ),
        ),
        (
            "negated or not yet: nothing to log",
            (
                "I didn't do {w} yesterday after all",
                "don't log {w} yet, I'll tell you the time later",
                "I'm thinking about {w} tomorrow",
                "if I eat {f} later I'll log it then",
            ),
        ),
    )
    seen: set[str] = set()
    for r, (why, forms) in enumerate(reasons):
        for k in range(20):
            while True:  # every text once: draw again on a repeat
                food = rng.choice(FOODS)[0]
                work = rng.choice(WORKOUTS)[0]
                twelve, _ = clock(rng.randint(6, 20), 0)
                text = forms[k % len(forms)].format(
                    w=work,
                    b=work.removeprefix("a ").removeprefix("an "),
                    f=food,
                    at=twelve,
                )
                if text not in seen:
                    break
            seen.add(text)
            items.append({"m": text, "kind": "none", "why": why})
    return items


def main() -> None:
    items = generate(datetime.now(ZoneInfo(settings.timezone)))
    if "--list" in sys.argv:
        for item in items:
            print(f"{item['kind']:8s} {item['m']}")
        print(len(items), "requests")
        return
    limit = (
        int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    )
    if limit:
        # A trial, only to price the run: the same number of each kind, written apart. The code
        # is not changed after it, so the run stays held out.
        rng = random.Random(SEED)
        kinds = ("food", "workout", "none")
        items = [
            x
            for k in kinds
            for x in rng.sample([i for i in items if i["kind"] == k], limit // 3)
        ]
        out = OUT.with_name(OUT.stem + "_trial.jsonl")
        summary = SUMMARY.with_name(SUMMARY.stem + "_trial.json")
        run(items, out, summary, 0.25)
        return
    if "--half" in sys.argv:
        items = half(items)
    run(items, OUT, SUMMARY, STOP_AT_USD)


def half(items: list[dict]) -> list[dict]:
    """180 of the 360, every stratum halved: 15 per meal, 5 per workout type, 10 per reason."""
    rng = random.Random(SEED + 1)
    groups: dict[tuple, list[dict]] = {}
    for item in items:
        key = item.get("meal") or (item.get("types") or [item.get("why")])[0]
        groups.setdefault((item["kind"], key), []).append(item)
    return [x for group in groups.values() for x in rng.sample(group, len(group) // 2)]


if __name__ == "__main__":
    main()
