"""Reads the third turn of the replay's three-turn conversations again, on today's code, and
grades the resolved request against the bank's independent key. Paid: about $0.0035 a reading
(the reader and its read back), a hard cap. Run from the repository root.

The reader now sees each earlier result beside the question that asked for it. In the Fitbit
replay of 2026-11-22 it saw the results apart from the questions, labelled "last" and "older",
and "for that earlier week" named the opening week in 63 of 66 readings. Graded here:

- steps, turn 3: "For that earlier week, just Monday to Friday?" (the week just answered);
- resting heart rate, turn 3: "Just that earlier weekend?" (the weekend of the week just
  answered);
- sleep, turn 3: "Now average the full week before that week." after "Only that weekend?"
  (relative to the older result, the full week: the last answer is the wrong one here);
- a control on the reserved step conversations: "Now the first week I asked about, Monday to
  Friday only." (the opening week).

Each conversation's history is its recorded questions, replies and saved request states, with
the question each result answered added as today's code saves it. Only conversations whose
second turn was right are used. The baseline is the replay's own reading of the same turn, from
its saved traces (same model, same histories, the earlier prompt).

    PYTHONPATH=backend .venv/bin/python eval/reader_followups.py freeze
    PYTHONPATH=backend .venv/bin/python eval/reader_followups.py run --sha <printed by freeze>
    PYTHONPATH=backend .venv/bin/python eval/reader_followups.py score
"""

import argparse
import glob
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

BANK = "f27b1d764f5cc91f6d0af4971ec019440989d5b3c6ea059925abc87d55497c04"
CAPTURES = Path("data/eval/bank_run_1122")
MANIFEST = Path(f"data/eval/scenario-bank/{BANK}.jsonl")
OUT = Path("data/eval/reader_followups_2026-11-23")
JOBS = OUT / "jobs.json"
READINGS = OUT / "readings.jsonl"
CAP_USD = 0.95
FAMILIES = ("steps", "resting_hr", "sleep_minutes")
FIRST_WEEK = "Now the first week I asked about, Monday to Friday only."


def conversation(
    db: sqlite3.Connection, case: dict, capture: dict
) -> list[dict] | None:
    """The case's conversation in its shard, matched by its first question and first reply."""
    for (conv,) in db.execute(
        "select conversation_id from chat_messages where role='user' and text=?",
        (case["steps"][0],),
    ):
        rows = db.execute(
            "select m.role, m.text, t.steps from chat_messages m left join answer_traces t "
            "on t.message_id = m.id where m.conversation_id=? order by m.created_at",
            (conv,),
        ).fetchall()
        if len(rows) >= 2 and rows[1][1] == capture["turns"][0]["text"]:
            return [
                {"role": r, "text": t, "steps": json.loads(s) if s else None}
                for r, t, s in rows
            ]
    return None


def request_of(message: dict) -> dict:
    return next(s for s in message["steps"] if s["type"] == "request")


def resolved(request: dict | None) -> list:
    if not request or request.get("kind") not in ("data", "causality"):
        return []
    return [
        [p["metrics"], p["operation"], [[w["start"], w["end"]] for w in p["windows"]]]
        for p in request.get("parts", [])
    ]


