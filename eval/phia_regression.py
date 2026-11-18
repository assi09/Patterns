"""Did a change to the agent move its PHIA results? Re-asks Patterns the first N questions of a
batch already run, with today's code, and compares each grade with the stored one. Nothing in the
batch's own results file changes.

    PYTHONPATH=backend:eval python eval/phia_regression.py --batch A1 --first 50   # about $0.20
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from app.agent.ask import default_guard, default_router
from app.agent.llm import OpenAILLM, SpendLedger
from app.config import settings
from phia_bench import ANSWERS, ITEMS, _frame_for, ask_one, broken, latest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", default="A1")
    parser.add_argument("--first", type=int, default=50)
    args = parser.parse_args()
    mode, number = args.batch[0], int(args.batch[1:])
    stored = latest(
        (ANSWERS / f"phia_bench_{args.batch}.jsonl").read_text().splitlines()
    )
    items = [
        i
        for i in json.loads(ITEMS.read_text())["items"]
        if i["mode"] == mode
        and i["batch"] == number
        and i["id"] in stored
        and not broken(stored[i["id"]].get("patterns", {"error": 1}))
    ][: args.first]
    llm = OpenAILLM.from_settings(settings, SpendLedger(cap_usd=1.0))
    router, guard, spent, cache = (
        default_router(settings),
        default_guard(settings),
        [0.0],
        {},
    )
    rows, same, before_right, now_right = [], 0, 0, 0
    for item in items:
        now = ask_one(
            "patterns", llm, router, guard, item, _frame_for(item, cache), spent
        )
        was = stored[item["id"]]["patterns"]
        before_right += bool(was.get("fair"))
        now_right += bool(now.get("fair"))
        same += bool(was.get("fair")) == bool(now.get("fair"))
        rows.append(
            {
                "id": item["id"],
                "q": item["q"],
                "before": was.get("fair"),
                "now": now.get("fair"),
            }
        )
        mark = "same" if bool(was.get("fair")) == bool(now.get("fair")) else "CHANGED"
        print(
            f"{mark:7s} before={int(bool(was.get('fair')))} now={int(bool(now.get('fair')))} | {item['q'][:70]}"
        )
    summary = {
        "batch": args.batch,
        "questions": len(items),
        "right_before": before_right,
        "right_now": now_right,
        "same_grade": same,
        "cost_usd": round(spent[0], 4),
    }
    out = (
        Path(__file__).parent
        / "results"
        / f"phia_regression_{args.batch}_{datetime.now(UTC).date()}.json"
    )
    out.write_text(json.dumps({**summary, "rows": rows}, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
