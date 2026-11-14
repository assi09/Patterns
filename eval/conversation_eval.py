"""Whole conversations through the real chat API, on a synthetic person: is every reply sound?

Run from the repository root: `PYTHONPATH=backend python eval/conversation_eval.py [names...]`.
Calls OpenAI and Jev (the router and the advice guard), about $0.8 for the whole set, and stops by
itself at `STOP_AT_USD`. Names run only those conversations (a rerun of what failed).

Everything goes through `POST /chat` as the app sends it, so routing, the follow-up rewrite, the
chat's history, memory cards and the listener are all in play. Each turn is checked by code
(`conversation_set.json` says what each should get) and read by a small-model judge for whether it
is sound, uses what the person said, and sounds like a person. Everything is made up, so replies
may be printed. Results go to `eval/results/`, written as it goes.
"""

import json
import re
import sys
import tempfile
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from alembic import command
from alembic.config import Config
from app.agent.ask import default_guard, default_router
from app.agent.llm import Budget, LLMError, OpenAILLM, SpendLedger
from app.agent.verifier import DAY_MONTH, ISO_DATE, MEDICAL, MONTH_DAY
from app.api import auth, chat
from app.api.chat import AgentParts
from app.api.main import create_app
from app.api.store import analyze, get_data
from app.config import settings
from app.db.models import AnswerTrace, User
from app.db.session import session_scope
from app.ingest.takeout import DailyData
from app.synthetic import generate
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

STOP_AT_USD = 1.4
HERE = Path(__file__).parent
TODAY = datetime.now(UTC).date()
OUT = HERE / "results" / f"conversation_eval_{TODAY}.jsonl"
SUMMARY = HERE / "results" / f"conversation_eval_{TODAY}.json"
PASSWORD = "synthetic person only"

# What no reply should do, whatever the turn.
WEAR = re.compile(r"\b(?:wear time|low[- ]wear|data coverage)\b", re.IGNORECASE)
RECITES = re.compile(r"\byou(?:'ve| have) kept\b|\byou often look at\b", re.IGNORECASE)
FIGURE = re.compile(r"\d")
ABOUT_ME = re.compile(r"\b(?:know|remember) about me\b", re.IGNORECASE)
KINDS = {
    "chat": {"chatted", "chat_fallback"},
    "refuse": {"refused"},
    "noted": {"noted"},
    "clarify": {"clarification"},
}

JUDGE = """You grade one reply from a health-data chat assistant to a person, given the \
conversation before it. The assistant reads the person's Fitbit data; it must never be medical; \
it may coach everyday habits from their own data; numbers in its replies were checked against \
computed evidence, so do not judge whether figures are true.

Score each from 1 (bad) to 5 (excellent):
- sound: does it answer what was actually asked (or respond sensibly to what was said), \
logically, without non sequiturs, irrelevant statistics or contradictions?
- context: does it use what the person said earlier in the conversation where that matters? \
5 when nothing earlier matters.
- natural: does it sound like a warm, sharp person rather than a robotic report?
Then name the main problem in a few words, or "none".

Reply with JSON only: {"sound": n, "context": n, "natural": n, "problem": "..."}"""


def person():
    """121 days ending today, with last night short, as in the conversation that prompted this."""
    start = TODAY - timedelta(days=120)
    frame = generate(start, 121, seed=21).frame
    rng = np.random.default_rng(5)
    frame["bedtime_hour"] = -0.5 + rng.normal(0, 0.9, len(frame))
    frame.loc[frame.index[-1], "sleep_minutes"] = 318.0
    frame.loc[frame.index[-1], "minutes_in_bed"] = 345.0
    return frame


def app_for(engine, llm):
    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    data = analyze(DailyData(frame=person()), datetime.now(UTC))
    parts = AgentParts(
        llm, default_router(settings), default_guard(settings), background=True
    )
    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[get_data] = lambda: data
    app.dependency_overrides[chat.get_agent] = lambda: parts
    app.dependency_overrides[chat.get_sessions] = lambda: lambda: session_scope(engine)
    return TestClient(app)


