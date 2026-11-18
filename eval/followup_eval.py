"""Follow-ups after the independent audit (2026-11-18): does each answer use the days, metric,
comparison and topic the conversation means?

Graded by code from what the agent actually computed, not from the numbers in its reply: two days
with the same value would pass a number check on the wrong day. A data turn passes when some
evidence of the run is about one of the expected metrics **over exactly the expected days**; a
question that stands on its own passes when it did **not** reuse the earlier days; a reference that
cannot be resolved passes when the person is asked; a how-to follow-up passes when the lookup is
about the topic; a count passes when it used the stated comparison and code's own count.

Two sets, through the real router and model (`ask()`, as the app runs it), on one made-up person:

- `regression`: the audit's own made-up conversations (the ones it judged), for before and after;
- `heldout`: new conversations written before any was run, run once, the number to report.

    PYTHONPATH=backend:eval python eval/followup_eval.py --split regression   # about $0.25
    PYTHONPATH=backend:eval python eval/followup_eval.py --split heldout      # about $0.30, once
"""

import argparse
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from app.agent.ask import ask, default_guard, default_router
from app.agent.context import Turn
from app.agent.llm import OpenAILLM, SpendLedger
from app.analysis.day import with_scores
from app.analysis.habits import COMPARISONS
from app.config import settings
from app.db.session import session_scope
from app.outside import FoodData, Outside
from app.synthetic import generate
from chat_eval import database

HERE = Path(__file__).parent
START = date(2026, 5, 23)
DAYS = 180
NOW = datetime(2026, 11, 18, 20, tzinfo=UTC)
TODAY = NOW.date()
STOP_AT_USD = 1.5


def d(text: str) -> date:
    return date.fromisoformat(text)


