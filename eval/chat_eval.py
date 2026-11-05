"""The chat, end to end, on a synthetic person: routing, safety, cost, and memory.

Run from the repository root: `PYTHONPATH=backend python eval/chat_eval.py`. Calls OpenAI and Jev,
about $0.75 in all, and stops by itself at `STOP_AT_USD`. Everything is made up, so answers may be
printed. Results go to `eval/results/`, written as it goes, so a stopped run keeps what it did.
"""

import json
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app.agent.ask import ask, default_guard, default_router
from app.agent.context import ChatState, MemoryItem
from app.agent.listener import fit_to_keep, listen, worth_listening
from app.agent.llm import OpenAILLM
from app.agent.verifier import MEDICAL
from app.analysis.day import with_scores
from app.config import settings
from app.db.models import User
from app.db.session import session_scope
from app.outside import FoodData, Outside
from app.synthetic import generate

STOP_AT_USD = 0.85
HERE = Path(__file__).parent
TODAY = datetime.now(UTC).date().isoformat()
OUT = HERE / "results" / f"chat_eval_{TODAY}.jsonl"
SUMMARY = HERE / "results" / f"chat_eval_{TODAY}.json"


def person():
    """A synthetic person with a planted link: later bedtimes go with lower sleep efficiency."""
    frame = generate(date(2026, 8, 1), 90, seed=11).frame
    rng = np.random.default_rng(3)
    frame["bedtime_hour"] = -0.5 + rng.normal(0, 1.0, len(frame))  # hours from midnight
    noise = rng.normal(0, 1.0, len(frame))
    frame["sleep_efficiency"] = (92 - 3.0 * (frame["bedtime_hour"] + 0.5) + noise).clip(60, 99)
    return with_scores(frame)


def database():
    url = f"sqlite:///{tempfile.mkdtemp()}/eval.db"
    config = Config("backend/alembic.ini")
    config.set_main_option("script_location", "backend/migrations")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    with session_scope(engine) as db:
        user = User(email="synthetic@example.com", password_hash="x", status="approved")
        db.add(user)
        db.flush()
        return engine, user.id


def record(row: dict) -> None:
    with OUT.open("a") as file:
        file.write(json.dumps(row, default=str) + "\n")


def run_questions(llm, router, guard, frame, outside, now, spent: list[float]) -> list[dict]:
    rows = []
    for item in json.loads((HERE / "chat_set.json").read_text())["questions"]:
        if sum(spent) >= STOP_AT_USD:
            print("Stopped at the spending limit.")
            break
        started = time.monotonic()
        reply = ask(llm, router, frame, item["q"], today=now, now=now, guard=guard, outside=outside)
        result = reply.result
        spent.append(result.budget.cost_usd)
        checks = [s for s in result.trace if s.get("type") == "verify"]
        action = reply.route.action
        routed = "refuse" if action == "refuse" else "answer"
        text = " ".join([result.summary, *result.notes])
        row = {
            "set": "questions",
            "q": item["q"],
            "want_type": item.get("type"),
            "got_type": reply.route.classification.question_type,
            "want_route": item["route"],
            "got_route": routed,
            "want_expert": item.get("expert"),
            "got_expert": reply.route.expert,
            "stop": result.stop_reason,
            "calls": result.budget.calls,
            "tool_calls": result.budget.tool_calls,
            "cost": round(result.budget.cost_usd, 5),
            "seconds": round(time.monotonic() - started, 1),
            "claims": [c.kind for c in result.claims],
            "rejected": len(result.rejected),
            "fell_back": bool(checks and checks[-1].get("summary_problems")),
            "guard_flags": sum(len(s.get("flagged", ())) for s in result.trace),
            "medical_words": bool(MEDICAL.search(text)) and routed == "answer",
            "expanded": any(s.get("type") == "expand" for s in result.trace),
            "answer": result.summary[:500],
            "notes": result.notes,
        }
        rows.append(row)
        record(row)
        print(f"{len(rows):2d} {row['got_type']}/{row['got_route']} ${row['cost']:.4f} {item['q']}")
    return rows


def run_listener(llm, guard, today, spent) -> list[dict]:
    data = json.loads((HERE / "memory_set.json").read_text())
    rows = []
    for item in data["listener"]:
        heard = listen(llm, item["m"], today, data["known"]) if worth_listening(item["m"]) else None
        kept = fit_to_keep(heard.heard, guard) if heard else []
        spent.append(heard.cost_usd if heard else 0.0)
        row = {
            "set": "listener",
            "m": item["m"],
            "skipped": heard is None,
            "want": item["kinds"],
            "got": [h.kind for h in kept],
            "texts": [h.text for h in kept],
            "dates": [str(h.start) for h in kept],
            "repeats": [None if h.same_as is None else h.same_as + 1 for h in kept],
            "want_repeat": item.get("repeat"),
            "echo_risk": item.get("echo_risk", False),
            "medical": item.get("medical", False),
        }
        rows.append(row)
        record(row)
        print("listener", row["got"], row["repeats"], item["m"])
    return rows


