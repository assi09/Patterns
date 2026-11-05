"""One paid synthetic draft-preparation check; never sends a Google write.

Run explicitly from the repository root with the venv active:
    python eval/logging_smoke.py --run-paid
Prints aggregates only. Record the returned cost in docs/costs.md and experiments.md.
"""

import argparse
import json
import tempfile
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from alembic import command
from alembic.config import Config
from app.actions.tools import proposal_tools
from app.agent.ask import ask, default_guard, default_router
from app.agent.llm import OpenAILLM
from app.config import settings
from app.db.models import User
from app.db.session import session_scope
from sqlalchemy import create_engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-paid", action="store_true", required=True)
    parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="503p-logging-smoke-") as folder:
        url = f"sqlite:///{folder}/test.db"
        config = Config(
            str(Path(__file__).resolve().parents[1] / "backend/alembic.ini")
        )
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        engine = create_engine(url)
        with session_scope(engine) as db:
            user = User(email="synthetic@example.com", status="approved")
            db.add(user)
            db.flush()
            user_id = user.id
        now = datetime(2026, 10, 24, 12, tzinfo=UTC)
        prepared: list[str] = []
        tools = proposal_tools(
            lambda: session_scope(engine), user_id, uuid.uuid4(), now, prepared
        )
        reply = ask(
            OpenAILLM.from_settings(settings),
            default_router(settings),
            pd.DataFrame(index=pd.DatetimeIndex([], name="date")),
            "Please log a food entry named Example meal for lunch on 2026-10-24 at "
            "12:00:00+03:00. Total supplied values for the entry: 650 kcal, 40 g protein, "
            "70 g carbohydrate and 20 g fat. Prepare a draft only; do not send it to Google.",
            today=date(2026, 10, 24),
            now=now,
            action_tools=tools,
            guard=default_guard(settings),
        )
        extra_cost = reply.route.classification.cost_usd + sum(
            step.get("cost_usd", 0)
            for step in reply.result.trace
            if step["type"] == "guard"
        )
        print(
            json.dumps(
                {
                    "topic": reply.route.expert,
                    "intent": str(reply.route.classification.intent),
                    "drafts": len(prepared),
                    "stop_reason": reply.result.stop_reason,
                    "model_calls": reply.result.budget.calls,
                    "model_cost_usd": reply.result.budget.cost_usd,
                    "router_and_guard_cost_usd": extra_cost,
                    "google_writes": 0,
                }
            )
        )
        if len(prepared) != 1 or reply.result.stop_reason != "submitted":
            raise SystemExit(
                "Expected one reviewable draft and a completed submission."
            )
        engine.dispose()


if __name__ == "__main__":
    main()