# Each turn: (question, what to check or None for context only).
#   {"days": (start, end), "metrics": [...]}    the evidence covers exactly those days
#   {"not_days": (start, end)}                  it did not reuse those days
#   {"asks": True}                              it asked which days or thing was meant
#   {"topic": "plank"}                          the lookup or answer is about that
#   {"count": (metric, value, comparison, start, end)}   counted with that comparison
#   {"reply": "No. What your data shows"}       a fixed reply
ALL = (START, TODAY)
CONVERSATIONS = {
    "regression": {
        "daily-reference": [
            (
                "How many steps did I take yesterday?",
                {"days": ("2026-11-17",) * 2, "metrics": ["steps"]},
            ),
            (
                "And the day before that?",
                {"days": ("2026-11-16",) * 2, "metrics": ["steps"]},
            ),
            (
                "How long did I sleep on that same day? Give hours and minutes.",
                {"days": ("2026-11-16",) * 2, "metrics": ["sleep_minutes"]},
            ),
            (
                "Actually I meant yesterday. How much sleep was it?",
                {"days": ("2026-11-17",) * 2, "metrics": ["sleep_minutes"]},
            ),
            (
                "And how much deep sleep did I get that same night?",
                {"days": ("2026-11-17",) * 2, "metrics": ["deep_sleep_minutes"]},
            ),
        ],
        "aggregate-followups": [
            (
                "Give my total steps from 2026-11-11 through 2026-11-17, inclusive.",
                {"days": ("2026-11-11", "2026-11-17"), "metrics": ["steps"]},
            ),
            (
                "What was the daily average for exactly those dates?",
                {"days": ("2026-11-11", "2026-11-17"), "metrics": ["steps"]},
            ),
            (
                "And the median, rather than the average?",
                {"days": ("2026-11-11", "2026-11-17"), "metrics": ["steps"]},
            ),
            (
                "How many of those days were strictly above 10,000 steps?",
                {"count": ("steps", 10_000, "above", "2026-11-11", "2026-11-17")},
            ),
        ],
        "calendar-and-history": [
            (
                "What are my total REM sleep minutes across all available history?",
                {"days": ALL, "metrics": ["rem_sleep_minutes"]},
            ),
            (
                "For that same history, give the average REM minutes per recorded night instead.",
                {"days": ALL, "metrics": ["rem_sleep_minutes"]},
            ),
        ],
        "multipart": [
            (
                (
                    "For 2026-11-11 to 2026-11-17 inclusive, give total steps, average sleep minutes, "
                    "and average resting heart rate. Label all three."
                ),
                {
                    "days": ("2026-11-11", "2026-11-17"),
                    "metrics": ["steps", "sleep_minutes", "resting_hr"],
                },
            ),
            (
                "Just the sleep average from that answer, in minutes, one sentence please.",
                {"days": ("2026-11-11", "2026-11-17"), "metrics": ["sleep_minutes"]},
            ),
        ],
        "guidance-followup": [
            (
                "How do I do a basic plank? Give the source for the instructions.",
                {"topic": "plank"},
            ),
            ("What should I do with my hips during it?", {"topic": "plank"}),
        ],
        "relationships": [
            (
                (
                    "Over 2026-08-20 to 2026-11-17, does more time asleep go with higher HRV? What is "
                    "the association, not a cause?"
                ),
                None,
            ),
            (
                "Can you tell me it definitely causes it?",
                {"reply": "No. What your data shows"},
            ),
        ],
        "strict-count": [
            (
                (
                    "Between 2026-11-11 and 2026-11-17, how many days had strictly more than 11,000 "
                    "steps, not counting a day exactly equal?"
                ),
                {"count": ("steps", 11_000, "above", "2026-11-11", "2026-11-17")},
            ),
        ],
        "coworker": [
            (
                "How did my coworker sleep yesterday?",
                {"reply": "I can only see your own"},
            ),
            (
                "My coworker visited yesterday. How many steps did I take yesterday?",
                {"days": ("2026-11-17",) * 2, "metrics": ["steps"]},
            ),
        ],
    },
    # Written on 2026-11-18 before any of it was run; run once.
    "heldout": {
        "distance-week": [
            (
                "What was my total distance from Nov 3 to Nov 9?",
                {"days": ("2026-11-03", "2026-11-09"), "metrics": ["distance_km"]},
            ),
            (
                "And the average per day over those days?",
                {"days": ("2026-11-03", "2026-11-09"), "metrics": ["distance_km"]},
            ),
            (
                "What about the median?",
                {"days": ("2026-11-03", "2026-11-09"), "metrics": ["distance_km"]},
            ),
            (
                "What's my average resting heart rate?",
                {"not_days": ("2026-11-03", "2026-11-09")},
            ),
        ],
        "one-night": [
            (
                "How long did I sleep on Nov 12?",
                {"days": ("2026-11-12",) * 2, "metrics": ["sleep_minutes"]},
            ),
            (
                "And my HRV that same night?",
                {"days": ("2026-11-12",) * 2, "metrics": ["hrv_ms"]},
            ),
            (
                "And the night before that?",
                {"days": ("2026-11-11",) * 2, "metrics": ["hrv_ms"]},
            ),
            (
                "How many steps did I take that day?",
                {"days": ("2026-11-11",) * 2, "metrics": ["steps"]},
            ),
        ],
        "other-metric-same-days": [
            (
                "My average steps from 2026-10-26 to 2026-11-01?",
                {"days": ("2026-10-26", "2026-11-01"), "metrics": ["steps"]},
            ),
            (
                "What was my average calories burned over those same dates?",
                {"days": ("2026-10-26", "2026-11-01"), "metrics": ["calories"]},
            ),
            (
                "And the highest day for calories in that period?",
                {"days": ("2026-10-26", "2026-11-01"), "metrics": ["calories"]},
            ),
        ],
        "new-period-wins": [
            (
                "Total active zone minutes from 2026-11-01 to 2026-11-07?",
                {
                    "days": ("2026-11-01", "2026-11-07"),
                    "metrics": ["active_zone_minutes"],
                },
            ),
            (
                "And the total from 2026-11-08 to 2026-11-14?",
                {
                    "days": ("2026-11-08", "2026-11-14"),
                    "metrics": ["active_zone_minutes"],
                },
            ),
        ],
        "counts": [
            (
                "From 2026-11-01 to 2026-11-14, how many days had more than 9,000 steps?",
                {"count": ("steps", 9_000, "above", "2026-11-01", "2026-11-14")},
            ),
            (
                "And how many of those days had at least 9,000?",
                {"count": ("steps", 9_000, "at_least", "2026-11-01", "2026-11-14")},
            ),
            (
                "How many nights in that period did I sleep less than 7 hours?",
                {"count": ("sleep_minutes", 420, "below", "2026-11-01", "2026-11-14")},
            ),
        ],
        "squat-then-lunge": [
            ("How do I do a bodyweight squat?", {"topic": "squat"}),
            ("Where should my knees point during it?", {"topic": "squat"}),
            ("And how do I do a lunge?", {"topic": "lunge"}),
        ],
        "nothing-to-refer-to": [
            ("What was my average over those dates?", {"asks": True}),
        ],
        "neighbour-and-cause": [
            (
                "How many steps did my neighbour take last week?",
                {"reply": "I can only see your own"},
            ),
            (
                "Over 2026-09-01 to 2026-11-17, do my steps go with my sleep?",
                None,
            ),
            ("So do my steps cause it?", {"reply": "No. What your data shows"}),
        ],
    },
}


def person():
    return with_scores(generate(START, DAYS, (), seed=5).frame)


