"""The fresh-chat handoff rehearsal for change memory (eval/change_memory_rehearsal.md). Local only:
no production write, no paid API. The chats are run by a person in a real client (Claude Code or
Codex); this script only prepares the database and reads it back.

    PYTHONPATH=backend python eval/change_memory_rehearsal.py setup
    FA_DATABASE_URL=sqlite:///data/eval/change_memory/rehearsal.db FA_SENTRY_DSN= \\
      FA_OPENAI_API_KEY= uvicorn app.api.main:app --app-dir backend --port 8014
    PYTHONPATH=backend python eval/change_memory_rehearsal.py check
    PYTHONPATH=backend python eval/change_memory_rehearsal.py grade calls.json

`setup` copies the supervisor eval instance (data/eval/supervisor/local.db, left untouched) to
data/eval/change_memory/rehearsal.db and migrates the copy. `check` prints, for the synthetic team
with a past change only: the changes recorded since setup (state, source, play, dates, tracking,
whether it was reported tried), events, notifications sent, and the MCP tool calls made since
setup by name. The server never stores a call's inputs or results, so whether an assistant passed
`as_of` is read from the client's own transcript, not here.

`check` also lists every change and held submission recorded since setup on **any** team, each
marked with whether it went to the intended team, so a draft's destination is read from the
database. `grade` scores team selection from a chat's tool calls, as copied from the transcript
into a JSON list of {"tool": ..., "arguments": {...} or null}: listing teams is fine, a read of
another team is a wrong-team lookup, a write to another team fails, and a team call whose
arguments the transcript does not show is unverified.
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
# Another file only to try the checks on a throwaway copy; the rehearsal uses the default.
DB = Path(os.environ.get("FA_REHEARSAL_DB", FOLDER / "rehearsal.db"))
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


LISTING = {"who_am_i"}
TEAM_READS = {
    "team_overview",
    "team_finding_evidence",
    "team_meeting_load",
    "team_history",
    "team_case",
}
TEAM_WRITES = {"record_team_change", "send_team_event"}


def _labels() -> dict[str, str]:
    """Team id (no dashes, lower case) to its key in the instance file: never a name."""
    instance = json.loads((SOURCE / "instance.json").read_text())
    return {str(v).replace("-", "").lower(): k for k, v in instance["teams"].items()}


def _team(value, labels: dict[str, str]) -> str:
    key = str(value).replace("-", "").lower()
    return labels.get(key, "an id that is none of the instance's teams")


def grade(path: str) -> None:
    """Team selection for one chat, from its tool calls."""
    state = json.loads(STATE.read_text())
    intended = state["team"].replace("-", "").lower()
    labels = _labels()
    rows, verdicts = [], set()
    for call in json.loads(Path(path).read_text()):
        tool, arguments = call["tool"], call.get("arguments")
        if tool in LISTING:
            verdict = "listing teams (fine)"
        elif tool in TEAM_READS | TEAM_WRITES:
            write = tool in TEAM_WRITES
            team_id = (arguments or {}).get("team_id")
            if team_id is None:
                verdict = "unverified write" if write else "unverified read"
            elif str(team_id).replace("-", "").lower() == intended:
                verdict = "intended-team write" if write else "intended-team read"
            else:
                verdict = "wrong-team write" if write else "wrong-team lookup"
                rows.append({"tool": tool, "verdict": verdict, "team": _team(team_id, labels)})
                verdicts.add(verdict)
                continue
        else:
            verdict = "not a team tool"
        rows.append({"tool": tool, "verdict": verdict})
        verdicts.add(verdict)
    if "wrong-team write" in verdicts:
        result = "fail: wrong-team write (the task fails)"
    elif "wrong-team lookup" in verdicts:
        result = "wrong-team lookup (scored here even if the answer is right)"
    elif verdicts & {"unverified read", "unverified write"}:
        result = "unverified: a team call's target is not in the transcript"
    else:
        result = "pass"
    print(json.dumps({"team_selection": result, "calls": rows}, indent=1))


def check() -> None:
    import uuid

    from app.db.models import HarnessCall, HarnessSubmission, Notification, TeamAction, TeamNote
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
        labels = _labels()
        # Every team, so a draft written to the wrong one shows up here.
        destinations = [
            {
                "what": f"change ({a.status}, source {a.source})",
                "team": _team(a.team_id, labels),
                "intended_team": a.team_id == team,
            }
            for a in db.scalars(select(TeamAction))
            if after(a.proposed_at)
        ] + [
            {
                "what": f"held {s.kind} ({s.status})",
                "team": _team(s.team_id, labels) if s.team_id else "no team (own data)",
                "intended_team": s.team_id == team,
            }
            for s in db.scalars(select(HarnessSubmission))
            if after(s.created_at)
        ]
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
                "writes_on_any_team": destinations,
                "events_added": events,
                "notifications_sent": sent,
                "tool_calls_ok_failed": dict(sorted(calls.items())),
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    if command == "grade":
        grade(sys.argv[2])
    else:
        {"setup": setup, "check": check}[command]()
