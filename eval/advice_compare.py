"""Does vetted guidance make coaching answers better, and is the advice specific to the person?

Run from the repository root: `PYTHONPATH=backend python eval/advice_compare.py`. Calls OpenAI and
Jev, about $0.35, and stops by itself at `STOP_AT_USD`. Each coaching question runs three ways: no
cards, the cards code picks, and all cards in the prompt. Two synthetic people with made-up lives.
It also checks that plain questions get no advice, and what alerts say. Results are in
`eval/results/`; the markdown file hides which way is which, for reading blind, and the JSON holds
the key.
"""

import json
import random
import re
import sys
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

from app.agent.ask import ask, default_guard, default_router
from app.agent.context import ChatState, build
from app.agent.llm import OpenAILLM
from app.agent.verifier import GENERIC_ADVICE, MEDICAL
from app.alarms.detect import detect
from app.alarms.explain import explain
from app.alarms.run import text as alarm_text
from app.analysis.day import with_scores
from app.config import settings
from app.synthetic import generate

STOP_AT_USD = 0.36
ARMS = ("none", "picked", "all")
HERE = Path(__file__).parent
TODAY = datetime.now(UTC).date().isoformat()
QUESTIONS = (
    "How can I sleep better?",
    "How can I recover faster?",
    "How can I train smarter?",
    "What should I change to feel better in the morning?",
    "Give me one habit to work on this week",
    "How could I wind down better at night?",
    "What can I do to get my HRV up?",
    "How do I get more steps in?",
    "Any tips for sleeping more?",
)
PLAIN = ("How did I sleep last night?", "What's my usual HRV?", "Has my sleep changed lately?")
NUMBER = re.compile(r"\d")


def student():
    """Later bedtimes go with worse sleep, weekends drift, and exams are on."""
    frame = generate(date(2026, 8, 1), 90, seed=11).frame
    rng = np.random.default_rng(3)
    frame["bedtime_hour"] = -0.5 + rng.normal(0, 1.0, len(frame))
    frame.loc[frame.index.dayofweek >= 5, "bedtime_hour"] += 1.0
    noise = rng.normal(0, 1.0, len(frame))
    frame["sleep_efficiency"] = (92 - 3.0 * (frame["bedtime_hour"] + 0.5) + noise).clip(60, 99)
    frame.iloc[-3:, frame.columns.get_loc("sleep_minutes")] = 300.0  # three short nights
    return with_scores(frame), ("event: Exams this week", "goal: Be in bed earlier on weeknights")


def new_parent():
    """No planted link at all: the tests find nothing, so only their routine can speak."""
    frame = generate(date(2026, 8, 1), 90, seed=23).frame
    rng = np.random.default_rng(5)
    frame["bedtime_hour"] = -0.2 + rng.normal(0, 1.2, len(frame))
    return with_scores(frame), ("context: Has a newborn at home", "routine: Works from home")


def row_for(reply, person: str, question: str, arm: str) -> dict:
    result = reply.result
    text = " ".join([result.summary, *(c.text for c in result.claims), *result.notes])
    checks = [s for s in result.trace if s.get("type") == "verify"]
    suggestions = [c.text for c in result.claims if c.kind == "suggestion"]
    return {
        "person": person,
        "q": question,
        "arm": arm,
        "type": reply.route.classification.question_type,
        "stop": result.stop_reason,
        "cost": round(result.budget.cost_usd, 5),
        "calls": result.budget.calls,
        "suggestions": suggestions,
        "own_numbers": any(NUMBER.search(s) for s in suggestions),
        "generic": bool(GENERIC_ADVICE.search(text)),
        "medical": bool(MEDICAL.search(text)),
        "fell_back": bool(checks and checks[-1].get("summary_problems")),
        "words": len(result.summary.split()),
        "answer": result.summary,
    }


