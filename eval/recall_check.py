"""Is a question about what was said in this chat read as memory recall, on two versions?

The Fitbit replay's control P4: "What day did I just mention?" after "Just for this chat I plan
to walk on Friday. Don't save it." was read as outside the app, or sent back twice. The reader's
own definitions disagreed: memory was "what the app keeps", and what was said with "don't save"
is not kept. Fresh made-up wordings (none is the replay's); each second turn is read once with
the code given by PYTHONPATH, so the same frozen set runs on main and on the fix.

    PYTHONPATH=backend .venv/bin/python eval/recall_check.py freeze
    PYTHONPATH=<code>/backend .venv/bin/python eval/recall_check.py run --sha <sha> --label main
    PYTHONPATH=backend .venv/bin/python eval/recall_check.py score
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

OUT = Path("data/eval/recall_check_2026-11-23")
JOBS = OUT / "jobs.json"
CAP_USD = 0.25
TODAY = "2026-11-23"
NOTED = "Got it, I'll keep that just for this chat."
THIS_CHAT = ["this_chat", "all"]

UNSAVED = [
    (
        "Don't keep this, but I'm planning a long ride on Sunday.",
        "Which day did I say the ride was?",
    ),
    (
        "Only for now, not for my profile: I'm testing a 10-minute stretch after lunch.",
        "What did I say I'm testing?",
    ),
    (
        "Keep this to this chat only: my 5k race is on the 14th.",
        "When is my race, again?",
    ),
    (
        "No need to save this: I skipped my evening walk yesterday.",
        "What did I tell you I skipped?",
    ),
    (
        "Please don't remember this later, but I'm trying to sleep by 11 this week.",
        "What bedtime did I mention?",
    ),
    (
        "This is just for this conversation: I swim on Tuesdays.",
        "Which day do I swim, like I said?",
    ),
    (
        "Not something to store: I'm visiting family next weekend.",
        "Remind me what I said about next weekend?",
    ),
    ("Don't save it: I had coffee at 6 pm today.", "What time did I say I had coffee?"),
]
PLAIN = [
    ("I'm training for a half marathon in March.", "What am I training for?"),
    ("I usually lift weights on Monday evenings.", "When did I say I lift?"),
    ("My knee felt fine on today's walk.", "What did I just say about my walk?"),
    ("I started a new job this month.", "What did I mention about this month?"),
]
KEPT = [
    ("What preferences do you have saved for me?", ["kept", "all"]),
    ("Is anything waiting for my approval?", ["waiting", "all"]),
    ("What do you remember about me?", ["kept", "all"]),
]


def freeze() -> None:
    jobs = [
        {"id": f"unsaved-{i}", "group": "said, not to save", "before": b, "answer": NOTED,
         "question": q, "recall": THIS_CHAT}
        for i, (b, q) in enumerate(UNSAVED)
    ] + [
        {"id": f"plain-{i}", "group": "said", "before": b, "answer": "Thanks for telling me.",
         "question": q, "recall": THIS_CHAT}
        for i, (b, q) in enumerate(PLAIN)
    ] + [
        {"id": f"kept-{i}", "group": "kept (control)", "before": None, "answer": None,
         "question": q, "recall": r}
        for i, (q, r) in enumerate(KEPT)
    ]  # fmt: skip
    OUT.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"cap_usd": CAP_USD, "jobs": jobs}, sort_keys=True, indent=1)
    JOBS.write_text(body)
    print(
        f"{len(jobs)} turns frozen, read once per version; cap ${CAP_USD} per version"
    )
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
            history = [Turn(job["before"], job["answer"])] if job["before"] else []
            request, _, budget = interpret(
                llm,
                job["question"],
                history,
                date.fromisoformat(TODAY),
                keep_readings=True,
            )
            row = {
                "id": job["id"],
                "request": request.model_dump(mode="json") if request else None,
            }
            rows.write(
                json.dumps(row | {"cost_usd": budget.cost_usd}, default=str) + "\n"
            )
    print(f"{label}: ${ledger.spent_usd:.6f} spent")


def score() -> None:
    jobs = {j["id"]: j for j in json.loads(JOBS.read_text())["jobs"]}
    for path in sorted(OUT.glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        right, shapes = Counter(), Counter()
        for row in rows:
            job, request = jobs[row["id"]], row["request"] or {}
            ok = (
                request.get("kind") == "memory"
                and request.get("memory_action") == "recall"
                and request.get("recall") in job["recall"]
            )
            right[job["group"], ok] += 1
            shapes[job["group"], request.get("kind"), request.get("recall")] += 1
        print(f"== {path.stem}: ${sum(r['cost_usd'] for r in rows):.6f}")
        for group in dict.fromkeys(j["group"] for j in jobs.values()):
            total = right[group, True] + right[group, False]
            print(f"  {group:20} {right[group, True]}/{total}")
        print("  readings:", dict(shapes))


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
