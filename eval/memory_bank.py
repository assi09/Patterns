"""A fresh memory set of 100 cases, worded by the large model and checked by code. Paid.

The memory evaluation (`memory_eval.py`) has been seen and partly tuned on. This set is new:
the large model writes each case from a description of its kind, with a short stem of the fact's
distinctive word ("pilat", "cycl") so a paraphrased card still matches; what passes is decided
by code from the stored memory and the reply, never from the generated text. Each case runs for
a fresh person, so nothing leaks between cases. Run from the repository root.

    PYTHONPATH=backend:eval .venv/bin/python eval/memory_bank.py generate
    PYTHONPATH=<code>/backend:eval .venv/bin/python eval/memory_bank.py run --sha <sha> --label main
    PYTHONPATH=backend:eval .venv/bin/python eval/memory_bank.py score
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

OUT = Path("data/eval/memory_bank_2026-11-23")
BANK = OUT / "bank.json"
CAP_USD = 0.90

KINDS = {
    "remember": (20, ("The person asks the app to remember one everyday fact about them (routine, "
                 "goal, preference, plan), each time in different words, politely or bluntly. "
                 'Fields: "message", "stem".')),
    "volunteered": (15, ("The person mentions one everyday fact about themselves in passing, as a "
                    "statement, without asking to remember it. "
                    'Fields: "message", "stem".')),
    "dont_save": (10, ("The person tells one everyday fact and, in the same message, asks that it "
                  'not be saved or kept. Fields: "message", "stem".')),
    "change": (15, ("The app already keeps one fact about the person; they now say it changed "
               "(no longer true, something else instead). 'kept' is the old fact in the third "
               "person, short ('They swim on Mondays.'); 'message' is what they say; 'stem' is "
               "from the NEW fact, a word the old fact does not contain. "
               'Fields: "kept", "message", "stem".')),
    "duplicate": (10, ("The app already keeps one fact ('kept', third person, short); the person "
                  "asks it to remember the same fact again in other words. "
                  'Fields: "kept", "message", "stem".')),
    "recall_kept": (10, ("The app keeps one fact ('kept', third person, short); the person asks, "
                    "with no earlier chat, what the app knows or remembers about them. "
                    'Fields: "kept", "message", "stem".')),
    "recall_chat": (10, ("'before': the person tells one everyday fact and asks that it not be "
                    "saved; 'message': a later question in the same chat asking what they said "
                    'about it. Fields: "before", "message", "stem".')),
    "forget": (10, ("The app keeps one fact ('kept', third person, short); the person asks it to "
               'forget or remove that fact. Fields: "kept", "message", "stem".')),
}  # fmt: skip
RULES = (
    "Write natural, varied messages as different real people would type them: different lengths, "
    "tones and phrasings, some casual, a few with small typos. Facts are everyday and made up, "
    "nothing medical. 'stem' is the first 4 to 6 letters of the fact's most distinctive word, "
    "lower case, so that any paraphrase of the fact keeps it ('pilat' for pilates, 'cycl' for "
    "cycling). Reply with JSON only."
)


def generate() -> None:
    import openai
    from app.config import settings

    key = settings.openai_api_key
    client = openai.OpenAI(api_key=getattr(key, "get_secret_value", lambda: key)())
    bank, cost = [], 0.0
    for kind, (count, task) in KINDS.items():
        reply = client.chat.completions.create(
            model=settings.openai_large_model,
            messages=[
                {"role": "system", "content": RULES},
                {
                    "role": "user",
                    "content": f'{count} items. {task} Return {{"items": [...]}}.',
                },
            ],
            response_format={"type": "json_object"},
        )
        items = json.loads(reply.choices[0].message.content)["items"][:count]
        bank += [
            {"id": f"{kind}-{i:02d}", "kind": kind} | item
            for i, item in enumerate(items)
        ]
        cost += reply.usage.prompt_tokens * 5e-6 + reply.usage.completion_tokens * 30e-6
    OUT.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"cap_usd": CAP_USD, "cases": bank}, sort_keys=True, indent=1)
    BANK.write_text(body)
    print(dict(Counter(c["kind"] for c in bank)), f"about ${cost:.4f}")
    print(f"sha256 {hashlib.sha256(body.encode()).hexdigest()}")


def seed(r, kind: str, text: str) -> None:
    from app.db import memory
    from app.db.session import session_scope

    now = datetime.now(UTC)
    with session_scope(r.engine) as db:
        fact = memory.propose_fact(db, r.me, kind, text, explicit=True, now=now)
        memory.decide_fact(db, r.me, fact.id, True, now)


def has(items, stem) -> bool:
    return any(stem in f["text"].casefold() for f in items)


def case(r, c: dict) -> tuple[bool, str]:
    """Runs one case for the person of `r`; (passed, why not)."""
    stem = c["stem"].casefold()
    if c.get("kept"):
        seed(r, "routine", c["kept"])
    cid = r.chat()
    if c.get("before"):
        r.ask(cid, c["before"], label=f"{c['id']} before")
    seen = r.ask(cid, c["message"], label=c["id"])
    if seen is None:
        return False, "no reply"
    page = r.memory()
    reply = seen.low
    waiting, kept = page["waiting"], page["kept"]
    kind = c["kind"]
    if kind in ("remember", "volunteered"):
        return has(waiting, stem) or has(kept, stem), "no card with the fact"
    if kind == "dont_save":
        return not (has(waiting, stem) or has(kept, stem)), "a card was made"
    if kind == "change":
        old_kept = any(f["text"] == c["kept"] for f in kept)
        return has(
            waiting, stem
        ) and old_kept, "no replacement card, or the old fact went"
    if kind == "duplicate":
        return "already" in reply and not has(
            waiting, stem
        ), "not said already kept, or a new card"
    if kind in ("recall_kept", "recall_chat"):
        return stem in reply, "the reply does not name the fact"
    if kind == "forget":
        forgets = any(f.get("forgets") for f in waiting)
        return forgets and any(
            f["text"] == c["kept"] for f in kept
        ), "no forget card, or removed"
    return False, "unknown kind"


def run(sha: str, label: str) -> None:
    import memory_eval as harness
    from app.agent.llm import OpenAILLM, SpendLedger
    from app.config import settings

    body = BANK.read_text()
    if hashlib.sha256(body.encode()).hexdigest() != sha:
        raise ValueError("The bank changed since it was frozen")
    out = OUT / f"{label}.jsonl"
    if out.exists():
        raise ValueError(
            f"{out} exists: a finished run is never rerun for a higher mark"
        )
    frozen = json.loads(body)
    settings.sentry_dsn = None
    settings.chat_daily_cap_per_user_usd = settings.chat_daily_cap_total_usd = 100.0
    ledger = SpendLedger(cap_usd=frozen["cap_usd"])
    llm = OpenAILLM.from_settings(settings, ledger)
    with out.open("w") as rows, (OUT / f"{label}_turns.jsonl").open("w") as turns:
        for c in frozen["cases"]:
            if ledger.spent_usd >= frozen["cap_usd"]:
                print("Stopped at the cap.")
                break
            r = harness.Run(llm, frozen["cap_usd"], turns)
            try:
                ok, why = case(r, c)
            except StopIteration:
                print("Stopped at the cap.")
                break
            rows.write(
                json.dumps(
                    {
                        "id": c["id"],
                        "kind": c["kind"],
                        "ok": ok,
                        "why": "" if ok else why,
                    }
                )
                + "\n"
            )
            rows.flush()
    print(f"{label}: ${ledger.spent_usd:.6f} spent")


def score() -> None:
    for path in sorted(OUT.glob("*.jsonl")):
        if path.stem.endswith("_turns"):
            continue
        rows = [json.loads(x) for x in path.read_text().splitlines()]
        by = Counter((r["kind"], r["ok"]) for r in rows)
        print(f"== {path.stem}: {sum(r['ok'] for r in rows)}/{len(rows)}")
        for kind in KINDS:
            n = by[kind, True] + by[kind, False]
            if n:
                print(f"  {kind:12} {by[kind, True]}/{n}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate")
    paid = sub.add_parser("run")
    paid.add_argument("--sha", required=True)
    paid.add_argument("--label", required=True)
    sub.add_parser("score")
    args = parser.parse_args()
    {"generate": generate, "score": score}.get(
        args.command, lambda: run(args.sha, args.label)
    )()


if __name__ == "__main__":
    main()