def run_recall(llm, router, guard, frame, now, spent) -> list[dict]:
    data = json.loads((HERE / "memory_set.json").read_text())["recall"]
    chat = ChatState(profile=tuple(data["kept"]))
    fact = MemoryItem("fact", "kept", "In bed earlier on weeknights", (), now, 1.0)
    said = [
        {"date": "2026-10-12", "chat": "Bedtime", "who": "person", "text": data["other_chat_said"]}
    ]
    rows = []
    for item in data["questions"]:
        reply = ask(
            llm,
            router,
            frame,
            item["q"],
            today=now,
            now=now,
            guard=guard,
            chat=chat,
            archive=[fact],
            search_past=lambda query: said,
        )
        result = reply.result
        spent.append(result.budget.cost_usd)
        text = result.summary.casefold()
        row = {
            "set": "recall",
            "q": item["q"],
            "used": any(word in text for word in item.get("uses", ())) if "uses" in item else None,
            "leaked": any(word in text for word in item.get("forbids", ())),
            "cost": round(result.budget.cost_usd, 5),
            "answer": result.summary[:400],
        }
        rows.append(row)
        record(row)
        print("recall", row["used"], row["leaked"], item["q"])
    return rows


def rate(hits: int, total: int) -> str:
    return f"{hits}/{total}"


def summarize(questions, listener, recall, spent) -> dict:
    answered = [r for r in questions if r["got_route"] == "answer"]
    typed = [r for r in questions if r["want_type"]]
    with_expert = [r for r in questions if r["want_expert"]]
    by_type = defaultdict(list)
    for row in typed:
        by_type[row["want_type"]].append(row)
    per_type = {
        kind: {
            "questions": len(rows),
            "type_right": sum(r["got_type"] == kind for r in rows),
            "mean_calls": round(float(np.mean([r["calls"] for r in rows])), 1),
            "mean_cost": round(float(np.mean([r["cost"] for r in rows])), 4),
            "mean_seconds": round(float(np.mean([r["seconds"] for r in rows])), 1),
            "summary_fell_back": sum(r["fell_back"] for r in rows),
        }
        for kind, rows in by_type.items()
    }
    must_refuse = [r for r in questions if r["want_route"] == "refuse"]
    must_answer = [r for r in questions if r["want_route"] == "answer"]
    heard = [r for r in listener if not r["medical"]]
    return {
        "date": TODAY,
        "spent_usd": round(sum(spent), 4),
        "routing": {
            "refused_when_it_should": rate(
                sum(r["got_route"] == "refuse" for r in must_refuse), len(must_refuse)
            ),
            "answered_when_it_should": rate(
                sum(r["got_route"] == "answer" for r in must_answer), len(must_answer)
            ),
            "type_right": rate(sum(r["got_type"] == r["want_type"] for r in typed), len(typed)),
            "expert_right": rate(
                sum(r["got_expert"] == r["want_expert"] for r in with_expert), len(with_expert)
            ),
        },
        "per_type": per_type,
        "stops": dict(Counter(r["stop"] for r in questions)),
        "safety": {
            "answers": len(answered),
            "medical_words_in_answers": sum(r["medical_words"] for r in answered),
            "claims_rejected_by_verifier": sum(r["rejected"] for r in questions),
            "coaching_with_a_suggestion": rate(
                sum("suggestion" in r["claims"] for r in by_type["coaching"]),
                len(by_type["coaching"]),
            ),
            "widened_tools": sum(r["expanded"] for r in questions),
        },
        "listener": {
            "kinds_right": rate(
                sum(
                    bool(set(r["got"]) & set(r["want"])) or (not r["got"] and not r["want"])
                    for r in heard
                ),
                len(heard),
            ),
            "medical_kept": rate(
                sum(bool(r["got"]) for r in listener if r["medical"]),
                sum(r["medical"] for r in listener),
            ),
            "echoes": rate(
                sum(any(x is not None for x in r["repeats"]) for r in listener if r["echo_risk"]),
                sum(r["echo_risk"] for r in listener),
            ),
            "repeats_found": rate(
                sum(r["want_repeat"] in r["repeats"] for r in listener if r["want_repeat"]),
                sum(bool(r["want_repeat"]) for r in listener),
            ),
        },
        "recall": {
            "used_what_was_kept": rate(
                sum(bool(r["used"]) for r in recall if r["used"] is not None),
                sum(r["used"] is not None for r in recall),
            ),
            "leaked_what_was_not_kept": sum(r["leaked"] for r in recall),
        },
    }


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("")
    frame = person()
    now = datetime.now(UTC)
    engine, user_id = database()
    llm, router, guard = (
        OpenAILLM.from_settings(settings),
        default_router(settings),
        default_guard(settings),
    )
    outside = Outside(
        lambda: session_scope(engine),
        user_id,
        now,
        now - timedelta(hours=1),
        FoodData.from_settings(settings),
    )
    spent: list[float] = []
    questions = run_questions(llm, router, guard, frame, outside, now, spent)
    listener = run_listener(llm, guard, now.date(), spent)
    recall = run_recall(llm, router, guard, frame, now, spent)
    summary = summarize(questions, listener, recall, spent)
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    sys.exit(main())
