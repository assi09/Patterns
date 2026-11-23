"""Writes a fresh, independently worded test bank for the November 23 reader fixes, then freezes it.

The wordings of the earlier small checks were written by the person who wrote the fixes. Here
the large model writes each user message from a description of the case, and the expected
reading comes from the case, never from the model's text. Negative controls (messages a fix
must not catch) are in it too. Paid: one call per family. Run from the repository root.

    PYTHONPATH=backend .venv/bin/python eval/fresh_bank.py
"""

import hashlib
import json
import random
from pathlib import Path

OUT = Path("data/eval/fresh_bank_2026-11-23")
SEED = 20261123
EARLIER = (  # the wordings of the earlier small checks: none may be reused
    "What day did I just mention?", "Which day did I say the ride was?",
    "Where did that advice come from?", "Where's that information from?",
    "On which days is there nothing recorded?", "on how many nights was my sleep tracked?",
    "And the protein for that same breakfast?", "Drop the breakfast filter",
    "Use four dates beginning two dates after that last day.",
)  # fmt: skip

FAMILIES = {
    "recall_unsaved": (
        25,
        (
            "Pairs of chat messages from a person to a health-data app. 'before': they tell the app "
            "one everyday fact or plan (a workout, a bedtime, a trip, a meal, a race) and in the same "
            "message ask that it not be saved or kept only for this conversation, each time with "
            "different words. 'question': a later message asking what they just said about it. "
            'Return {"items": [{"before": "...", "question": "..."}]}.'
        ),
    ),
    "recall_plain": (
        15,
        (
            "Pairs of chat messages to a health-data app. 'before': they mention one everyday fact "
            "or plan, with nothing about saving. 'question': a later message asking what they said. "
            'Return {"items": [{"before": "...", "question": "..."}]}.'
        ),
    ),
    "recall_kept": (
        10,
        (
            "Messages to a health-data app, with no earlier chat, asking what it has saved or "
            "remembers about them, or what is waiting for their approval. "
            'Return {"items": [{"question": "..."}]}.'
        ),
    ),
    "source_guidance": (
        15,
        (
            "The app just explained how to do a plank, citing a public exercise database. Messages "
            "asking where that advice or information came from, or what it is based on. "
            'Return {"items": [{"question": "..."}]}.'
        ),
    ),
    "source_data": (
        15,
        (
            "The app just said the person's total steps for one week, computed from their tracker. "
            "Messages asking where that number came from or what data it is based on. "
            'Return {"items": [{"question": "..."}]}.'
        ),
    ),
    "source_negative": (
        15,
        (
            "The app just explained how to do a plank. Follow-up messages that ask something else "
            "about planks (how long to hold, how often, an easier version, common mistakes), never "
            'where the advice came from. Return {"items": [{"question": "..."}]}.'
        ),
    ),
    "coverage": (
        30,
        (
            "Messages asking on how many days or nights ONE named measure was recorded, tracked, "
            "logged or captured between {start} and {end} (keep those two placeholders exactly). "
            "Use 'sleep' in 10, 'steps' in 10 and 'resting heart rate' in 10. "
            'Return {"items": [{"question": "...", "measure": "sleep|steps|resting heart rate"}]}.'
        ),
    ),
    "coverage_negative": (
        10,
        (
            "Messages asking how complete ALL of their data or every measure was between {start} "
            "and {end} (keep those placeholders), naming no single measure. "
            'Return {"items": [{"question": "..."}]}.'
        ),
    ),
    "food": (
        30,
        (
            "The app just said the energy the person logged for breakfast on one day. Follow-ups, "
            "10 of each kind: 'keep_meal': a nutrient (protein, carbohydrate or fat) for that same "
            "breakfast; 'all_meals': a nutrient for every meal that whole day; 'burned': the "
            "calories their tracker says they burned that day. "
            'Return {"items": [{"question": "...", "kind": "keep_meal|all_meals|burned", '
            '"nutrient": "protein|carbohydrate|fat|none"}]}.'
        ),
    ),
}
EDGE = {
    "its_first_day": "the earlier period's first day",
    "its_last_day": "its last day",
}


def period_specs() -> list[dict]:
    rng = random.Random(SEED)
    specs = []
    for _ in range(30):
        specs.append(
            {
                "role": rng.choice(["begins", "ends"]),
                "counted_from": rng.choice(list(EDGE)),
                "days_after": rng.choice([-2, -1, 0, 1, 2]),
                "length": rng.choice([2, 3, 4]),
            }
        )
    return specs


def describe(spec: dict) -> str:
    offset = spec["days_after"]
    shift = (
        "that day itself"
        if offset == 0
        else f"{abs(offset)} day(s) {'after' if offset > 0 else 'before'} it"
    )
    return (
        f"a block of {spec['length']} days that {spec['role'][:-1]}s on {shift}, where 'it' is "
        f"{EDGE[spec['counted_from']]}"
    )


def main() -> None:
    import openai
    from app.config import settings

    key = settings.openai_api_key
    client = openai.OpenAI(api_key=getattr(key, "get_secret_value", lambda: key)())
    rules = (
        "Write natural, varied messages as different real people would type them: different "
        "lengths, tones and phrasings, some casual, a few with small typos. Do not reuse these "
        f"wordings: {list(EARLIER)}. Reply with JSON only."
    )
    bank, cost = {}, 0.0
    for family, (count, task) in FAMILIES.items():
        reply = client.chat.completions.create(
            model=settings.openai_large_model,
            messages=[
                {"role": "system", "content": rules},
                {"role": "user", "content": f"{count} items. {task}"},
            ],
            response_format={"type": "json_object"},
        )
        bank[family] = json.loads(reply.choices[0].message.content)["items"][:count]
        cost += reply.usage.prompt_tokens * 5e-6 + reply.usage.completion_tokens * 30e-6
    specs = period_specs()
    listing = "\n".join(f"{i}: {describe(s)}" for i, s in enumerate(specs))
    reply = client.chat.completions.create(
        model=settings.openai_large_model,
        messages=[
            {"role": "system", "content": rules},
            {
                "role": "user",
                "content": "The app just gave the person's average steps for a five-day period. "
                "For each numbered spec, one follow-up asking for the same average over that block "
                "of days, said in words (no dates). Return "
                '{"items": [{"spec": <number>, "question": "..."}]}.\n' + listing,
            },
        ],
        response_format={"type": "json_object"},
    )
    said = {
        i["spec"]: i["question"]
        for i in json.loads(reply.choices[0].message.content)["items"]
    }
    bank["periods"] = [
        s | {"question": said[i]} for i, s in enumerate(specs) if i in said
    ]
    cost += reply.usage.prompt_tokens * 5e-6 + reply.usage.completion_tokens * 30e-6
    OUT.mkdir(parents=True, exist_ok=True)
    body = json.dumps(bank, sort_keys=True, indent=1)
    (OUT / "bank.json").write_text(body)
    print({family: len(items) for family, items in bank.items()})
    print(f"about ${cost:.4f}; sha256 {hashlib.sha256(body.encode()).hexdigest()}")


if __name__ == "__main__":
    main()
