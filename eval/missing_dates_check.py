"""Which dates have no sleep record, through the chat, with fresh wording. Paid, with a hard cap.

The Fitbit replay of 2026-11-22 completed "which dates have no sleep record?" after a count of
recorded nights in 0 of 43 reserved conversations. This asks the same kind of two-turn question
of 20 of those reserved weeks, in wordings the replay never used: a count of recorded nights for
a week, then which dates are missing. The expected dates are the frozen manifest's independent
key; the wordings, the weeks and the cap are frozen and hashed before any reply.

A conversation passes when its second reply cites coverage evidence for sleep over exactly that
week, the evidence lists exactly the key's missing dates, and the reply names each of them. The
first reply is graded too: its evidence counts the key's recorded nights.

    PYTHONPATH=backend:eval .venv/bin/python eval/missing_dates_check.py freeze
    PYTHONPATH=backend:eval .venv/bin/python eval/missing_dates_check.py run --sha <from freeze>
    PYTHONPATH=backend:eval .venv/bin/python eval/missing_dates_check.py score

`run` uses the local replay harness (`data/eval/910_final_inputs`, git-ignored, with the public
PMData and LifeSnaps frames under `data/eval/bank_run_1122`): no Google traffic, a frozen clock
per conversation. Prints aggregates only; replies stay in the ignored data folder.
"""

import argparse
import hashlib
import json
import random
import subprocess
from collections import Counter
from datetime import date
from pathlib import Path

BANK = "f27b1d764f5cc91f6d0af4971ec019440989d5b3c6ea059925abc87d55497c04"
MANIFEST = Path(f"data/eval/scenario-bank/{BANK}.jsonl")
OUT = Path("data/eval/missing_dates_check_2026-11-23")
JOBS = OUT / "jobs.json"
RESULTS = OUT / "results.jsonl"
SEED = 20261123
COUNT = 20
CAP_USD = 0.40

# None of these is the replay's wording ("How many nights have sleep records from … through …?",
# "Which dates have no sleep record?").
OPENINGS = (
    "For {start} to {end}, on how many nights was my sleep tracked?",
    "Between {start} and {end}, how many nights do I have sleep data for?",
    "Count the nights with a sleep log from {start} until {end}.",
    "How many nights of sleep got recorded in the week {start} to {end}?",
)
FOLLOW_UPS = (
    "Which nights were the missing ones?",
    "Tell me the exact dates without sleep data.",
    "On which days is there nothing recorded?",
    "List the gaps, date by date.",
    "And which dates are those?",
)


def freeze() -> None:
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BANK:
        raise ValueError("Unexpected manifest fingerprint")
    reserved = [
        c
        for c in map(json.loads, raw.splitlines())
        if c["family"] == "missing_nights" and c["split"] == "evaluation"
    ]
    chosen = sorted(random.Random(SEED).sample(reserved, COUNT), key=lambda c: c["id"])
    jobs = []
    for index, case in enumerate(chosen):
        start = date.fromisoformat(case["week"])
        end = date.fromordinal(start.toordinal() + 6)
        jobs.append(
            {
                "case": case["id"],
                "source": case["source"],
                "member": case["members"][0],
                "today": case["today"],
                "week": [start.isoformat(), end.isoformat()],
                "questions": [
                    OPENINGS[index % len(OPENINGS)].format(start=start, end=end),
                    FOLLOW_UPS[index % len(FOLLOW_UPS)],
                ],
                "recorded": case["expected"][0]["recorded_nights"],
                "missing": case["expected"][1]["missing_dates"],
            }
        )
    OUT.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        {"bank": BANK, "cap_usd": CAP_USD, "jobs": jobs}, sort_keys=True, indent=1
    )
    JOBS.write_text(body)
    print(
        f"{len(jobs)} conversations frozen from {len(reserved)} reserved weeks; cap ${CAP_USD}"
    )
    print(f"sha256 {hashlib.sha256(body.encode()).hexdigest()}")


