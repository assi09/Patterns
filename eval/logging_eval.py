"""Logging through the real chat API: does the draft hold what the person said?

Code generates requests whose every value is known (a food, its meal, day and time, calories when
given; a workout, its day, start time, length and distance), plus ones that must not become a draft:
a workout with no length, something that has not happened yet, and plain statements that only ask
"log it or look at the data?". Each goes to `POST /chat` in a fresh chat, as the app sends it, and
the draft the agent prepares is read from the database and compared field by field, like BFCL's
argument match. Nothing is ever sent to Google: drafts wait for a person's tap.

    PYTHONPATH=backend:eval python eval/logging_eval.py --list     # the requests, free
    PYTHONPATH=backend:eval python eval/logging_eval.py            # the run, about $1.50

How many: 90 meals, 70 workouts and 90 requests that must not become a draft (250). Per kind,
about 80-90 requests estimate an accuracy near 85% within roughly +-7 points (95% Wilson), the
whole set within about +-4; and if none of the 90 must-not requests becomes a draft, the 95% upper
bound on that failure rate is 3/90 = 3.3% (the rule of three), where 8 cases could only say 37%.

Everything is made up, so requests and drafts may be printed. Results go to `eval/results/`.
"""

import json
import random
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.agent.llm import OpenAILLM, SpendLedger
from app.config import settings
from app.db.models import HealthAction
from app.db.session import session_scope
from conversation_eval import app_for, database, sign_in
from sqlalchemy import select

STOP_AT_USD = 2.5
SEED = 503
HERE = Path(__file__).parent
OUT = HERE / "results" / f"logging_eval_{datetime.now(UTC).date()}.jsonl"
SUMMARY = HERE / "results" / f"logging_eval_{datetime.now(UTC).date()}.json"

FOODS = [  # (name in the request, word the draft's name must contain)
    ("a banana", "banana"),
    ("two boiled eggs", "egg"),
    ("a bowl of oatmeal", "oat"),
    ("a chicken caesar salad", "salad"),
    ("a slice of pepperoni pizza", "pizza"),
    ("a cappuccino", "cappuccino"),
    ("a turkey sandwich", "sandwich"),
    ("a plate of spaghetti bolognese", "spaghetti"),
    ("a greek yogurt", "yogurt"),
    ("a falafel wrap", "falafel"),
    ("an apple", "apple"),
    ("a bowl of lentil soup", "lentil"),
    ("a cheeseburger", "burger"),
    ("a glass of orange juice", "orange"),
    ("a plate of grilled salmon", "salmon"),
    ("a croissant", "croissant"),
    ("a protein bar", "bar"),
    ("a bowl of rice", "rice"),
    ("a chocolate chip cookie", "cookie"),
    ("a tuna sandwich", "tuna"),
    ("a bowl of hummus with bread", "hummus"),
    ("a mango smoothie", "smoothie"),
    ("a handful of almonds", "almond"),
    ("a shawarma wrap", "shawarma"),
    ("a bowl of cereal with milk", "cereal"),
    ("a latte", "latte"),
    ("a slice of cheesecake", "cheesecake"),
    ("a chicken burrito", "burrito"),
    ("a plate of fries", "fries"),
    ("a bowl of fruit salad", "fruit"),
]
MEALS = {
    "breakfast": "BREAKFAST",
    "lunch": "LUNCH",
    "dinner": "DINNER",
    "a snack": "SNACK",
}
MEAL_HOURS = {
    "BREAKFAST": (7, 9),
    "LUNCH": (12, 14),
    "DINNER": (18, 21),
    "SNACK": (15, 17),
}
WORKOUTS = [  # (words, types accepted)
    ("a run", ("RUNNING", "TRAIL_RUN")),
    ("a walk", ("WALKING", "POWER_WALKING")),
    ("a bike ride", ("BIKING", "OUTDOOR_BIKE", "MOUNTAIN_BIKE")),
    ("a swim", ("SWIMMING", "SWIMMING_POOL", "SWIMMING_OPEN_WATER")),
    ("a yoga session", ("YOGA", "YOGA_HATHA", "YOGA_VINYASA", "YOGA_POWER")),
    (
        "strength training",
        (
            "STRENGTH_TRAINING",
            "WEIGHTLIFTING",
            "WEIGHTS",
            "FREE_WEIGHTS",
            "FUNCTIONAL_STRENGTH_TRAINING",
        ),
    ),
    ("a hike", ("HIKING",)),
    ("a tennis match", ("TENNIS",)),
    ("a football game", ("SOCCER", "FOOTBALL")),
    ("a basketball game", ("BASKETBALL",)),
]