def covers(evidence, metrics, start: date, end: date) -> bool:
    return any(
        metric in e.metrics and any((w.start, w.end) == (start, end) for w in e.windows)
        for e in evidence
        for metric in metrics
    )


def grade(
    check: dict, result, frame, before: set[str] = frozenset()
) -> tuple[bool, str]:
    """`before` is the evidence earlier turns already had: re-attached so it can be cited, it is
    not what this turn computed, so "did not reuse the days" looks only at what it computed (the
    held-out run of 2026-11-18 counted it, failing a right answer)."""
    evidence = list(result.evidence.values())
    computed = [e for e in evidence if e.id not in before]
    summary = result.summary or ""
    if "days" in check:
        start, end = (
            map(d, check["days"])
            if isinstance(check["days"][0], str)
            else check["days"]
        )
        ok = covers(evidence, check["metrics"], start, end)
        seen = sorted(
            {
                f"{m}:{w.start}..{w.end}"
                for e in evidence
                for m in e.metrics[:1]
                for w in e.windows[:1]
            }
        )
        return ok, "; ".join(seen[:6])
    if "not_days" in check:
        start, end = map(d, check["not_days"])
        reused = any(
            any((w.start, w.end) == (start, end) for w in e.windows) for e in computed
        )
        return bool(
            computed
        ) and not reused, f"{len(computed)} computed, reused={reused}"
    if "asks" in check:
        return summary.startswith("Which"), summary[:80]
    if "topic" in check:
        said = (summary + json.dumps(result.trace, default=str)).lower()
        return check["topic"] in said, summary[:80]
    if "reply" in check:
        return summary.startswith(check["reply"]), summary[:80]
    if "count" in check:
        metric, value, comparison, start, end = check["count"]
        days = frame.loc[start:end, metric].dropna()
        want = int(COMPARISONS[comparison](days, value).sum())
        counts = [
            e for e in evidence if e.tool == "goal_progress" and metric in e.metrics
        ]
        ok = any(
            e.stats.get("direction") == comparison and e.stats.get("days_met") == want
            for e in counts
        )
        got = [(e.stats.get("direction"), e.stats.get("days_met")) for e in counts]
        return ok, f"want {comparison} {want}, got {got}"
    raise ValueError(check)


def wilson(k: int, n: int) -> list[float] | None:
    if not n:
        return None
    z, p = 1.96, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 3), round(centre + half, 3)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=CONVERSATIONS, required=True)
    args = parser.parse_args()
    frame = person()
    ledger = SpendLedger(cap_usd=STOP_AT_USD)
    llm, router, guard = (
        OpenAILLM.from_settings(settings, ledger),
        default_router(settings),
        default_guard(settings),
    )
    engine, user_id = database()
    outside = Outside(
        lambda: session_scope(engine),
        user_id,
        NOW,
        NOW - timedelta(hours=1),
        FoodData.from_settings(settings),
    )
    out = HERE / "results" / f"followup_eval_{args.split}_{TODAY}.jsonl"
    out.write_text("")
    rows = []
    for name, turns in CONVERSATIONS[args.split].items():
        history: list[Turn] = []
        stored: dict = {}
        for question, check in turns:
            before = set(stored)
            reply = ask(
                llm,
                router,
                frame,
                question,
                today=NOW,
                now=NOW,
                history=history,
                stored_evidence=stored,
                guard=guard,
                outside=outside,
            )
            result = reply.result
            stored |= result.evidence
            claims = tuple(
                {"text": c.text, "kind": c.kind, "evidence_ids": list(c.evidence_ids)}
                for c in result.claims
            )
            history.append(
                Turn(
                    question,
                    result.summary or "",
                    claims=claims,
                    answered_by=result.expert,
                    at=NOW,
                )
            )
            if check is None:
                continue
            ok, seen = grade(check, result, frame, before)
            row = {
                "conversation": name,
                "q": question,
                "check": check,
                "ok": ok,
                "seen": seen,
                "summary": result.summary,
            }
            rows.append(row)
            print(
                f"{'ok ' if ok else 'BAD'} {name:24s} | {question[:60]} | {seen[:90]}"
            )
            with out.open("a") as handle:
                handle.write(json.dumps(row, default=str) + "\n")
    passed = sum(r["ok"] for r in rows)
    summary = {
        "split": args.split,
        "graded_turns": len(rows),
        "passed": passed,
        "rate": round(passed / len(rows), 3),
        "wilson_95": wilson(passed, len(rows)),
        "cost_usd": round(ledger.spent_usd, 4),
    }
    (HERE / "results" / f"followup_eval_{args.split}_{TODAY}.json").write_text(
        json.dumps(summary, indent=1) + "\n"
    )
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