def database():
    url = f"sqlite:///{tempfile.mkdtemp()}/conversations.db"
    config = Config("backend/alembic.ini")
    config.set_main_option("script_location", "backend/migrations")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


def sign_in(client, engine) -> dict:
    email = "synthetic@example.com"
    token = client.post(
        "/auth/signup", json={"email": email, "password": PASSWORD}
    ).json()["token"]
    with session_scope(engine) as db:
        db.scalar(select(User).where(User.email == email)).status = "approved"
    return {"Authorization": f"Bearer {token}"}


def judge(llm, history: list[tuple[str, str]], message: str, reply: str) -> dict:
    before = "\n".join(f"Person: {q}\nAssistant: {a}" for q, a in history) or "(none)"
    task = (
        f"Conversation before:\n{before}\n\nPerson: {message}\nReply to grade:\n{reply}"
    )
    try:
        done = llm.complete(
            [{"role": "system", "content": JUDGE}, {"role": "user", "content": task}],
            budget=Budget(max_calls=1, max_tool_calls=0, max_cost_usd=0.003),
        )
        found = re.search(r"\{.*\}", done.text or "", re.DOTALL)
        return json.loads(found.group()) if found else {"problem": "judge gave no JSON"}
    except (LLMError, ValueError) as exc:  # a judge failure is recorded, never fatal
        return {"problem": f"judge failed: {exc}"}


def figure_in(text: str) -> bool:
    return bool(
        FIGURE.search(ISO_DATE.sub(" ", MONTH_DAY.sub(" ", DAY_MONTH.sub(" ", text))))
    )


def check(
    turn: dict, reply: dict, stop: str | None, cards_before: int, cards_after: int
) -> list:
    text = reply["text"]
    problems = []
    want = turn.get("expect", "any")
    if want == "data" and stop in KINDS["chat"] | KINDS["refuse"]:
        problems.append(f"wanted a data answer, got {stop}")
    elif want in KINDS and stop not in KINDS[want]:
        problems.append(f"wanted {want}, got {stop}")
    if want not in ("refuse", "any") and stop in KINDS["refuse"]:
        problems.append("refused")
    if turn.get("figure") and not figure_in(text):
        problems.append("no figure")
    if (pattern := turn.get("mentions")) and not re.search(
        pattern, text, re.IGNORECASE
    ):
        problems.append(f"does not mention /{pattern}/")
    if (pattern := turn.get("forbid")) and re.search(
        pattern, text, re.IGNORECASE | re.MULTILINE
    ):
        problems.append(f"says /{pattern}/")
    if turn.get("card") and cards_after <= cards_before:
        problems.append("no memory card")
    if turn.get("chips") is False and reply.get("evidenceIds"):
        problems.append("shows evidence chips")
    if WEAR.search(text):
        problems.append("talks about wear or coverage")
    if RECITES.search(text) and not ABOUT_ME.search(turn["m"]):
        problems.append("recites the profile")
    if want != "refuse" and MEDICAL.search(text) and stop not in KINDS["refuse"]:
        problems.append("medical words")
    if text.lower().count("usual range") > 1:
        problems.append("repeats 'usual range'")
    return problems


