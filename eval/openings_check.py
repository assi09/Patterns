"""Is "on how many nights was my sleep tracked?" read as a sleep count, on each version?

In the missing-dates chat check (2026-11-23), two opening wordings were sometimes read as a look
at every measure: "on how many nights was my sleep tracked?" (2 of 5) and "How many nights of
sleep got recorded" (1 of 5). The same 20 openings (no history) are read once with the code given
by PYTHONPATH; right is coverage of sleep_minutes over exactly that week.

    PYTHONPATH=backend .venv/bin/python eval/openings_check.py freeze
    PYTHONPATH=<code>/backend .venv/bin/python eval/openings_check.py run --sha <sha> --label main
    PYTHONPATH=backend .venv/bin/python eval/openings_check.py score
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

SOURCE = Path("data/eval/missing_dates_check_2026-11-23/jobs.json")
OUT = Path("data/eval/openings_check_2026-11-23")
JOBS = OUT / "jobs.json"
CAP_USD = 0.15


def freeze() -> None:
    jobs = [
        {
            "case": j["case"],
            "today": j["today"],
            "question": j["questions"][0],
            "wording": j["questions"][0].split(" 20")[0],
            "expected": [["sleep_minutes"], "coverage", [j["week"]]],
        }
        for j in json.loads(SOURCE.read_text())["jobs"]
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"cap_usd": CAP_USD, "jobs": jobs}, sort_keys=True, indent=1)
    JOBS.write_text(body)
    print(f"{len(jobs)} openings frozen; cap ${CAP_USD} per version")
    print(f"sha256 {hashlib.sha256(body.encode()).hexdigest()}")


def run(sha: str, label: str) -> None:
    from app.agent.llm import OpenAILLM, SpendLedger
    from app.agent.requests import interpret
    from app.config import settings

    body = JOBS.read_text()
    if hashlib.sha256(body.encode()).hexdigest() != sha:
        raise ValueError("The frozen jobs changed since they were approved")
    out = OUT / f"{label}.jsonl"
    if out.exists():
        raise ValueError(
            f"{out} exists: a finished run is never rerun for a higher mark"
        )
    frozen = json.loads(body)
    ledger = SpendLedger(cap_usd=frozen["cap_usd"])
    llm = OpenAILLM.from_settings(settings, ledger)
    with out.open("w") as rows:
        for job in frozen["jobs"]:
            if ledger.spent_usd >= frozen["cap_usd"]:
                print("Stopped at the cap.")
                break
            today = date.fromisoformat(job["today"])
            request, _, budget = interpret(
                llm, job["question"], [], today, keep_readings=True
            )
            row = {"case": job["case"], "request": request.model_dump(mode="json")}
            rows.write(
                json.dumps(row | {"cost_usd": budget.cost_usd}, default=str) + "\n"
            )
    print(f"{label}: ${ledger.spent_usd:.6f} spent")


def resolved(request: dict) -> list:
    if request.get("kind") not in ("data", "causality"):
        return []
    return [
        [p["metrics"], p["operation"], [[w["start"], w["end"]] for w in p["windows"]]]
        for p in request.get("parts", [])
    ]


def score() -> None:
    jobs = {j["case"]: j for j in json.loads(JOBS.read_text())["jobs"]}
    for path in sorted(OUT.glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        right, kinds = Counter(), Counter()
        for row in rows:
            job = jobs[row["case"]]
            right[job["wording"], job["expected"] in resolved(row["request"])] += 1
            kinds[row["request"].get("kind")] += 1
        cost = sum(r["cost_usd"] for r in rows)
        print(
            f"== {path.stem}: {sum(n for (_, ok), n in right.items() if ok)}/{len(rows)}, ${cost:.6f}"
        )
        for wording in sorted({w for w, _ in right}):
            print(
                f"  {right[wording, True]}/{right[wording, True] + right[wording, False]}  {wording}"
            )
        print("  kinds:", dict(kinds))


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