def clock(hour: int, minute: int) -> tuple[str, str]:
    """A time said two ways: '7am' / '19:30'."""
    suffix = "am" if hour < 12 else "pm"
    twelve = f"{(hour - 1) % 12 + 1}{f':{minute:02d}' if minute else ''}{suffix}"
    return twelve, f"{hour:02d}:{minute:02d}"


def generate(now: datetime) -> list[dict]:
    """The requests, every value known. Times are yesterday's, so none is in the future."""
    rng = random.Random(SEED)
    yesterday = (now - timedelta(days=1)).date()
    items: list[dict] = []
    for i, (said, word) in enumerate(FOODS * 3):
        meal_said, meal = list(MEALS.items())[i % 4]
        low, high = MEAL_HOURS[meal]
        hour, minute = rng.randint(low, high - 1), rng.choice((0, 15, 30, 45))
        twelve, twentyfour = clock(hour, minute)
        at = twelve if i % 2 else twentyfour
        kcal = rng.choice((None, None, 120, 250, 410, 650))
        values = f", {kcal} kcal" if kcal else ""
        form = i % 4
        text = (
            f"log {said} for {meal_said} yesterday at {at}{values}",
            f"Please add {said}{values} I had yesterday at {at} for {meal_said}",
            f"yesterday {at} {meal_said}: {said}{values}. log it",
            f"Can you record {said} for {meal_said}, yesterday at {at}{values}?",
        )[form]
        items.append(
            {
                "m": text,
                "kind": "food",
                "word": word,
                "meal": meal,
                "day": str(yesterday),
                "hour": hour,
                "minute": minute,
                "kcal": kcal,
            }
        )
    for i, (said, types) in enumerate(WORKOUTS * 7):
        hour, minute = rng.randint(6, 20), rng.choice((0, 30))
        length = rng.choice((20, 30, 45, 60, 75, 90))
        twelve, twentyfour = clock(hour, minute)
        at = twelve if i % 2 else twentyfour
        pace = {"a run": 6, "a walk": 12, "a bike ride": 3}.get(said)  # minutes per km
        km = round(length / pace) if pace and rng.random() < 0.6 else None
        distance = f", {km} km" if km else ""
        span = (
            f"{length} minutes"
            if length < 60 or i % 3
            else (
                f"{length // 60} hour{'s' if length >= 120 else ''}"
                + (f" {length % 60} minutes" if length % 60 else "")
            )
        )
        text = (
            f"log {said} yesterday at {at} for {span}{distance}",
            f"I did {said} yesterday, started at {at}, {span}{distance}. please log it",
            f"Add {said}: yesterday {at}, {span}{distance}",
        )[i % 3]
        items.append(
            {
                "m": text,
                "kind": "workout",
                "types": list(types),
                "day": str(yesterday),
                "hour": hour,
                "minute": minute,
                "minutes": length,
                "km": km,
            }
        )
    # Must not become a draft: 18 of each of five reasons, worded several ways.
    reasons = (
        (
            "no length: ask for it",
            (
                "log {w} yesterday at {at}",
                "log my {b} from yesterday morning",
                "I did {w} yesterday, please log it",
                "add {w} from this morning",
            ),
        ),
        (
            "not happened yet",
            (
                "log {w} tomorrow at {at} for 45 minutes",
                "log my dinner tonight, {f}",
                "add {f} for breakfast tomorrow",
                "log {w} next Monday at {at}, 30 minutes",
            ),
        ),
        (
            "a statement: ask what they want",
            (
                "I had {f} yesterday",
                "went for {w} yesterday",
                "ate {f} for lunch",
                "just finished {w}",
            ),
        ),
        (
            "a question, not a log",
            (
                "how many calories are in {f}?",
                "is {w} good for recovery?",
                "how much protein is in {f}?",
                "how long should {w} last?",
            ),
        ),
        (
            "a question about data",
            (
                "did {w} yesterday help my sleep?",
                "do I sleep better after {w}?",
                "how many steps did I take on the day of {w}?",
                "was my resting heart rate higher after {f}?",
            ),
        ),
    )
    for r, (why, forms) in enumerate(reasons):
        for k in range(18):
            food = FOODS[(k * 7 + r) % len(FOODS)][0]
            work = WORKOUTS[(k * 3 + r) % len(WORKOUTS)][0]
            twelve, _ = clock(rng.randint(6, 20), 0)
            text = forms[k % len(forms)].format(
                w=work, b=work.removeprefix("a ").removeprefix("an "), f=food, at=twelve
            )
            items.append({"m": text, "kind": "none", "why": why})
    return items


