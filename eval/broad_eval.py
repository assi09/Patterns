"""Broad questions on made-up people with a planted change: is the answer about what actually
changed most, across every area, with nothing ranked wrongly and no metric given as a cause?

Five people, 110 days each, changed in the last 14 days (or not at all). Each is asked 24 broad
questions in the person's own words, through the real router and model (the same `ask()` the app
runs): 12 to develop on (`--split dev`) and 12 held out (`--split heldout`), run once. Code grades
every answer:

- broad: the answer got the all-metric overview (the router sent it to a "change" or "why" path
  and the question names no metric);
- leads right: the first metric the answer names is the planted one (or a score built from it);
- no wrong "biggest": nothing but the overview's first change is called the biggest or main;
- no cause: no metric given as the reason for how they feel ("because you...");
- quiet person: with nothing planted, no change is claimed.

    PYTHONPATH=backend:eval python eval/broad_eval.py --split dev      # about $1.2
    PYTHONPATH=backend:eval python eval/broad_eval.py --split heldout  # about $1.2, once

Everything is made up, so questions and answers may be printed. Results go to `eval/results/`.
"""

import argparse
import json
import math
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.agent.ask import ask, default_router
from app.agent.llm import OpenAILLM, SpendLedger
from app.agent.verifier import MENTIONS, attributed, overstated, ranked_problems
from app.analysis.day import with_scores
from app.config import settings
from app.synthetic import Step, generate

START = date(2026, 7, 1)
DAYS = 110
END = START + timedelta(days=DAYS - 1)
ON = END - timedelta(days=13)
STOP_AT_USD = 3.0
HERE = Path(__file__).parent

# name -> (planted effects, the metrics an answer may lead with: the planted one and scores of it)
PEOPLE = {
    "activity_fell": (
        (Step("steps", ON, -5000.0), Step("sleep_minutes", ON, -12.0)),
        {"steps", "distance_km", "calories", "strain", "active_zone_minutes"},
    ),
    "recovery_fell": (
        (Step("resting_hr", ON, 6.0), Step("hrv_ms", ON, -15.0)),
        {"resting_hr", "hrv_ms", "recovery_score", "readiness"},
    ),
    "sleep_fell": (
        (Step("sleep_minutes", ON, -70.0),),
        {
            "sleep_minutes",
            "sleep_score",
            "time_in_bed",
            "light_sleep_minutes",
            "recovery_score",
        },
    ),
    "bedtime_later": (
        (Step("bedtime_hour", ON, 1.5),),
        {"bedtime_hour"},
    ),
    "nothing": ((), set()),
}
QUESTIONS = {
    "dev": [
        "What changed most lately?",
        "Anything different about me recently?",
        "How has my life been lately?",
        "Why do I feel tired?",
        "What's been going on with my body lately?",
        "Give me the big picture of the last two weeks",
        "Has anything changed?",
        "Why do I feel off lately?",
        "How am I doing?",
        "What stands out in my data recently?",
        "Why am I so drained this week?",
        "Summarise how I've been.",
    ],
    "heldout": [
        "What's the biggest change in my data lately?",
        "Is anything unusual going on with me?",
        "How have the last couple of weeks been?",
        "Why am I exhausted?",
        "What's new in my numbers?",
        "Any changes I should know about?",
        "Why do I feel sluggish recently?",
        "Overall, how's it going?",
        "What moved the most recently?",
        "Why have I been feeling low on energy?",
        "Tell me what changed lately",
        "How's everything looking?",
    ],
}
NOTHING_CLAIMED = re.compile(
    r"\b(no clear change|nothing (?:has )?changed|held steady|steady)\b", re.IGNORECASE
)


def first_metric(summary: str) -> str | None:
    """The metric the answer names first."""
    found = [
        (m.start(), metric)
        for metric, p in MENTIONS.items()
        if (m := p.search(summary))
    ]
    return min(found)[1] if found else None


def wilson(k: int, n: int) -> list[float] | None:
    if not n:
        return None
    z, p = 1.96, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 3), round(centre + half, 3)]


def grade(person: str, leads: set[str], result) -> dict:
    evidence = list(result.evidence.values())
    summary = result.summary or ""
    overview = [e for e in evidence if e.stats.get("overview")]
    top = [e.metrics[0] for e in overview if e.stats.get("overview_rank") == 1]
    claimed = [c for c in result.claims if c.kind == "change"]
    out = {
        "broad": bool(overview),
        "overview_top": top[0] if top else None,
        "first_metric": first_metric(summary),
        "wrong_biggest": bool(ranked_problems(summary, evidence)),
        "cause_wording": bool(attributed(summary)),
        # A change stated, unhedged, that no significant test in the answer's evidence shows.
        "overclaims": bool(overstated(summary, evidence)),
        "change_claims": sorted({c.metric for c in claimed if c.metric}),
    }
    if person == "nothing":
        out["quiet_ok"] = not claimed and not out["overclaims"]
    else:
        out["leads_right"] = out["first_metric"] in leads
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=QUESTIONS, required=True)
    parser.add_argument(
        "--first", type=int, default=None, help="only this many questions"
    )
    args = parser.parse_args()
    out = HERE / "results" / f"broad_eval_{args.split}_{datetime.now(UTC).date()}.jsonl"
    ledger = SpendLedger(cap_usd=STOP_AT_USD)
    llm = OpenAILLM.from_settings(settings, ledger)
    router = default_router(settings)
    frames = {
        name: with_scores(generate(START, DAYS, effects, seed=7).frame)
        for name, (effects, _) in PEOPLE.items()
    }
    rows = []
    questions = QUESTIONS[args.split][: args.first]
    for question in questions:
        for person, (_, leads) in PEOPLE.items():
            reply = ask(llm, router, frames[person], question, today=END)
            graded = grade(person, leads, reply.result)
            row = {
                "q": question,
                "person": person,
                "summary": reply.result.summary,
                **graded,
            }
            rows.append(row)
            ok = graded.get("leads_right", graded.get("quiet_ok"))
            print(
                f"{'ok ' if ok and graded['broad'] and not graded['wrong_biggest'] else 'BAD'} "
                f"{person:14s} broad={int(graded['broad'])} first={graded['first_metric']} "
                f"top={graded['overview_top']} | {question}"
            )
            with out.open("a") as handle:
                handle.write(json.dumps(row) + "\n")
    planted = [r for r in rows if r["person"] != "nothing"]
    quiet = [r for r in rows if r["person"] == "nothing"]

    def rate(group, key):
        k = sum(1 for r in group if r.get(key))
        return {
            "k": k,
            "n": len(group),
            "rate": round(k / len(group), 3) if group else None,
            "wilson_95": wilson(k, len(group)),
        }

    summary = {
        "split": args.split,
        "questions": len(questions),
        "answers": len(rows),
        "broad": rate(rows, "broad"),
        "leads_right": rate(planted, "leads_right"),
        "wrong_biggest": rate(rows, "wrong_biggest"),
        "cause_wording": rate(rows, "cause_wording"),
        "overclaims": rate(rows, "overclaims"),
        "quiet_ok": rate(quiet, "quiet_ok"),
        "cost_usd": round(ledger.spent_usd, 4),
    }
    (
        HERE / "results" / f"broad_eval_{args.split}_{datetime.now(UTC).date()}.json"
    ).write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
