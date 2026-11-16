"""The router on held-out questions: does each question reach the right place?

`router_set.json` holds 152 questions written after the router was built and never used to tune it
(112 of ours across every route, intent and question type, in three languages, with follow-ups,
typos, logging, reminders, medical and off-topic questions), plus 40 of PHIA's own. Labels were fixed
before any router saw them. Scored for each router: the action and lead expert (`decide`), the
question type, and the request intent; with latency and cost.

    PYTHONPATH=backend:eval python eval/router_eval.py              # keyword rule and Jev
    PYTHONPATH=backend:eval python eval/router_eval.py --llm        # also the LLM router (OpenAI)

Jev costs about $0.01 for the set; the LLM router about $0.10.
"""

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

from app.agent.llm import OpenAILLM, SpendLedger
from app.agent.router import JevRouter, KeywordRouter, LLMRouter, RouterError, decide
from app.config import settings

SET = Path(__file__).parent / "router_set.json"
SUMMARY = Path("eval/results/router_eval_summary.json")


def grade(item: dict, classification) -> dict:
    route = decide(classification)
    action_right = route.action in item["route"]
    if action_right and route.action == "expert" and item["experts"]:
        action_right = route.expert in item["experts"]
    out = {
        "route": action_right,
        "got": route.action if route.action != "expert" else f"expert:{route.expert}",
        "want": item["route"][0]
        if item["route"][0] != "expert"
        else f"expert:{'/'.join(item['experts'])}",
    }
    if item["types"]:
        out["type"] = classification.question_type in item["types"]
    if item["intent"]:
        out["intent"] = classification.intent.value == item["intent"]
    return out


def rate(rows: list[dict], key: str) -> dict:
    scored = [r[key] for r in rows if key in r]
    return {
        "right": sum(scored),
        "of": len(scored),
        "rate": round(sum(scored) / len(scored), 3),
    }


def run(name: str, router, items: list[dict]) -> dict:
    rows, latency, cost, failed = [], [], 0.0, 0
    for item in items:
        try:
            c = router.classify(item["q"], item["earlier"])
        except RouterError:
            failed += 1
            rows.append(
                {"route": False, "got": "failed", "want": "-", "source": item["source"]}
            )
            continue
        latency.append(c.latency_s)
        cost += c.cost_usd
        rows.append(grade(item, c) | {"source": item["source"], "q": item["q"]})
    wrong = Counter((r["want"], r["got"]) for r in rows if not r["route"])
    return {
        "route": rate(rows, "route"),
        "type": rate(rows, "type"),
        "intent": rate(rows, "intent"),
        "route_ours": rate([r for r in rows if r["source"] == "ours"], "route"),
        "route_phia": rate([r for r in rows if r["source"] == "phia"], "route"),
        "type_phia": rate([r for r in rows if r["source"] == "phia"], "type"),
        "failed": failed,
        "median_latency_s": round(statistics.median(latency), 3) if latency else None,
        "max_latency_s": round(max(latency), 3) if latency else None,
        "cost_usd": round(cost, 4),
        "route_mistakes": [f"{w} -> {g}: {n}" for (w, g), n in wrong.most_common()],
        "misrouted": [r["q"] for r in rows if not r["route"] and "q" in r],
        "type_wrong": [r["q"] for r in rows if r.get("type") is False],
        "intent_wrong": [r["q"] for r in rows if r.get("intent") is False],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--llm", action="store_true", help="also the LLM router (paid, OpenAI)"
    )
    args = parser.parse_args()
    items = json.loads(SET.read_text())["questions"]
    routers = {"keyword": KeywordRouter(), "jev": JevRouter.from_settings(settings)}
    if args.llm:
        routers["llm"] = LLMRouter(
            OpenAILLM.from_settings(settings, SpendLedger(cap_usd=0.5))
        )
    summary = {"questions": len(items)} | {
        n: run(n, r, items) for n, r in routers.items()
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
    for name in routers:
        s = summary[name]
        print(
            f"{name:8s} route {s['route']['right']}/{s['route']['of']} "
            f"type {s['type']['right']}/{s['type']['of']} "
            f"intent {s['intent']['right']}/{s['intent']['of']} "
            f"| PHIA route {s['route_phia']['rate']} type {s['type_phia']['rate']} "
            f"| median {s['median_latency_s']} s, ${s['cost_usd']}, failed {s['failed']}"
        )


if __name__ == "__main__":
    main()
