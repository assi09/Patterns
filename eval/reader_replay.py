"""Replays only the request reader on an audit's turns, with the context it saw, keeping each
reading, any retry and why. Paid: about $0.001 a turn. The audit kept only the final request, so
whether a failure was the reader's misreading or code rejecting a good reading was unknowable.

Failed and partial turns go first, then a few passing ones as controls; the run stops at a hard
cap. Each turn gets the original question, the profile's local date, the earlier questions and
answers of its conversation, the request state its previous turn saved, and whether a draft card
was waiting. Answers are the recorded replies, and the waiting card is read from the store as it
was before the turn: both are marked as reconstructed. These are new readings on today's code:
they can reproduce a failure, not recover the readings the original run discarded.

    PYTHONPATH=backend .venv/bin/python eval/reader_replay.py \\
        --audit data/eval/independent_validation_v4_run_2026-11-19 \\
        --bundle data/eval/independent_validation_v4_2026-11-19 \\
        --out data/eval/reader_replay_2026-11-19 --cap 0.067
"""

import argparse
import json
import pickle
from datetime import date, datetime
from pathlib import Path

from app.agent.context import Turn
from app.agent.llm import BudgetExceeded, OpenAILLM, SpendLedger
from app.agent.requests import interpret
from app.config import settings

CONTROLS = 12


def chosen(conversations: list[dict], grades: dict) -> list[tuple[str, str]]:
    """Every failed or partial turn, then one passing turn per family that failed somewhere (the
    all-metric family three times), as controls for readings that a check sends back wrongly."""
    order = [(c["id"], t["id"]) for c in conversations for t in c["turns"]]
    family = {c["id"]: c["family"] for c in conversations}
    missed = [key for key in order if grades[f"{key[0]}/{key[1]}"]["status"] != "pass"]
    failing = {family[c] for c, _ in missed}
    controls, seen = [], {}
    for key in order:
        name = family[key[0]]
        allowed = 3 if name == "all_metrics" else 1
        if key in missed or seen.get(name, 0) >= allowed:
            continue
        if name in failing or name == "all_metrics":
            controls.append(key)
            seen[name] = seen.get(name, 0) + 1
    return missed + controls[:CONTROLS]


def jobs(args, conversations, profiles, grades, rows) -> list[dict]:
    """Each turn to read with the context it had: the audit's misses and controls, or exactly the
    turns an expectations file lists (standalone questions there have no context)."""
    by_id = {c["id"]: c for c in conversations}
    if args.only:
        listed = json.loads(args.only.read_text())["turns"]
        keys = [tuple(t["id"].split("/")) for t in listed]
        standalone = {tuple(t["id"].split("/")): t for t in listed if "question" in t}
    else:
        keys, standalone = chosen(conversations, grades), {}
    found = []
    for conversation, turn in keys:
        if (conversation, turn) in standalone:
            item = standalone[(conversation, turn)]
            found.append(
                {
                    "conversation": conversation,
                    "turn": turn,
                    "family": "standalone",
                    "graded": "control",
                    "question": item["question"],
                    "today": date.fromisoformat(item["today"]),
                    "history": [],
                    "waiting": False,
                }
            )
            continue
        conv = by_id[conversation]
        history = []
        for earlier in conv["turns"]:
            if earlier["id"] == turn:
                break
            row = rows[(conversation, earlier["id"])]
            state = next(
                (
                    s.get("state") or {}
                    for s in row["trace"]
                    if s.get("type") == "request"
                ),
                {},
            )
            history.append(
                Turn(row["question"], row["reply"]["text"], request_state=state)
            )
        row = rows[(conversation, turn)]
        found.append(
            {
                "conversation": conversation,
                "turn": turn,
                "family": conv["family"],
                "graded": grades[f"{conversation}/{turn}"]["status"],
                "question": row["question"],
                "today": datetime.fromisoformat(
                    profiles[conv["profile"]]["clock"]
                ).date(),
                "history": history,
                "waiting": any(
                    a["status"] == "draft" for a in row["before"].get("actions", [])
                ),
            }
        )
    return found


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cap", type=float, default=0.067)
    parser.add_argument(
        "--only", type=Path, help="an expectations file listing the turns to read"
    )
    args = parser.parse_args()

    conversations = json.loads((args.bundle / "conversations.json").read_text())
    profiles = pickle.loads((args.bundle / "profiles.pkl").read_bytes())
    grades = json.loads((args.audit / "adjudications.json").read_text())
    rows = {
        (r["conversation"], r["turn"]): r
        for r in map(
            json.loads, (args.audit / "answers.jsonl").read_text().splitlines()
        )
    }
    ledger = SpendLedger(cap_usd=args.cap)
    llm = OpenAILLM.from_settings(settings, ledger)
    args.out.mkdir(parents=True, exist_ok=True)
    out = (args.out / "readings.jsonl").open("w")
    done = 0
    for job in jobs(args, conversations, profiles, grades, rows):
        if ledger.spent_usd >= args.cap:
            print(f"Stopped at the cap after {done} turns.")
            break
        # The reader turns a refused call into a clarification, so the cap shows up there.
        request, _, budget = interpret(
            llm,
            job["question"],
            job["history"],
            job["today"],
            pending_draft=job["waiting"],
            keep_readings=True,
        )
        if request is not None and request.reader_error == BudgetExceeded.__name__:
            print(f"Stopped at the cap after {done} turns; this turn is not recorded.")
            break
        done += 1
        out.write(
            json.dumps(
                {
                    "conversation": job["conversation"],
                    "turn": job["turn"],
                    "family": job["family"],
                    "graded": job["graded"],
                    "question": job["question"],
                    "today": job["today"].isoformat(),
                    "pending_draft": job["waiting"],
                    "reconstructed": [
                        "earlier answers from recorded replies",
                        "pending_draft",
                    ],
                    "request": request.model_dump(mode="json") if request else None,
                    "cost_usd": budget.cost_usd,
                    "calls": budget.calls,
                },
                default=str,
            )
            + "\n"
        )
        out.flush()
    print(f"{done} turns, ${ledger.spent_usd:.4f} spent of a ${args.cap} cap.")


if __name__ == "__main__":
    main()
