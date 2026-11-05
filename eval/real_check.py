"""The real agent on the owner's real data, from the Takeout export on this machine.

Run from the repository root: `PYTHONPATH=backend python eval/real_check.py`, optionally with
questions as arguments. Calls OpenAI and Jev, about $0.01 a question.

Real health values must not reach git or a chat, so answers go only to `data/real_run.md`, which is
git-ignored, and this prints counts: what the agent did, never what it found. Read the file yourself.
"""

import sys
from datetime import UTC, datetime, time
from pathlib import Path

from app.agent.ask import ask, default_guard, default_router
from app.agent.llm import OpenAILLM
from app.agent.verifier import GENERIC_ADVICE, MEDICAL
from app.analysis.day import with_scores
from app.config import settings
from app.ingest.takeout import load_daily

QUESTIONS = (
    "How did I sleep last night?",
    "Has my sleep changed lately?",
    "Why has my recovery been what it has?",
    "Do I go to bed later on weekends?",
    "How can I sleep better?",
    "How can I recover faster?",
)
OUT = Path("data/real_run.md")


def main() -> None:
    questions = sys.argv[1:] or QUESTIONS
    frame = with_scores(load_daily(settings.export_dir, settings.timezone).frame)
    last = frame.index.max().date()
    moment = datetime.combine(last, time(20), UTC)  # the export's last day counts as today
    llm, router, guard = (
        OpenAILLM.from_settings(settings),
        default_router(settings),
        default_guard(settings),
    )
    lines = [f"# Real run, {datetime.now(UTC):%Y-%m-%d %H:%M} UTC\n", f"Data up to {last}.\n"]
    total = 0.0
    print(f"{len(frame)} days of data, {(datetime.now(UTC).date() - last).days} days old")
    for question in questions:
        reply = ask(llm, router, frame, question, today=moment, now=moment, guard=guard)
        result = reply.result
        total += result.budget.cost_usd
        checks = [s for s in result.trace if s.get("type") == "verify"]
        tools = [s["name"] for s in result.trace if s.get("type") == "tool"]
        fell_back = bool(checks and checks[-1].get("summary_problems"))
        text = " ".join([result.summary, *result.notes])
        kinds = [claim.kind for claim in result.claims]
        lines += [
            f"## {question}\n",
            f"{text}\n",
            *(f"- {claim.kind}: {claim.text}" for claim in result.claims),
            f"\n*{reply.route.expert or reply.route.action}, "
            f"{reply.route.classification.question_type}, tools: {', '.join(tools) or 'none'}*\n",
        ]
        print(
            f"{question}\n  {reply.route.action}/{reply.route.expert} "
            f"{reply.route.classification.question_type} stop={result.stop_reason} "
            f"calls={result.budget.calls} tools={len(tools)} ${result.budget.cost_usd:.4f}\n"
            f"  claims={len(result.claims)} rejected={len(result.rejected)} "
            f"suggestions={kinds.count('suggestion')} fell_back={fell_back} "
            f"generic={bool(GENERIC_ADVICE.search(text))} medical={bool(MEDICAL.search(text))}"
        )
    OUT.write_text("\n".join(lines))
    print(f"total ${total:.4f}; answers in {OUT}")


if __name__ == "__main__":
    main()