def local(moment: str, zone: ZoneInfo) -> datetime:
    return datetime.fromisoformat(moment).astimezone(zone)


def grade(item: dict, drafts: list[dict], zone: ZoneInfo) -> dict:
    """Field by field: True where the draft holds what was said, False where it does not."""
    if item["kind"] == "none":
        return {"no_draft": not drafts}
    drafts = [d for d in drafts if d.get("kind") == item["kind"]]
    if not drafts:
        return {"drafted": False}
    d = drafts[-1]
    out: dict = {"drafted": True}
    if item["kind"] == "food":
        when = local(d["consumedAt"], zone)
        out["name"] = item["word"] in d["foodName"].lower()
        out["meal"] = d["mealType"] == item["meal"]
        out["day"] = str(when.date()) == item["day"]
        out["time"] = (when.hour, when.minute) == (item["hour"], item["minute"])
        if item["kcal"]:
            out["kcal"] = round(d.get("energyKcal") or -1) == item["kcal"]
    else:
        start = local(d["startTime"], zone)
        out["type"] = d["exerciseType"] in item["types"]
        out["day"] = str(start.date()) == item["day"]
        out["time"] = (start.hour, start.minute) == (item["hour"], item["minute"])
        out["minutes"] = round(d["activeSeconds"] / 60) == item["minutes"]
        if item["km"]:
            out["km"] = abs((d.get("distanceKm") or -1) - item["km"]) < 0.05
    return out


def main() -> None:
    zone = ZoneInfo(settings.timezone)
    items = generate(datetime.now(zone))
    if "--list" in sys.argv:
        for item in items:
            print(f"{item['kind']:8s} {item['m']}")
        print(len(items), "requests")
        return
    engine = database()
    settings.chat_daily_cap_per_user_usd = settings.chat_daily_cap_total_usd = (
        STOP_AT_USD + 0.2
    )
    spend = SpendLedger(cap_usd=STOP_AT_USD + 0.2)
    client = app_for(engine, OpenAILLM.from_settings(settings, spend))
    headers = sign_in(client, engine)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("")
    rows = []
    for item in items:
        if spend.spent_usd >= STOP_AT_USD:
            print("Stopped at the spending limit.")
            break
        chat_id = client.post("/conversations", headers=headers).json()["id"]
        with session_scope(engine) as db:
            before = {a.id for a in db.scalars(select(HealthAction))}
        spent, started = spend.spent_usd, time.monotonic()
        response = client.post(
            "/chat",
            json={"text": item["m"], "conversationId": chat_id},
            headers=headers,
        )
        reply = (
            response.json()[-1]["text"]
            if response.status_code == 200
            else response.text
        )
        with session_scope(engine) as db:
            new = [
                a.payload
                for a in db.scalars(select(HealthAction))
                if a.id not in before
            ]
            # Drafts are kept apart per request: each is cancelled so the next is never a duplicate.
            for action in db.scalars(select(HealthAction)):
                action.status = "cancelled"
        row = {
            "m": item["m"],
            "kind": item["kind"],
            "reply": reply,
            "drafts": new,
            "fields": grade(item, new, zone),
            "status": response.status_code,
            "cost": round(spend.spent_usd - spent, 4),
            "seconds": round(time.monotonic() - started, 1),
        }
        rows.append(row)
        with OUT.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        mark = "ok " if all(row["fields"].values()) else "BAD"
        print(f"{mark} {item['kind']:8s} {json.dumps(row['fields'])} | {item['m']}")

    fields: dict[str, Counter] = {}
    for row in rows:
        for name, right in row["fields"].items():
            fields.setdefault(f"{row['kind']}.{name}", Counter())[right] += 1
    summary = {
        "requests": len(rows),
        "all_fields_right": sum(all(r["fields"].values()) for r in rows),
        "by_kind": {
            k: [
                sum(all(r["fields"].values()) for r in rows if r["kind"] == k),
                sum(r["kind"] == k for r in rows),
            ]
            for k in ("food", "workout", "none")
        },
        "fields": {k: [c[True], c[True] + c[False]] for k, c in sorted(fields.items())},
        "cost_usd": round(spend.spent_usd, 4),
        "wrong": [
            {"m": r["m"], "fields": r["fields"]}
            for r in rows
            if not all(r["fields"].values())
        ],
    }
    SUMMARY.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "wrong"}, indent=1))


if __name__ == "__main__":
    main()