def run(sha: str) -> None:
    import pickle
    import sys
    import warnings
    from datetime import UTC, datetime
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    import pandas as pd

    body = JOBS.read_text()
    if hashlib.sha256(body.encode()).hexdigest() != sha:
        raise ValueError("The frozen jobs changed since they were approved")
    if RESULTS.exists():
        raise ValueError(
            f"{RESULTS} exists: a finished run is never rerun for a higher mark"
        )
    frozen = json.loads(body)
    root = Path.cwd()
    sys.path.insert(0, str(root / "data/eval/910_final_inputs"))
    warnings.filterwarnings("ignore")
    import run_independent_validation as audit
    from app.agent.llm import LLMError
    from app.api import auth, store
    from app.auth import accounts
    from app.config import settings
    from app.db.models import User
    from app.ingest.takeout import DailyData

    settings.sentry_dsn = None
    settings.email_backend = "outbox"
    frames = pickle.loads((root / "data/eval/bank_run_1122/frames.pkl").read_bytes())
    audit.CAP = frozen["cap_usd"]
    harness = audit.Harness(SimpleNamespace(repo=root), OUT, True)
    settings.timezone = "Asia/Beirut"
    settings.chat_daily_cap_per_user_usd = settings.chat_daily_cap_total_usd = frozen[
        "cap_usd"
    ]

    def no_search(*_args, **_kwargs):
        raise LLMError("Web search disabled in this check")

    harness.llm.search = no_search
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    with RESULTS.open("w") as out:
        for job in frozen["jobs"]:
            zone = ZoneInfo("Asia/Beirut")
            audit.NOW = datetime.fromisoformat(job["today"] + "T12:00:00").replace(
                tzinfo=zone
            )
            audit.NOW = audit.NOW.astimezone(UTC)
            audit.FixedClock.ticks = 0
            harness.app.dependency_overrides[auth.now] = lambda: audit.FixedClock.now(
                UTC
            )
            stop = pd.Timestamp(job["today"]) - pd.Timedelta(days=1)
            person = frames[job["source"]][job["member"]].loc[:stop].copy()
            harness.active = store.analyze(
                DailyData(frame=person), audit.NOW, "google_health"
            )
            with harness.sessions() as db:
                user = User(
                    email=f"{job['case']}-dates@example.com",
                    status="approved",
                    role="member",
                    timezone="Asia/Beirut",
                )
                db.add(user)
                db.flush()
                token = accounts.start_session(db, user, audit.NOW, 10)
            headers = {"Authorization": f"Bearer {token}"}
            conversation = harness.client.post(
                "/conversations", headers=headers, json={}
            ).json()
            turns = []
            for question in job["questions"]:
                response = harness.client.post(
                    "/chat",
                    headers=headers,
                    json={"text": question, "conversationId": conversation["id"]},
                )
                if response.status_code >= 400:
                    turns.append({"http": response.status_code})
                    break
                last = response.json()[-1]
                evidence = [
                    harness.client.get(f"/evidence/{e}", headers=headers).json()
                    for e in last.get("evidenceIds", [])
                ]
                turns.append({"text": last["text"], "evidence": evidence})
            spent = (
                json.loads((OUT / "spend.json").read_text())
                if (OUT / "spend.json").exists()
                else {}
            )
            row = {
                "case": job["case"],
                "commit": commit,
                "turns": turns,
                "spend": spent,
            }
            out.write(json.dumps(row, default=str) + "\n")
            out.flush()
    print(f"{len(frozen['jobs'])} conversations; spend in {OUT / 'spend.json'}")


def named(text: str, day: str) -> bool:
    when = date.fromisoformat(day)
    return any(
        form in text for form in (day, when.strftime("%b %-d"), when.strftime("%B %-d"))
    )


def grade(job: dict, turns: list[dict]) -> tuple[str, str]:
    week = [{"start": job["week"][0], "end": job["week"][1]}]
    first = turns[0] if turns else {}
    counted = [
        e
        for e in first.get("evidence", [])
        if e.get("tool") == "coverage"
        and e.get("windows") == week
        and e.get("stats", {}).get("days_present", {}).get("sleep_minutes")
        == job["recorded"]
    ]
    opening = "pass" if counted else "no matching count"
    if len(turns) < 2 or "text" not in turns[1]:
        return opening, "no second reply"
    second = turns[1]
    listed = [
        e
        for e in second["evidence"]
        if e.get("tool") == "coverage" and "missing_dates" in e.get("stats", {})
    ]
    if not listed:
        return opening, "no list of dates"
    if not any(e["windows"] == week for e in listed):
        return opening, "other days"
    exact = [
        e
        for e in listed
        if e["stats"]["missing_dates"].get("sleep_minutes") == job["missing"]
    ]
    if not exact:
        return opening, "wrong dates"
    if not all(named(second["text"], day) for day in job["missing"]):
        return opening, "reply leaves a date out"
    return opening, "pass"


def score() -> None:
    jobs = {j["case"]: j for j in json.loads(JOBS.read_text())["jobs"]}
    rows = [json.loads(line) for line in RESULTS.read_text().splitlines()]
    openings, follow_ups, by_wording = Counter(), Counter(), Counter()
    for row in rows:
        job = jobs[row["case"]]
        opening, follow_up = grade(job, row["turns"])
        openings[opening] += 1
        follow_ups[follow_up] += 1
        by_wording[job["questions"][1], follow_up == "pass"] += 1
    print("opening count:", dict(openings))
    print("which dates:", dict(follow_ups))
    for (wording, passed), n in sorted(by_wording.items()):
        print(f"  {'pass' if passed else 'fail'} {n}  {wording}")
    print(
        f"{len(rows)} of {len(jobs)} run; commits {sorted({r['commit'][:7] for r in rows})}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    paid = sub.add_parser("run")
    paid.add_argument("--sha", required=True)
    sub.add_parser("score")
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
    elif args.command == "run":
        run(args.sha)
    else:
        score()


if __name__ == "__main__":
    main()