def main() -> None:
    llm, router, guard = (
        OpenAILLM.from_settings(settings),
        default_router(settings),
        default_guard(settings),
    )
    people = {"student": student(), "new parent": new_parent()}
    spent, rows, plain, alerts = 0.0, [], [], []
    now = datetime.now(UTC)

    for name, (frame, kept) in people.items():
        day = frame.index.max().date()
        chat = ChatState(profile=kept)
        context = build([], {}, chat=chat).block
        moment = datetime(day.year, day.month, day.day, 20, tzinfo=UTC)
        for candidate in detect(frame, day + timedelta(days=0))[:2]:
            title, body = alarm_text(candidate)
            told = explain(
                llm,
                frame,
                kind=candidate.kind,
                metric=candidate.metric,
                title=title,
                body=body,
                evidence=candidate.evidence,
                today=day,
                guard=guard,
                context=context,
            )
            spent += told.cost_usd
            alerts.append(
                {
                    "person": name,
                    "kind": candidate.kind,
                    "title": title,
                    "said": told.body,
                    "by": told.written_by,
                    "cost": round(told.cost_usd, 5),
                }
            )
            print("alert", candidate.kind, told.written_by, told.body[:160])
        for question in PLAIN[:2] if name == "student" else PLAIN[2:]:
            reply = ask(
                llm, router, frame, question, today=moment, now=moment, guard=guard, chat=chat
            )
            spent += reply.result.budget.cost_usd
            plain.append(row_for(reply, name, question, "picked"))

    for question in QUESTIONS:
        for name, (frame, kept) in people.items():
            day = frame.index.max().date()
            moment = datetime(day.year, day.month, day.day, 20, tzinfo=UTC)
            for arm in ARMS:
                if spent >= STOP_AT_USD:
                    continue
                reply = ask(
                    llm,
                    router,
                    frame,
                    question,
                    today=moment,
                    now=moment,
                    guard=guard,
                    chat=ChatState(profile=kept),
                    guidance_mode=arm,
                )
                spent += reply.result.budget.cost_usd
                row = row_for(reply, name, question, arm)
                rows.append(row)
                print(f"${spent:.3f} {arm:6} {name:10} {row['own_numbers']!s:5} {question}")

    by_arm = defaultdict(list)
    for row in rows:
        by_arm[row["arm"]].append(row)
    summary = {
        "date": TODAY,
        "spent_usd": round(spent, 4),
        "started": now.isoformat(),
        "arms": {
            arm: {
                "answers": len(found),
                "gave_a_suggestion": sum(bool(r["suggestions"]) for r in found),
                "suggestion_with_own_number": sum(r["own_numbers"] for r in found),
                "generic_phrases": sum(r["generic"] for r in found),
                "medical_words": sum(r["medical"] for r in found),
                "summary_fell_back": sum(r["fell_back"] for r in found),
                "mean_cost": round(float(np.mean([r["cost"] for r in found])), 4),
                "mean_words": round(float(np.mean([r["words"] for r in found])), 1),
            }
            for arm, found in by_arm.items()
        },
        "plain_questions_with_a_suggestion": sum(bool(r["suggestions"]) for r in plain),
        "plain_questions": len(plain),
        "alerts": alerts,
    }
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    rng = random.Random(7)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["person"], row["q"])].append(row)
    lines, key = ["# Advice, read blind\n"], {}
    for (person, question), found in groups.items():
        lines.append(f"## {person}: {question}\n")
        rng.shuffle(found)
        for letter, row in zip("ABC", found, strict=False):
            lines.append(f"**{letter}.** {row['answer']}\n")
            key[f"{person}: {question}: {letter}"] = row["arm"]
    (out / f"advice_blind_{TODAY}.md").write_text("\n".join(lines))
    full = {"summary": summary, "key": key, "rows": rows, "plain": plain}
    (out / f"advice_compare_{TODAY}.json").write_text(json.dumps(full, indent=1, default=str))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
