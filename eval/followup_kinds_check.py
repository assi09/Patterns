"""Do food edits and source questions resolve, read by the real reader, on each version?

Two follow-up kinds the reading could not express (pr-195-followup-issues.md item 4, and the
replay's control P8): a food follow-up that changes its nutrient, meal or records, and "where did
that come from?". Made-up states and fresh wordings; each turn is read once with the code given
by PYTHONPATH, so the same frozen set runs on main and on each fix.

    PYTHONPATH=backend .venv/bin/python eval/followup_kinds_check.py freeze
    PYTHONPATH=<code>/backend .venv/bin/python eval/followup_kinds_check.py run \\
        --sha <sha> --group food --label main
    PYTHONPATH=backend .venv/bin/python eval/followup_kinds_check.py score
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

OUT = Path("data/eval/followup_kinds_check_2026-11-23")
JOBS = OUT / "jobs.json"
CAP_USD = 0.20
TODAY = "2026-11-02"
DAY = ["2026-10-31", "2026-10-31"]
FOOD = {
    "question": "Read confirmed breakfast energy for October 31, 2026.",
    "answer": "On Sat, Oct 31 you logged 1 entry. Energy consumed: 327 kcal.",
    "state": {
        "last": "data",
        "data": [
            {
                "metrics": ["food_logs"],
                "operation": "food",
                "windows": [{"start": DAY[0], "end": DAY[1]}],
                "meal_type": "BREAKFAST",
                "nutrients": ["energy"],
            }
        ],
        "answer": {"kind": "data", "parts": 1, "reads": 0},
    },
}
PLANK = {
    "question": "How do I do a plank?",
    "answer": "Hold a straight line on your forearms and toes. From free-exercise-db.",
    "state": {"last": "guidance", "guidance": ["plank"]},
}
STEPS = {
    "question": "Total steps from 2026-10-19 to 2026-10-25?",
    "answer": "From Mon, Oct 19 to Sun, Oct 25, total steps: 61,204.",
    "state": {
        "last": "data",
        "data": [
            {
                "metrics": ["steps"],
                "operation": "sum",
                "windows": [{"start": "2026-10-19", "end": "2026-10-25"}],
            }
        ],
        "answer": {"kind": "data", "parts": 1, "reads": 0},
    },
}
SAME_MEAL = {
    "kind": "data",
    "operation": "food",
    "nutrients": ["protein"],
    "meal": "BREAKFAST",
}
ALL_MEALS = {
    "kind": "data",
    "operation": "food",
    "nutrients": ["protein"],
    "meal": None,
}
BURNED = {"kind": "data", "operation": "value", "metrics": ["calories"]}
SOURCE = {"kind": "source"}
JOBS_LIST = [
    ("food", FOOD, "And the protein for that same breakfast?", SAME_MEAL),
    ("food", FOOD, "How much protein was in that breakfast?", SAME_MEAL),
    ("food", FOOD, "Now protein across all my meals that day.", ALL_MEALS),
    (
        "food",
        FOOD,
        "Drop the breakfast filter and give me the day's protein.",
        ALL_MEALS,
    ),
    (
        "food",
        FOOD,
        "What about the calories my tracker says I burned that day?",
        BURNED,
    ),
    ("food", FOOD, "Same day, but energy burned according to the watch.", BURNED),
    ("source", PLANK, "Where's that information from?", SOURCE),
    ("source", PLANK, "What is that advice based on?", SOURCE),
    ("source", PLANK, "Can you tell me your source for that?", SOURCE),
    ("source", STEPS, "Which data did you use for that number?", SOURCE),
    ("source", STEPS, "Where does that figure come from?", SOURCE),
    ("source", STEPS, "What's that total based on?", SOURCE),
]


def freeze() -> None:
    jobs = [
        {
            "id": f"{group}-{i}",
            "group": group,
            "before": before,
            "question": q,
            "want": want,
        }
        for i, (group, before, q, want) in enumerate(JOBS_LIST)
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"cap_usd": CAP_USD, "jobs": jobs}, sort_keys=True, indent=1)
    JOBS.write_text(body)
    print(f"{len(jobs)} turns frozen; cap ${CAP_USD} per run")
    print(f"sha256 {hashlib.sha256(body.encode()).hexdigest()}")


def run(sha: str, group: str, label: str) -> None:
    from app.agent.context import Turn
    from app.agent.llm import OpenAILLM, SpendLedger
    from app.agent.requests import interpret
    from app.config import settings

    body = JOBS.read_text()
    if hashlib.sha256(body.encode()).hexdigest() != sha:
        raise ValueError("The frozen jobs changed since they were approved")
    out = OUT / f"{group}_{label}.jsonl"
    if out.exists():
        raise ValueError(
            f"{out} exists: a finished run is never rerun for a higher mark"
        )
    frozen = json.loads(body)
    ledger = SpendLedger(cap_usd=frozen["cap_usd"])
    llm = OpenAILLM.from_settings(settings, ledger)
    with out.open("w") as rows:
        for job in frozen["jobs"]:
            if job["group"] != group or ledger.spent_usd >= frozen["cap_usd"]:
                continue
            b = job["before"]
            history = [Turn(b["question"], b["answer"], request_state=b["state"])]
            request, _, budget = interpret(
                llm,
                job["question"],
                history,
                date.fromisoformat(TODAY),
                keep_readings=True,
            )
            row = {"id": job["id"], "request": request.model_dump(mode="json")}
            rows.write(
                json.dumps(row | {"cost_usd": budget.cost_usd}, default=str) + "\n"
            )
    print(f"{group} {label}: ${ledger.spent_usd:.6f} spent")


def right(want: dict, request: dict) -> bool:
    if request.get("kind") != want["kind"]:
        return False
    if want["kind"] == "source":
        return True
    parts = request.get("parts", [])
    if len(parts) != 1 or [[w["start"], w["end"]] for w in parts[0]["windows"]] != [
        DAY
    ]:
        return False
    part = parts[0]
    if part["operation"] != want["operation"]:
        return False
    if "metrics" in want and part["metrics"] != want["metrics"]:
        return False
    if "nutrients" in want and part.get("nutrients") != want["nutrients"]:
        return False
    return "meal" not in want or part.get("meal_type") == want["meal"]


def score() -> None:
    jobs = {j["id"]: j for j in json.loads(JOBS.read_text())["jobs"]}
    for path in sorted(OUT.glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        got, kinds = Counter(), Counter()
        for row in rows:
            job = jobs[row["id"]]
            got[right(job["want"], row["request"])] += 1
            kinds[row["request"].get("kind")] += 1
        cost = sum(r["cost_usd"] for r in rows)
        print(
            f"{path.stem:14} {got[True]}/{len(rows)}  ${cost:.6f}  kinds {dict(kinds)}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    paid = sub.add_parser("run")
    paid.add_argument("--sha", required=True)
    paid.add_argument("--group", choices=("food", "source"), required=True)
    paid.add_argument("--label", required=True)
    sub.add_parser("score")
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
    elif args.command == "run":
        run(args.sha, args.group, args.label)
    else:
        score()


if __name__ == "__main__":
    main()
