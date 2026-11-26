# ruff: noqa: SIM117 (a client session opens inside its transport, as the MCP SDK shows it)
"""Does a team figure survive the whole path to the supervisor? Three ways, one week.

For team A (PMData's 16 real people, seeded by `eval/mcp_red_team_seed.py`), the week of
2020-01-06, as of the Monday after:

1. the team figures computed straight from the dataset files (`eval/real_data.py`), no database;
2. the supervisor's stored weekly report (`python -m app.teams weekly --week 2020-01-06`);
3. an authenticated MCP read over HTTP with the supervisor's token, the server's date set to
   2020-01-13 so "the latest readings" are those of that week.

Passes only when all three agree, figure by figure. From the repository root, after seeding and
making the report (Sentry off):
    FA_SENTRY_DSN= FA_DATABASE_URL=sqlite:////tmp/rt.db FA_REMINDERS_ENABLED=false \\
      PYTHONPATH=backend:eval python eval/team_three_way.py /tmp/tokens.json
Prints pass/fail and counts only; exits 1 on any failure.
"""

import asyncio
import json
import sys
import threading
import time
from datetime import date
from pathlib import Path

import httpx2
import real_data
import uvicorn
from app.analysis import team
from app.api.main import create_app
from app.db.models import TeamReport
from app.db.session import session_scope
from app.harness import server as mcp_server
from app.teams import observed as observed_text
from app.teams import reports
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select

WEEK = team.week_of(date(2020, 1, 6))
AS_OF = date(2020, 1, 13)  # the Monday after: the week checked is "the last full week"
PORT = 8013
T = json.loads(Path(sys.argv[1]).read_text())
failures = 0


def check(name: str, ok: bool) -> None:
    global failures
    failures += 0 if ok else 1
    print(("PASS " if ok else "FAIL ") + name)


# 1. From the dataset files alone.
frames = list(real_data.load_pmdata().values())
stats = team.team_statistics(frames, WEEK)
changed = {e.metrics[0] for e in stats.changed}
expected = {
    e.metrics[0]: reports._section(e, e.metrics[0] in changed)["text"]
    for e in stats.changes
}
expected_readings = [
    observed_text.sentence(e, AS_OF) for e in team.team_observed(frames, AS_OF)
]
print("members per metric:", {e.metrics[0]: e.stats["members"] for e in stats.changes})

# 2. The stored report.
with session_scope() as db:
    report = db.scalar(
        select(TeamReport).where(
            TeamReport.team_id == T["team_a"], TeamReport.week_start == WEEK.start
        )
    )
    stored = (
        {}
        if report is None
        else {s["metric"]: s["text"] for s in report.body["sections"]}
    )
    stored_order = (
        [] if report is None else [s["text"] for s in report.body["sections"]]
    )
check(
    "the report exists for the week and is not withheld",
    report is not None and report.status != "withheld",
)
check("dataset and report agree, metric by metric", stored == expected)
check(
    "every figure shown comes from at least 5 people",
    all(e.stats["members"] >= team.MIN_MEMBERS for e in stats.changes if e.sufficient),
)

# 3. An authenticated MCP read, as of the Monday after.
mcp_server._today = lambda user, fallback: AS_OF
server = uvicorn.Server(
    uvicorn.Config(create_app(), host="127.0.0.1", port=PORT, log_level="warning")
)
threading.Thread(target=server.run, daemon=True).start()
while not server.started:
    time.sleep(0.2)


async def read() -> dict:
    http = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {T['boss_a']}"}, timeout=60
    )
    async with (
        http,
        streamable_http_client(f"http://127.0.0.1:{PORT}/mcp/", http_client=http) as s,
    ):
        async with ClientSession(s[0], s[1]) as session:
            await session.initialize()
            result = await session.call_tool("team_overview", {"team_id": T["team_a"]})
            return json.loads(" ".join(getattr(c, "text", "") for c in result.content))


got = asyncio.run(read())
server.should_exit = True
weekly = got.get("weekly_report") or {}
check(
    "MCP returns the report's week", weekly.get("week_start") == WEEK.start.isoformat()
)
check(
    "report and MCP agree, every figure line in order",
    weekly.get("figures") == stored_order,
)
check(
    "dataset and MCP agree on the latest readings as of 2020-01-13",
    got.get("readings") == expected_readings,
)
print(f"figure lines: {len(stored_order)}; readings: {len(expected_readings)}")
print("failures:", failures)
sys.exit(1 if failures else 0)
