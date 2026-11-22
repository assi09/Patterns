"""A second held-out logging set, written after #211 fixed the first one's misses.

`eval/logging_heldout.py` was run once (2026-11-22), its misses were traced and fixed, so it is
now development too. This set was written before any of it ran and shares none of the earlier
sets' foods, workout types or sentence forms (a few food words recur: "apple", "tuna", "falafel").
It keeps the hard parts the fixes were for, said in new ways: days still to come ("this Sunday",
"in two days"), workouts with no length, spoken and run-together durations ("an hour and ten
minutes", "2h", "a quarter of an hour"), and named types. Two durations were seen while writing it
to be beyond the parser ("an hour and three quarters", "thirty-five minutes") and kept, since
people say them. Graded by the same code as the others, field by field, and run once.

    PYTHONPATH=backend:eval python eval/logging_fresh.py --list     # the requests, free
    PYTHONPATH=backend:eval python eval/logging_fresh.py            # the run, about $0.95

How many: 60 meals, 60 workouts and 60 that must not become a draft (6 reasons, 10 each), as the
user chose for the first held-out run: each kind within about +-7.5 points; if no must-not request
is drafted, the 95% upper bound on that rate is 3/60 = 5%. Must-not replies are also checked for
the generic "couldn't pin that down", which the first run counted as a pass.

Everything is made up, so requests and drafts may be printed. Results go to `eval/results/`.
"""

import json
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.agent.agent import NO_ANSWER
from app.config import settings
from logging_eval import MEAL_HOURS, clock, run

SEED = 2211
STOP_AT_USD = 1.3
HERE = Path(__file__).parent
DAY = datetime.now(UTC).date()
OUT = HERE / "results" / f"logging_fresh_{DAY}.jsonl"
SUMMARY = HERE / "results" / f"logging_fresh_{DAY}.json"

FOODS = [  # (said, word the draft's name must contain); in neither earlier set
    ("a bowl of miso soup", "miso"),
    ("a slice of watermelon", "watermelon"),
    ("a chicken shawarma plate", "chicken"),
    ("a bowl of chili", "chili"),
    ("a glass of apple juice", "apple"),
    ("a tuna salad", "tuna"),
    ("a bowl of porridge", "porridge"),
    ("a waffle", "waffle"),
    ("a plate of fried rice", "rice"),
    ("a cup of hot chocolate", "chocolate"),
    ("a plum", "plum"),
    ("a ham and cheese omelette", "omelet"),
    ("a bowl of minestrone", "minestrone"),
    ("a slice of apple pie", "pie"),
    ("a plate of hummus and falafel", "falafel"),  # "falafel" is in dev only as a wrap
]
MEALS = {
    "breakfast": "BREAKFAST",
    "lunch": "LUNCH",
    "dinner": "DINNER",
    "a snack": "SNACK",
}

WORKOUTS = [  # (said, types accepted, minutes per km when a distance may be given)
    ("a tennis match", ("TENNIS",), None),
    ("a power yoga class", ("YOGA_POWER",), None),
    ("a kickboxing class", ("KICKBOXING",), None),
    ("a circuit training session", ("CIRCUIT_TRAINING",), None),
    ("a trail run", ("TRAIL_RUN",), 7),
    ("a volleyball game", ("VOLLEYBALL",), None),
    ("a stair climber session", ("STAIRCLIMBER",), None),
    ("a mountain bike ride", ("MOUNTAIN_BIKE",), 4),
    ("a table tennis game", ("TABLE_TENNIS",), None),
    ("a zumba class", ("ZUMBA",), None),
    ("a weightlifting session", ("WEIGHTLIFTING", "WEIGHTS", "FREE_WEIGHTS"), None),
    ("an open water swim", ("SWIMMING_OPEN_WATER",), None),
]

SPANS = {  # minutes: new ways of saying it
    15: ("a quarter of an hour", "15 mins"),
    35: ("35 min", "thirty-five minutes"),
    50: ("50 minutes", "50 mins"),
    60: ("one hour", "60 min"),
    70: ("an hour and ten minutes", "1h10"),
    105: ("an hour and three quarters", "1 hour 45 minutes"),
    120: ("2h", "two hours"),
}
DAYS = (("yesterday", 1), ("2 days ago", 2), ("three days ago", 3))


