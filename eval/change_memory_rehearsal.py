"""The fresh-chat handoff rehearsal for change memory (eval/change_memory_rehearsal.md). Local only:
no production write, no paid API. The chats are run by a person in a real client (Claude Code or
Codex); this script only prepares the database and reads it back.

    PYTHONPATH=backend python eval/change_memory_rehearsal.py setup
    FA_DATABASE_URL=sqlite:///data/eval/change_memory/rehearsal.db FA_SENTRY_DSN= \\
      FA_OPENAI_API_KEY= uvicorn app.api.main:app --app-dir backend --port 8014
    PYTHONPATH=backend python eval/change_memory_rehearsal.py check

`setup` copies the supervisor eval instance (data/eval/supervisor/local.db, left untouched) to
data/eval/change_memory/rehearsal.db and migrates the copy. `check` prints, for the synthetic team
with a past change only: the changes recorded since setup (state, source, play, dates, tracking,
whether it was reported tried), events, notifications sent, and the MCP tool calls made since
setup by name. The server never stores a call's inputs or results, so whether an assistant passed
`as_of` is read from the client's own transcript, not here.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

SOURCE = Path("data/eval/supervisor")
FOLDER = Path("data/eval/change_memory")
DB = FOLDER / "rehearsal.db"
STATE = FOLDER / "rehearsal.json"


def setup() -> None:
    FOLDER.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE / "local.db", DB)
    url = f"sqlite:///{DB}"
    subprocess.run(
        ["alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
        check=True,
        env={**os.environ, "FA_DATABASE_URL": url},
        capture_output=True,
    )
    instance = json.loads((SOURCE / "instance.json").read_text())
    STATE.write_text(
        json.dumps(
            {"started": datetime.now(UTC).isoformat(), "team": instance["teams"]["demo_acted"]},
            indent=1,
        )
    )
    print(f"Ready: {DB} (migrated copy). Start the API on it, port 8014.")


def check() -> None:
    import uuid

    from app.db.models import HarnessCall, Notification, TeamAction, TeamNote
    from app.db.session import session_scope
    from sqlalchemy import create_engine, select

    state = json.loads(STATE.read_text())
    started = datetime.fromisoformat(state["started"])
    team = uuid.UUID(state["team"])
    engine = create_engine(f"sqlite:///{DB}")
    with session_scope(engine) as db:

        def after(at: datetime | None) -> bool:
            return at is not None and (at if at.tzinfo else at.replace(tzinfo=UTC)) >= started

        changes = [
            {
                "status": a.status,
                "source": a.source,
                "play": a.play,
                "dates": [str(a.starts_on), str(a.ends_on)],
                "tracked": a.metric,
                "comparison": a.comparison,
                "event_linked": a.event_id is not None,
                "implementation": a.implementation,
            }
            for a in db.scalars(select(TeamAction).where(TeamAction.team_id == team))
            if after(a.proposed_at)
        ]
        events = sum(
            after(n.created_at)
            for n in db.scalars(select(TeamNote).where(TeamNote.team_id == team))
        )
        sent = sum(after(n.created_at) for n in db.scalars(select(Notification)))
        calls: dict[str, list[int]] = {}
        for call in db.scalars(select(HarnessCall)):
            if after(call.at):
                ok, failed = calls.setdefault(call.tool, [0, 0])
                calls[call.tool] = [ok + call.ok, failed + (not call.ok)]
    print(
        json.dumps(
            {
                "since": state["started"],
                "changes_recorded": changes,
                "events_added": events,
                "notifications_sent": sent,
                "tool_calls_ok_failed": dict(sorted(calls.items())),
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    {"setup": setup, "check": check}[sys.argv[1] if len(sys.argv) > 1 else "check"]()
