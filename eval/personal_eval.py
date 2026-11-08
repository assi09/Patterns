"""Is advice personal? The same questions for different made-up people, compared.

Run from the repository root: `PYTHONPATH=backend:eval python eval/personal_eval.py [--stop 0.35]`.
Each answer must use what this person told the app, must not mention another person's details, and
must suit their life (no clock-time bedtime for someone on nights). With nothing known, it should
say the advice is general and ask one question.
"""

import argparse
import json
import re
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from chat_eval import person

from app.agent.ask import ask, default_guard, default_router
from app.agent.context import ChatState
from app.agent.llm import OpenAILLM
from app.agent.verifier import MEDICAL
from app.config import settings

HERE = Path(__file__).parent
STAMP = datetime.now(UTC).date().isoformat()
PEOPLE = {
    "nights": (("Works night shifts as a nurse",), ("night shift", "shift", "nurse"), None),
    "student": (
        ("Has university exams next week", "Studies late in the library"),
        ("exam", "study", "library"),
        None,
    ),
    "parent": (
        ("Has a newborn at home", "Wakes in the night to feed the baby"),
        ("baby", "newborn", "feed"),
        None,
    ),
    "lifter": (
        ("Trains with weights four days a week", "Wants to build muscle"),
        ("weights", "muscle", "lift", "training"),
        None,
    ),
    "unknown": ((), (), None),
}
QUESTIONS = [
    "How do I eat better?",
    "How can I sleep better?",
    "How can I have more energy during the day?",
    "How much protein do I need?",
    "How should I plan my evenings?",
]
CLOCK = re.compile(r"\b(?:2[0-3]|[01]?\d):[0-5]\d\b|\b\d{1,2} ?pm\b", re.IGNORECASE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", type=float, default=0.35)
    parser.add_argument("--questions", default="", help="indexes, such as 0,3,4")
    options = parser.parse_args()
    stop = options.stop
    chosen = [int(i) for i in options.questions.split(",") if i] or range(len(QUESTIONS))
    llm = OpenAILLM.from_settings(settings)
    router, guard, frame = default_router(settings), default_guard(settings), person()
    now = datetime.combine(frame.index.max().date() + timedelta(days=1), time(9), UTC)
    spent, rows = 0.0, []
    out = HERE / "results" / f"personal_eval_{STAMP}.jsonl"
    with out.open("w") as file:
        for question in [QUESTIONS[i] for i in chosen]:
            for name, (profile, own, _) in PEOPLE.items():
                if spent >= stop:
                    print("Stopped at the limit.")
                    break
                reply = ask(
                    llm,
                    router,
                    frame,
                    question,
                    today=now,
                    now=now,
                    guard=guard,
                    chat=ChatState(profile=profile),
                )
                result = reply.result
                jev = sum(s.get("cost_usd") or 0 for s in result.trace if s.get("type") == "route")
                spent += result.budget.cost_usd + jev
                text = result.summary.lower()
                others = [
                    w
                    for n, (_, ws, _) in PEOPLE.items()
                    if n != name
                    for w in ws
                    if w not in own and w not in ("shift", "training")
                ]
                held = {e.id: e for e in result.evidence.values()}
                cited = {i for c in result.claims for i in c.evidence_ids}
                row = {
                    "person": name,
                    "q": question,
                    "a": result.summary,
                    "notes": result.notes,
                    "type": reply.route.classification.question_type,
                    "expert": result.expert,
                    "action": reply.route.action,
                    "stop": result.stop_reason,
                    "kinds": [c.kind for c in result.claims],
                    "uses_them": any(w in text for w in own) if own else None,
                    "leaks": [w for w in others if re.search(rf"\b{w}", text)],
                    "cites_memory": any(held[i].tool == "memory" for i in cited if i in held),
                    "cites_passage": any(held[i].tool == "knowledge" for i in cited if i in held),
                    "clock_time": bool(CLOCK.search(result.summary)),
                    "medical": bool(MEDICAL.search(result.summary)),
                    "asks": "?" in result.summary,
                    "cost": round(result.budget.cost_usd + jev, 5),
                }
                rows.append(row)
                file.write(json.dumps(row) + "\n")
                file.flush()
                print(f"${spent:.3f} {name}: {question}")
    known = [r for r in rows if r["person"] != "unknown" and r["action"] != "refuse"]
    unknown = [r for r in rows if r["person"] == "unknown" and r["action"] != "refuse"]
    summary = {
        "spent_usd": round(spent, 4),
        "answers": len(rows),
        "refused": sum(r["action"] == "refuse" for r in rows),
        "uses_what_they_said": f"{sum(bool(r['uses_them']) for r in known)}/{len(known)}",
        "cites_memory": f"{sum(r['cites_memory'] for r in known)}/{len(known)}",
        "cites_passage": f"{sum(r['cites_passage'] for r in rows)}/{len(rows)}",
        "leaked_another_person": sum(bool(r["leaks"]) for r in rows),
        "night_worker_given_a_clock_time": sum(
            r["clock_time"] for r in known if r["person"] == "nights"
        ),
        "unknown_person_asks_a_question": f"{sum(r['asks'] for r in unknown)}/{len(unknown)}",
        "medical_words": sum(r["medical"] for r in rows),
        "no_answer": sum(r["stop"] not in ("submitted",) for r in rows),
    }
    (HERE / "results" / f"personal_eval_{STAMP}.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