def generate(now: datetime) -> list[dict]:
    """The requests, every value known; every meal and workout is at least a day old."""
    rng = random.Random(SEED)
    today = now.date()
    items: list[dict] = []
    for i, (said, word) in enumerate(FOODS * 4):
        meal_said, meal = list(MEALS.items())[i % 4]
        day_said, back = DAYS[(i // 4) % 3]
        low, high = MEAL_HOURS[meal]
        hour, minute = rng.randint(low, high - 1), rng.choice((5, 15, 25, 35, 45, 55))
        twelve, twentyfour = clock(hour, minute)
        at = twelve if i % 3 else twentyfour
        kcal = rng.choice((None, None, 180, 340, 560, 720))
        values = f" — {kcal} calories" if kcal else ""
        text = (
            f"please log {meal_said} {day_said}: {said} at {at}{values}",
            f"for {meal_said} {day_said} I had {said} around {at}{values}, log it",
            f"note down {said}, eaten {day_said} at {at} as {meal_said}{values}",
            f"I want to log {said} I ate {day_said} at {at} ({meal_said}){values}",
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
    for i, (said, types, pace) in enumerate(WORKOUTS * 5):
        day_said, back = DAYS[(i // 4) % 3]
        hour, minute = rng.randint(6, 20), rng.choice((0, 10, 20, 40, 50))
        length = rng.choice(sorted(SPANS))
        span = SPANS[length][i % 2]
        twelve, twentyfour = clock(hour, minute)
        at = twentyfour if i % 2 else twelve
        km = round(length / pace) if pace and rng.random() < 0.6 else None
        distance = f" and covered {km} km" if km else ""
        text = (
            f"please log {said} {day_said} at {at}, it lasted {span}{distance}",
            f"{said.capitalize()} {day_said} from {at}, {span}{distance}, add it",
            f"note down {said}: started {at} {day_said}, went for {span}{distance}",
            f"I want to log {said} from {day_said}, {at}, {span}{distance}",
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
    reasons = (
        (
            "no length: ask for it",
            (
                "please log {w} from yesterday at {at}",
                "note down {w} I did three days ago",
                "I want to log {w} from this afternoon",
                "can you put {w} from 2 days ago in my log",
            ),
        ),
        (
            "not happened yet",
            (
                "please log {w} this coming Sunday at {at}, one hour",
                "note down {f} for lunch in two days",
                "I want to log {w} on the 30th, 50 minutes",
                "log {f} as breakfast tomorrow morning",
            ),
        ),
        (
            "a statement: ask what they want",
            (
                "had {f} earlier",
                "{w} done today, legs are tired",
                "two days ago I had {f}",
                "back from {w}",
            ),
        ),
        (
            "a question, not a log",
            (
                "is {w} good cardio?",
                "how much sugar is in {f}?",
                "what muscles does {w} work?",
                "is {f} high in protein?",
            ),
        ),
        (
            "a question about data",
            (
                "was my sleep worse after {w}?",
                "how many active minutes did {w} give me last week?",
                "does my heart rate stay up after {w}?",
                "did I sleep later on days I had {f}?",
            ),
        ),
        (
            "negated or not yet: nothing to log",
            (
                "I skipped {w} yesterday",
                "no need to log {f}, I didn't finish it",
                "planning {w} later this week",
                "wait, don't add {w} yet",
            ),
        ),
    )
    seen: set[str] = set()
    for why, forms in reasons:
        for k in range(10):
            while True:  # every text once: draw again on a repeat
                food = rng.choice(FOODS)[0]
                work = rng.choice(WORKOUTS)[0]
                twelve, _ = clock(rng.randint(6, 20), 0)
                text = forms[k % len(forms)].format(w=work, f=food, at=twelve)
                if text not in seen:
                    break
            seen.add(text)
            items.append({"m": text, "kind": "none", "why": why})
    return items


def generic(rows_path: Path) -> dict:
    """How many must-not replies were the generic fallback, per reason: a pass that says nothing."""
    by_text = {
        i["m"]: i.get("why")
        for i in generate(datetime.now(ZoneInfo(settings.timezone)))
    }
    counts: dict[str, list[int]] = {}
    for line in rows_path.read_text().splitlines():
        row = json.loads(line)
        if row["kind"] != "none":
            continue
        tally = counts.setdefault(by_text.get(row["m"], "?"), [0, 0])
        tally[0] += row["reply"].strip() == NO_ANSWER
        tally[1] += 1
    return counts


def main() -> None:
    items = generate(datetime.now(ZoneInfo(settings.timezone)))
    if "--list" in sys.argv:
        for item in items:
            print(f"{item['kind']:8s} {item['m']}")
        print(len(items), "requests")
        return
    summary = run(items, OUT, SUMMARY, STOP_AT_USD)
    summary["generic_replies"] = generic(OUT)
    SUMMARY.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
    print("generic replies (must-not):", summary["generic_replies"])


if __name__ == "__main__":
    main()