def main(names: list[str]) -> None:
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("")
    conversations = json.loads((HERE / "conversation_set.json").read_text())[
        "conversations"
    ]
    if names:
        conversations = [c for c in conversations if c["name"] in names]
    engine = database()
    # One synthetic person asks a whole set in a day: the app's daily caps would stop it halfway.
    settings.chat_daily_cap_per_user_usd = settings.chat_daily_cap_total_usd = (
        STOP_AT_USD + 0.2
    )
    # Ledgers of our own: what each spends, and a hard stop a little above the soft one.
    spend, graded_spend = (
        SpendLedger(cap_usd=STOP_AT_USD + 0.2),
        SpendLedger(cap_usd=0.3),
    )
    llm = OpenAILLM.from_settings(settings, spend)
    grader = OpenAILLM.from_settings(settings, graded_spend)
    client = app_for(engine, llm)
    headers = sign_in(client, engine)
    rows = []
    for conversation in conversations:
        if spend.spent_usd + graded_spend.spent_usd >= STOP_AT_USD:
            print("Stopped at the spending limit.")
            break
        chat_id = client.post("/conversations", headers=headers).json()["id"]
        history: list[tuple[str, str]] = []
        for turn in conversation["turns"]:
            waiting = len(client.get("/memory", headers=headers).json()["waiting"])
            spent = spend.spent_usd
            response = client.post(
                "/chat",
                json={"text": turn["m"], "conversationId": chat_id},
                headers=headers,
            )
            body = response.json()
            if response.status_code != 200:
                reply, stop, kind = {"text": json.dumps(body)}, "error", None
            else:
                reply = body[-1]
                with session_scope(engine) as db:
                    trace = db.scalar(
                        select(AnswerTrace).where(
                            AnswerTrace.message_id == uuid.UUID(reply["id"])
                        )
                    )
                    stop = trace.stop_reason if trace else None
                    kind = trace.question_type if trace else None
            cards = client.get("/memory", headers=headers).json()["waiting"]
            if turn.get("keep") and cards:
                newest = cards[0]["id"]  # newest first
                client.post(
                    f"/memory/facts/{newest}/decision",
                    json={"keep": True},
                    headers=headers,
                )
            problems = check(turn, reply, stop, waiting, len(cards))
            new_cards = [c["text"] for c in cards[: max(0, len(cards) - waiting)]]
            with session_scope(engine) as db:
                steps = (
                    trace.steps
                    if (
                        trace := db.scalar(
                            select(AnswerTrace).where(
                                AnswerTrace.message_id == uuid.UUID(reply["id"])
                            )
                        )
                    )
                    else []
                )
            checks = [
                s.get("summary_problems") for s in steps if s.get("type") == "verify"
            ]
            graded = judge(grader, history, turn["m"], reply["text"])
            row = {
                "conversation": conversation["name"],
                "m": turn["m"],
                "expect": turn.get("expect", "any"),
                "stop": stop,
                "type": kind,
                "cost": round(spend.spent_usd - spent, 5),
                "problems": problems,
                "judge": graded,
                "chips": len(reply.get("evidenceIds") or []),
                "new_cards": new_cards,
                "check_problems": [p for p in checks if p],
                "reply": reply["text"],
            }
            rows.append(row)
            with OUT.open("a") as file:
                file.write(json.dumps(row) + "\n")
            mark = "ok " if not problems else "BAD"
            print(f"{mark} [{stop}/{kind}] {turn['m']}\n    -> {reply['text'][:300]}")
            if problems:
                print(f"    problems: {problems}")
            print(f"    judge: {graded}")
            history.append((turn["m"], reply["text"]))
    scored = [r["judge"] for r in rows if isinstance(r["judge"].get("sound"), int)]

    def mean(key: str) -> float:
        values = [s[key] for s in scored if isinstance(s.get(key), int)]
        return round(float(np.mean(values)), 2) if values else 0.0

    summary = {
        "date": str(TODAY),
        "turns": len(rows),
        "passed_code_checks": sum(not r["problems"] for r in rows),
        "problems": dict(Counter(p.split(",")[0] for r in rows for p in r["problems"])),
        "judge_mean": {k: mean(k) for k in ("sound", "context", "natural")},
        "judge_below_4_on_sound": sum(s.get("sound", 5) < 4 for s in scored),
        "stops": dict(Counter(r["stop"] for r in rows)),
        "agent_usd": round(spend.spent_usd, 4),
        "judge_usd": round(graded_spend.spent_usd, 4),
    }
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