def freeze() -> None:
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BANK:
        raise ValueError("Unexpected manifest fingerprint")
    jobs, skipped = [], Counter()
    for case in map(json.loads, raw.splitlines()):
        if case["family"] not in FAMILIES:
            continue
        paths = glob.glob(str(CAPTURES / f"paid[0-5]/{case['id']}.json"))
        capture = json.loads(Path(paths[0]).read_text())
        messages = conversation(
            sqlite3.connect(Path(paths[0]).parent / "api.sqlite"), case, capture
        )
        if not messages or len(messages) < 6:
            skipped[case["family"], "conversation not found"] += 1
            continue
        key = case["expected"]
        second = request_of(messages[3])
        want = [[key[1]["metric"]], key[1]["operation"], [key[1]["window"]]]
        if want not in resolved(second["request"]):
            skipped[case["family"], "turn two wrong"] += (
                1  # its history is another conversation
            )
            continue
        first = request_of(messages[1])["state"]
        state = second["state"]
        # What today's code saves: the question each result answered, `data` then `older`.
        asked = [messages[2]["text"]] * len(state["data"]) + [
            messages[0]["text"] if p in first["data"] else None for p in state["older"]
        ]
        history = [
            {
                "question": messages[0]["text"],
                "answer": messages[1]["text"],
                "state": first,
            },
            {
                "question": messages[2]["text"],
                "answer": messages[3]["text"],
                "state": state | {"asked": asked},
            },
        ]
        baseline = (
            resolved(request_of(messages[5])["request"]) if len(messages) > 5 else []
        )
        third = [[key[2]["metric"]], key[2]["operation"], [key[2]["window"]]]
        common = {"case": case["id"], "split": case["split"], "today": case["today"]}
        jobs.append(
            common
            | {
                "family": case["family"],
                "question": case["steps"][2],
                "history": history,
                "expected": third,
                "baseline_right": third in baseline,
            }
        )
        if case["family"] == "steps" and case["split"] == "evaluation":
            monday = date.fromisoformat(key[0]["window"][0])
            week = [monday.isoformat(), (monday + timedelta(days=4)).isoformat()]
            jobs.append(
                common
                | {
                    "family": "steps first week",
                    "question": FIRST_WEEK,
                    "history": history,
                    "expected": [["steps"], "sum", [week]],
                    "baseline_right": None,
                }
            )
    OUT.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        {"bank": BANK, "cap_usd": CAP_USD, "jobs": jobs}, sort_keys=True, indent=1
    )
    JOBS.write_text(body)
    print(f"{len(jobs)} readings frozen; skipped {dict(skipped)}")
    print(f"by family {dict(Counter(j['family'] for j in jobs))}; cap ${CAP_USD}")
    print(f"sha256 {hashlib.sha256(body.encode()).hexdigest()}")


def run(sha: str) -> None:
    from app.agent.context import Turn
    from app.agent.llm import BudgetExceeded, OpenAILLM, SpendLedger
    from app.agent.requests import interpret
    from app.config import settings

    body = JOBS.read_text()
    if hashlib.sha256(body.encode()).hexdigest() != sha:
        raise ValueError("The frozen jobs changed since they were approved")
    if READINGS.exists():
        raise ValueError(
            f"{READINGS} exists: a finished run is never rerun for a higher mark"
        )
    frozen = json.loads(body)
    ledger = SpendLedger(cap_usd=frozen["cap_usd"])
    llm = OpenAILLM.from_settings(settings, ledger)
    done = 0
    with READINGS.open("w") as out:
        for job in frozen["jobs"]:
            if ledger.spent_usd >= frozen["cap_usd"]:
                print(f"Stopped at the cap after {done} readings.")
                break
            history = [
                Turn(h["question"], h["answer"], request_state=h["state"])
                for h in job["history"]
            ]
            request, _, budget = interpret(
                llm,
                job["question"],
                history,
                date.fromisoformat(job["today"]),
                keep_readings=True,
            )
            if request is not None and request.reader_error == BudgetExceeded.__name__:
                print(
                    f"Stopped at the cap after {done} readings; this one is not recorded."
                )
                break
            done += 1
            row = {
                "case": job["case"],
                "family": job["family"],
                "request": request.model_dump(mode="json") if request else None,
                "cost_usd": budget.cost_usd,
            }
            out.write(json.dumps(row, default=str) + "\n")
            out.flush()
    print(
        f"{done} readings, ${ledger.spent_usd:.6f} spent of a ${frozen['cap_usd']} cap."
    )


def score() -> None:
    jobs = {(j["case"], j["family"]): j for j in json.loads(JOBS.read_text())["jobs"]}
    rows = [json.loads(line) for line in READINGS.read_text().splitlines()]
    now, before = Counter(), Counter()
    for row in rows:
        job = jobs[(row["case"], row["family"])]
        group = (job["family"], job["split"])
        now[group, job["expected"] in resolved(row["request"])] += 1
        if job["baseline_right"] is not None:
            before[group, job["baseline_right"]] += 1
    for group in sorted({g for g, _ in now}):
        total = now[group, True] + now[group, False]
        base = before[group, True] + before[group, False]
        was = f"replay {before[group, True]}/{base}" if base else "no baseline"
        print(f"{group[0]:18} {group[1]:10} now {now[group, True]}/{total}   {was}")
    print(f"{len(rows)} of {len(jobs)} read; ${sum(r['cost_usd'] for r in rows):.6f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    sub.add_parser("run").add_argument("--sha", required=True)
    sub.add_parser("score")
    args = parser.parse_args()
    {"freeze": freeze, "score": score}.get(args.command, lambda: run(args.sha))()


if __name__ == "__main__":
    main()
