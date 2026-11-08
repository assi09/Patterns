"""Does retrieval make answers better? The whole agent with and without it, on a made-up person.

Run from the repository root: `PYTHONPATH=backend python eval/rag_compare.py [--stop 1.4]`. Coaching
runs both ways three times; a general how-to runs three times with retrieval and once without, since
without it each one is a paid web search. Facts are checked by code; usefulness, and whether each
answer is supported by what it cites, by a small model that is not told which arm it is reading. A
shuffled sample goes to `eval/results/` for a person to read blind.
"""

import argparse
import json
import random
import re
import statistics
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from unittest import mock

from app import outside as outside_module
from app.agent import world
from app.agent.ask import ask, default_guard, default_router
from app.agent.context import ChatState
from app.agent.llm import Budget, OpenAILLM
from app.agent.retrieval import Retrieved
from app.agent.verifier import MEDICAL
from app.config import settings
from app.db.session import session_scope
from app.outside import FoodData, Outside
from chat_eval import database, person

HERE = Path(__file__).parent
STAMP = datetime.now(UTC).date().isoformat()
COACHING = [
    "How can I sleep better?",
    "What can I actually do in the hour before bed so I fall asleep easier?",
    "I have exams next week, how should I handle my sleep?",
    "I work night shifts, how should I plan my sleep around them?",
    "How can I recover faster after hard training?",
    "How can I get more steps in?",
    "What should I change about my evenings?",
    "How can I stop feeling so tired after lunch?",
    "How can I train smarter this month?",
    "give me 4 tips to sleep better",
]
HOW_TO = [
    ("How do I do a plank?", ("forearm", "toes", "body", "straight")),
    ("How do I do a barbell squat?", ("bar", "knees", "hips")),
    ("How much exercise should an adult get in a week?", ("150", "minutes")),
    ("How much protein do adults need a day?", ("protein", "gram")),
    ("How long should a nap be before a night shift?", ("nap", "minute", "hour")),
    (
        "What's the difference between moderate and vigorous exercise?",
        ("talk", "intensity", "heart"),
    ),
    ("How do I stretch my hamstrings?", ("leg", "stretch")),
    ("How do I get over jet lag?", ("light", "time", "sleep")),
    ("Which foods are high in fibre?", ("grain", "fruit", "bean", "vegetable")),
    ("How do I do a Romanian deadlift?", ("hips", "bar", "back")),
]
JUDGE = """You grade one reply from a health-tracker assistant. You are shown what it could cite.
Return JSON only: {"useful": 1-5, "specific": 1-5, "supported": 0|1}. useful: would this actually
help the person do something? specific: 5 is concrete steps or their own numbers, 1 is a tip anyone
could read anywhere. supported: 1 if every factual statement is backed by the material shown or by
the person's data described there, 0 if it adds things that are not."""


def grade(llm, question, text, material, spent):
    budget = Budget(max_calls=1, max_cost_usd=0.01)
    try:
        done = llm.complete(
            [
                {"role": "system", "content": JUDGE},
                {
                    "role": "user",
                    "content": f"Asked: {question}\nMaterial: {material[:3500]}\nReply: {text}",
                },
            ],
            budget=budget,
        )
        spent[0] += budget.cost_usd
        raw = done.text or "{}"
        return json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    except Exception:
        return {}


def run_one(llm, router, guard, frame, outside, now, question, on):
    profile = ("Works night shifts",) if "night shifts" in question else ()
    arguments = dict(
        today=now, now=now, guard=guard, outside=outside, chat=ChatState(profile=profile)
    )
    if on:
        return ask(llm, router, frame, question, **arguments)
    with mock.patch.object(world, "search", lambda *a, **k: Retrieved()):
        return ask(llm, router, frame, question, guidance_mode="none", **arguments)


def row_for(reply, question, kind, arm, repeat, llm, spent, words=()):
    result = reply.result
    text = " ".join([result.summary, *result.notes])
    passages = [e for e in result.evidence.values() if e.tool == "knowledge"]
    cited = {i for c in result.claims for i in c.evidence_ids}
    material = " ".join(
        f"{e.tool}: {json.dumps(e.stats, default=str)[:700]}"
        for e in result.evidence.values()
        if e.id in cited or e.tool == "knowledge"
    )
    jev = sum(s.get("cost_usd") or 0 for s in result.trace if s.get("type") == "route")
    cost = result.budget.cost_usd + jev
    spent[0] += cost
    row = {
        "kind": kind,
        "arm": arm,
        "repeat": repeat,
        "q": question,
        "a": result.summary,
        "notes": result.notes,
        "type": reply.route.classification.question_type,
        "stop": result.stop_reason,
        "calls": result.budget.calls,
        "cost": round(cost, 5),
        "cites_passage": any(e.id in cited for e in passages),
        "searched_web": any(s.get("type") == "web_lookup" for s in result.trace),
        "no_answer": bool(re.search(r"couldn't|can't look|pin that down|don't see anything", text)),
        "own_numbers": bool(re.search(r"\d", result.summary)),
        "medical": bool(MEDICAL.search(text)),
        "words": any(w in text.lower() for w in words) if words else None,
        "kinds": [c.kind for c in result.claims],
    }
    row["grade"] = grade(llm, question, result.summary, material, spent)
    return row


