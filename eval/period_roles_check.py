"""Does a period said to begin or end somewhere begin or end there, read by the real reader?

The audit of 910da27 (pr-195-followup-issues.md item 1): "four dates beginning two dates after
that last day" ended there, and "make the opening date the closing date of a three-day block"
began there. Paired wordings that differ only in begins/ends, against the same five-day result
(Mon Oct 12 to Fri Oct 16), read once with the code given by PYTHONPATH. Right is the expected
days, however the period was said.

    PYTHONPATH=backend .venv/bin/python eval/period_roles_check.py freeze
    PYTHONPATH=<code>/backend .venv/bin/python eval/period_roles_check.py run --sha <sha> --label main
    PYTHONPATH=backend .venv/bin/python eval/period_roles_check.py score
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

OUT = Path("data/eval/period_roles_check_2026-11-23")
JOBS = OUT / "jobs.json"
CAP_USD = 0.15
TODAY = "2026-11-02"
BEFORE = {
    "question": "Average steps from 2026-10-12 to 2026-10-16?",
    "answer": "From Mon, Oct 12 to Fri, Oct 16, daily average steps: 8,210.",
    "state": {
        "last": "data",
        "data": [
            {
                "metrics": ["steps"],
                "operation": "mean",
                "windows": [{"start": "2026-10-12", "end": "2026-10-16"}],
            }
        ],
        "answer": {"kind": "data", "parts": 1, "reads": 0},
    },
}
PAIRS = [
    ("Same average for three days ending on its first day.", ["2026-10-10", "2026-10-12"],
     "Same average for three days beginning on its first day.", ["2026-10-12", "2026-10-14"]),
    ("Use four dates beginning two dates after that last day.", ["2026-10-18", "2026-10-21"],
     "Use four dates ending two dates after that last day.", ["2026-10-15", "2026-10-18"]),
    ("Make the opening date the closing date of a three-day block.", ["2026-10-10", "2026-10-12"],
     "Make the opening date the first date of a three-day block.", ["2026-10-12", "2026-10-14"]),
    ("Now two days finishing the day before it started.", ["2026-10-10", "2026-10-11"],
     "Now two days starting the day before it started.", ["2026-10-11", "2026-10-12"]),
    ("Average a five-day window that closes on its final date.", ["2026-10-12", "2026-10-16"],
     "Average a five-day window that opens on its final date.", ["2026-10-16", "2026-10-20"]),
    ("Take the three days that end one day after its last day.", ["2026-10-15", "2026-10-17"],
     "Take the three days that start one day after its last day.", ["2026-10-17", "2026-10-19"]),
]  # fmt: skip


def freeze() -> None:
    jobs = []
    for i, (ends, ends_days, begins, begins_days) in enumerate(PAIRS):
        jobs += [
            {"id": f"{i}-ends", "role": "ends", "question": ends, "expected": ends_days},
            {"id": f"{i}-begins", "role": "begins", "question": begins, "expected": begins_days},
        ]
    OUT.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"cap_usd": CAP_USD, "jobs": jobs}, sort_keys=True, indent=1)
    JOBS.write_text(body)
    print(f"{len(jobs)} turns frozen; cap ${CAP_USD} per version")
    print(f"sha256 {hashlib.sha256(body.encode()).hexdigest()}")


def run(sha: str, label: str) -> None:
    from app.agent.context import Turn
    from app.agent.llm import OpenAILLM, SpendLedger
    from app.agent.requests import interpret
    from app.config import settings

    body = JOBS.read_text()
    if hashlib.sha256(body.encode()).hexdigest() != sha:
        raise ValueError("The frozen jobs changed since they were approved")
    out = OUT / f"{label}.jsonl"
    if out.exists():
        raise ValueError(f"{out} exists: a finished run is never rerun for a higher mark")
    frozen = json.loads(body)
    ledger = SpendLedger(cap_usd=frozen["cap_usd"])
    llm = OpenAILLM.from_settings(settings, ledger)
    history = [Turn(BEFORE["question"], BEFORE["answer"], request_state=BEFORE["state"])]
    with out.open("w") as rows:
        for job in frozen["jobs"]:
            if ledger.spent_usd >= frozen["cap_usd"]:
                print("Stopped at the cap.")
                break
            request, _, budget = interpret(
                llm, job["question"], history, date.fromisoformat(TODAY), keep_readings=True
            )
            row = {"id": job["id"], "request": request.model_dump(mode="json")}
            rows.write(json.dumps(row | {"cost_usd": budget.cost_usd}, default=str) + "\n")
    print(f"{label}: ${ledger.spent_usd:.6f} spent")


def score() -> None:
    jobs = {j["id"]: j for j in json.loads(JOBS.read_text())["jobs"]}
    for path in sorted(OUT.glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        right, pairs = Counter(), Counter()
        for row in rows:
            job, request = jobs[row["id"]], row["request"]
            days = [[w["start"], w["end"]] for p in request.get("parts", []) for w in p["windows"]]
            ok = request.get("kind") == "data" and days == [job["expected"]]
            right[job["role"], ok] += 1
            pairs[row["id"].split("-")[0]] += ok
        both = sum(n == 2 for n in pairs.values())
        cost = sum(r["cost_usd"] for r in rows)
        print(
            f"{path.stem:6} ends {right['ends', True]}/6, begins {right['begins', True]}/6, "
            f"both of a pair {both}/6  ${cost:.6f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    paid = sub.add_parser("run")
    paid.add_argument("--sha", required=True)
    paid.add_argument("--label", required=True)
    sub.add_parser("score")
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
    elif args.command == "run":
        run(args.sha, args.label)
    else:
        score()


if __name__ == "__main__":
    main()
