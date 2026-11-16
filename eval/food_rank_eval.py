"""How well a food lookup finds the food a person means: USDA's own order against ranking its
matches by meaning (embeddings), on `food_set.json`. A match is right when its calories per 100 g
fall in the range the food really has.

    PYTHONPATH=backend python eval/food_rank_eval.py [set]   # USDA (free), the model (~$0.01)
"""

import json
import sys
from pathlib import Path

from app.agent.llm import OpenAILLM, SpendLedger
from app.config import settings
from app.outside import SHORTLIST, FoodData, by_meaning, model_choice, restaurant_item

NAME = sys.argv[1] if len(sys.argv) > 1 else "food_set"
SET = json.loads((Path(__file__).parent / f"{NAME}.json").read_text())
SUMMARY = Path(f"eval/results/food_rank_eval_{NAME}.json")


def right(entry: dict | None, kcal: list[float]) -> bool:
    value = (entry or {}).get("per_100g", {}).get("energy_kcal")
    return value is not None and kcal[0] <= value <= kcal[1]


def first(found: list[dict], query: str) -> dict | None:
    ordered = sorted(found, key=lambda entry: restaurant_item(entry["food"], query))
    return ordered[0] if ordered else None


def main() -> None:
    llm = OpenAILLM.from_settings(settings, SpendLedger(cap_usd=0.05))
    data = FoodData.from_settings(settings)
    embed = lambda texts: llm.embed(texts).vectors  # noqa: E731
    choose = model_choice(llm)
    rows = []
    for item in SET["foods"]:
        found = data.candidates(item["q"])
        usda = first(found, item["q"])
        ranked = by_meaning(item["q"], found, embed) if len(found) > 1 else found
        meaning = first(ranked, item["q"])
        picked = choose(item["q"], [e["food"] for e in ranked[:SHORTLIST]]) if ranked else None
        chosen = ranked[picked] if picked is not None and picked < len(ranked) else meaning
        rows.append(
            {
                "q": item["q"],
                "matches": len(found),
                "usda": usda and usda["food"],
                "usda_right": right(usda, item["kcal"]),
                "meaning": meaning and meaning["food"],
                "meaning_right": right(meaning, item["kcal"]),
                "chosen": chosen and chosen["food"],
                "chosen_right": right(chosen, item["kcal"]),
                "any_right": any(right(f, item["kcal"]) for f in found),
            }
        )
        mark = lambda ok: "Y" if ok else "-"  # noqa: E731
        print(
            f"{mark(rows[-1]['usda_right'])} {mark(rows[-1]['meaning_right'])} "
            f"{mark(rows[-1]['chosen_right'])} {item['q']:26s} "
            f"chosen: {(rows[-1]['chosen'] or '-')[:55]}"
        )
    n = len(rows)
    summary = {
        "foods": n,
        "usda_order_right": sum(r["usda_right"] for r in rows),
        "by_meaning_right": sum(r["meaning_right"] for r in rows),
        "meaning_then_model_right": sum(r["chosen_right"] for r in rows),
        "right_food_among_matches": sum(r["any_right"] for r in rows),
        "rows": rows,
    }
    SUMMARY.write_text(json.dumps(summary, indent=1) + "\n")
    print(
        f"\nUSDA's order {summary['usda_order_right']}/{n}, by meaning "
        f"{summary['by_meaning_right']}/{n}, by meaning then the model "
        f"{summary['meaning_then_model_right']}/{n}; the right food was among the matches for "
        f"{summary['right_food_among_matches']}/{n}"
    )


if __name__ == "__main__":
    main()