def mean(rows, key):
    values = [r["grade"][key] for r in rows if key in r.get("grade", {})]
    return round(statistics.mean(values), 2) if values else None


def share(rows, key):
    return round(sum(bool(r[key]) for r in rows) / len(rows), 2) if rows else None


def main():
    outside_module.WEB_PER_DAY = 1000  # the arm without retrieval makes one search per question
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", type=float, default=1.4)
    parser.add_argument("--only", default="", help="coaching or how_to")
    parser.add_argument("--tag", default="")
    options = parser.parse_args()
    stop, tag = options.stop, options.tag
    llm = OpenAILLM.from_settings(settings)
    router, guard, frame = default_router(settings), default_guard(settings), person()
    engine, user_id = database()
    now = datetime.combine(frame.index.max().date() + timedelta(days=1), time(9), UTC)

    def sessions():
        return session_scope(engine)

    def outside():
        start = now.replace(hour=0)
        return Outside(sessions, user_id, now, start, FoodData.from_settings(settings))

    spent, rows = [0.0], []
    out = HERE / "results" / f"rag_compare_{STAMP}{tag}.jsonl"
    plan = [("coaching", q, (), arm, r) for q in COACHING for arm in (1, 0) for r in range(3)]
    plan += [("how_to", q, w, 1, r) for q, w in HOW_TO for r in range(3)]
    plan += [("how_to", q, w, 0, 0) for q, w in HOW_TO]
    plan = [step for step in plan if not options.only or step[0] == options.only]
    with out.open("w") as file:
        for kind, question, words, arm, repeat in plan:
            if spent[0] >= stop:
                print("Stopped at the spending limit.")
                break
            try:
                reply = run_one(llm, router, guard, frame, outside(), now, question, bool(arm))
            except Exception as error:
                print("failed:", type(error).__name__, str(error)[:150])
                if "quota" in str(error).lower() or "credit" in str(error).lower():
                    break
                continue
            name = "on" if arm else "off"
            row = row_for(reply, question, kind, name, repeat, llm, spent, words)
            rows.append(row)
            file.write(json.dumps(row, default=str) + "\n")
            file.flush()
            print(f"${spent[0]:.3f} {kind}/{name}#{repeat} {row['stop']} {question[:45]}")
    groups = defaultdict(list)
    for row in rows:
        groups[(row["kind"], row["arm"])].append(row)
    summary = {
        "spent_usd": round(spent[0], 4),
        "answers": len(rows),
        "arms": {
            f"{kind}/{arm}": {
                "answers": len(group),
                "useful": mean(group, "useful"),
                "specific": mean(group, "specific"),
                "supported": mean(group, "supported"),
                "cites_passage": share(group, "cites_passage"),
                "no_answer": share(group, "no_answer"),
                "own_numbers": share(group, "own_numbers"),
                "medical_words": share(group, "medical"),
                "searched_web": share(group, "searched_web"),
                "words_found": share([r for r in group if r["words"] is not None], "words"),
                "mean_cost": round(statistics.mean(r["cost"] for r in group), 5),
                "mean_calls": round(statistics.mean(r["calls"] for r in group), 2),
            }
            for (kind, arm), group in sorted(groups.items())
        },
    }
    (HERE / "results" / f"rag_compare_{STAMP}{tag}.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    if options.only:
        return
    blind = random.Random(7)
    lines, key = ["# Which answer is better? (made-up person)\n"], {}
    for at, question in enumerate(COACHING[:8] + [q for q, _ in HOW_TO[:4]], 1):
        pair = {r["arm"]: r for r in rows if r["q"] == question and r["repeat"] == 0}
        if len(pair) < 2:
            continue
        order = ["on", "off"]
        blind.shuffle(order)
        key[at] = {"A": order[0], "B": order[1]}
        lines.append(
            f"\n## {at}. {question}\n\n**A.** {pair[order[0]]['a']}\n\n"
            f"**B.** {pair[order[1]]['a']}\n"
        )
    (HERE / "results" / f"rag_blind_{STAMP}.md").write_text("".join(lines))
    (HERE / "results" / f"rag_blind_key_{STAMP}.json").write_text(json.dumps(key, indent=1))


if __name__ == "__main__":
    main()
