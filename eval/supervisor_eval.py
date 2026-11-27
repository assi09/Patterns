# ruff: noqa: SIM117 (a client session opens inside its transport, as the MCP SDK shows it)
"""Scripted MCP runs of the frozen supervisor tasks (eval/supervisor_tasks.json). Free: no model.

Against a local API on the instance from eval/supervisor_instance.py:

    FA_DATABASE_URL=sqlite:///data/eval/supervisor/local.db FA_SENTRY_DSN= FA_OPENAI_API_KEY= \\
      uvicorn app.api.main:app --app-dir backend --port 8013 &
    PYTHONPATH=backend:eval python eval/supervisor_eval.py <label>

The client is the MCP SDK's own. Each task has a fixed plan of calls, the same for every version
of the server; when a server does not know an argument (the baseline has no `week`), the call is
made once more without it, as an assistant would, and the extra call is counted. Each task's
checks read only what the tools returned. Team discovery (`who_am_i`) is counted apart. A task
that fails gets no efficiency credit. Writes eval/results/supervisor_<label>_<date>.json with
outcomes, calls, bytes and latency; never a token or a tool's full output.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = os.environ.get("FA_EVAL_MCP_URL", "http://127.0.0.1:8013/mcp/")
FOLDER = Path(os.environ.get("FA_SUPERVISOR_INSTANCE", "data/eval/supervisor"))
INSTANCE = json.loads((FOLDER / "instance.json").read_text())
TEAMS = INSTANCE["teams"]


class Run:
    """One client session's calls, with what each returned and how long it took."""

    def __init__(self, session: ClientSession) -> None:
        self.session = session
        self.calls: list[dict] = []

    async def call(self, tool: str, args: dict, optional: tuple[str, ...] = ()) -> dict:
        started = time.perf_counter()
        result = await self.session.call_tool(tool, args)
        text = " ".join(getattr(c, "text", "") for c in result.content)
        self.calls.append(
            {
                "tool": tool,
                "ok": not result.is_error,
                "bytes": len(text.encode()),
                "seconds": round(time.perf_counter() - started, 3),
            }
        )
        if result.is_error and any(a in text for a in optional):
            kept = {k: v for k, v in args.items() if k not in optional}
            return await self.call(tool, kept)
        return {"error": result.is_error, "text": text}


def _pending_proposals(team_id: str) -> int:
    """Proposals waiting for the supervisor, read from the local instance's database."""
    import sqlite3

    db = sqlite3.connect(INSTANCE["url"].removeprefix("sqlite:///"))
    row = db.execute(
        "select count(*) from team_actions where team_id = ? and status = 'proposed'",
        (team_id.replace("-", ""),),
    ).fetchone()
    return row[0]


def has(text: str, *needles: str) -> bool:
    return all(n in text for n in needles)


def contributors(text: str, n: int) -> bool:
    return bool(re.search(rf'"contributors": {n}\b|\b0 of {n} higher', text))


async def tasks(run: Run) -> dict[str, dict]:
    """Every frozen task's checks; True only when its facts are in the tool outputs."""
    out = {}
    ls11, ls4 = TEAMS["lifesnaps-11"], TEAMS["lifesnaps-4"]
    week = {"week": "2021-07-19"}

    first = await run.call("team_overview", {"team_id": ls11, **week}, ("week",))
    t = first["text"]
    out["ls11_what_changed"] = {
        "steps -696": has(t, "-696"),
        "contributors 5": contributors(t, 5),
        "comparison 2021-06-21 to 2021-07-18": has(t, "2021-06-21", "2021-07-18"),
        "target week 2021-07-19 to 2021-07-25": has(t, "2021-07-19", "2021-07-25"),
        "evidence reference": bool(re.search(r'"evidence_id": "[0-9a-f]{6,}"', t)),
    }
    out["ls11_all_eleven"] = {
        "roster 11": bool(re.search(r'"roster": 11\b', t)),
        "contributors 5": contributors(t, 5),
        "minimum 5": bool(re.search(r'"minimum(_members)?": 5\b', t)),
    }
    found = re.search(
        r'"report_id": "([^"]+)".*?"metric": "steps".*?"evidence_id": "([^"]+)"', t, re.S
    )
    if found:
        ev = await run.call(
            "team_finding_evidence",
            {"team_id": ls11, "report_id": found[1], "evidence_id": found[2]},
        )
        e = ev["text"]
    else:
        e = ""
    out["ls11_evidence"] = {
        "reached": bool(e) and '"error"' not in e[:20],
        "method stated": "median" in e and "previous four weeks" in e,
        "dates": has(e, "2021-07-19", "2021-06-21", "2021-07-18"),
        "contributors 5": contributors(e, 5),
        "0 higher, 5 lower": bool(re.search(r'"higher": 0\b', e))
        and bool(re.search(r'"lower": 5\b', e)),
        "no quartiles": "q1" not in e and "q3" not in e,
    }

    w = await run.call("team_overview", {"team_id": ls4, **week}, ("week",))
    t = w["text"]
    out["ls4_withheld"] = {
        "withheld": has(t, "withheld"),
        "reason": has(t, "3 of the 5 people needed"),
        "week asked": has(t, "2021-07-19"),
        "no figure": not re.search(r"median|-?\d+ steps|\bbpm\b", t),
    }

    q = await run.call("team_overview", {"team_id": ls11, "week": "2021-05-24"}, ("week",))
    t = q["text"]
    out["quiet_week"] = {
        "week asked": has(t, "2021-05-24"),
        "ready": has(t, '"ready"'),
        "no priority": bool(re.search(r'"priorities": \[\]', t)),
        "no weekly change": bool(re.search(r'"changed": \[\]', t)),
        "coverage stated": has(t, '"withheld_metrics"') or has(t, "not enough data"),
    }

    n = await run.call("team_overview", {"team_id": ls11, "week": "2023-01-02"}, ("week",))
    t = n["text"]
    out["no_report_week"] = {
        "no report stated": has(t, "no_report"),
        "no other week": "2022-01-10" not in t and "2021-" not in t,
    }

    c = await run.call("team_meeting_load", {"team_id": ls11, **week}, ("week",))
    t = c["text"]
    out["historical_calendar"] = {
        "week asked": has(t, "2021-07-19"),
        "unavailable stated": has(t, "unavailable"),
        "no figures": not re.search(r'"median', t),
        "no zero inferred": not re.search(r'"meeting_minutes": 0\b', t),
    }

    both = TEAMS["demo_both"]
    s = await run.call("team_overview", {"team_id": both})
    t = s["text"]
    rep_week = re.search(r'"week_start": "(\d{4}-\d{2}-\d{2})"', t)
    m = await run.call(
        "team_meeting_load",
        {"team_id": both, "week": rep_week[1] if rep_week else ""},
        ("week",),
    )
    mt = m["text"]
    out["synthetic_both_sources"] = {
        "sustained change": "Sustained change" in t or '"sustained"' in t,
        # Corrected after the first dev run: the server indents its JSON, so the frozen pattern
        # (no whitespace after the brace) could never match. Same check, whitespace allowed.
        "finding dates": bool(re.search(r'"baseline": \{\s*"start": "\d{4}', t)),
        "calendar same week": bool(rep_week) and rep_week[1] in mt,
        "calendar comparison dates": has(mt, '"baseline"'),
        "no automatic scheduling proposal": "evening boundary" not in t.lower()
        and _pending_proposals(both) == 0,
    }

    acted = TEAMS["demo_acted"]
    h = await run.call(
        "team_overview", {"team_id": acted, "week": INSTANCE["action_week"]}, ("week",)
    )
    now = await run.call("team_overview", {"team_id": acted})
    out["action_follow_up"] = {
        "historical: in progress": has(h["text"], "in_progress"),
        # A measured result is marked by "verdict" up to #262 and "outcome" from it; either
        # counts, so the change of key favours neither version (disclosed in the workflow doc).
        "historical: no result": not any(k in h["text"] for k in ('"verdict"', '"outcome"')),
        "current: result": any(has(now["text"], k) for k in ('"verdict"', '"outcome"')),
        "current: result evidence": bool(re.search(r'"result".*"evidence_id"', now["text"], re.S)),
        "measured apart from tried": has(now["text"], "measured") and has(now["text"], "tried"),
    }

    theirs = TEAMS["other_supervisors_team"]
    a = await run.call("team_overview", {"team_id": theirs})
    b = await run.call(
        "team_finding_evidence",
        {"team_id": ls11, "report_id": found[1] if found else "x", "evidence_id": "000000000000"},
    )
    out["scope_and_authorization"] = {
        "another supervisor's team refused": a["error"] and "No such team" in a["text"],
        "unknown evidence reveals nothing": b["error"] and "-696" not in b["text"],
    }
    out["tool_failures"] = {
        "unavailable evidence is an error": b["error"],
    }
    return out


async def other_checks() -> dict:
    """Checks that need another token: a revoked one, and another supervisor's evidence."""
    out = {}
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {INSTANCE['revoked_token']}"}, timeout=30
    ) as http:
        r = await http.post(URL, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        out["revoked token refused"] = r.status_code == 401
    return out


def _no_later_report(text: str, cutoff: str) -> bool:
    """No report made after the cutoff: none by then, or one whose made_on is by then."""
    try:
        report = json.loads(text).get("report") or {}
    except (ValueError, AttributeError):
        return False
    made = report.get("made_on")
    return report.get("state") == "no_report_by_then" or (made is not None and made <= cutoff)


async def versioned(run: Run, frozen: dict[str, dict]) -> dict[str, dict]:
    """The versioned tasks (eval/supervisor_tasks.json, "versioned"), on their own call count so
    the frozen run's stays comparable. action_follow_up_v2 asks the historical question with its
    cutoff, as_of the day after the week; its current half is the frozen task's own checks."""
    acted = TEAMS["demo_acted"]
    cutoff = (date.fromisoformat(INSTANCE["action_week"]) + timedelta(days=7)).isoformat()
    h = await run.call(
        "team_overview",
        {"team_id": acted, "week": INSTANCE["action_week"], "as_of": cutoff},
        ("as_of",),
    )
    current = {
        k: v
        for k, v in frozen["action_follow_up"].items()
        if k.startswith(("current", "measured"))
    }
    return {
        "action_follow_up_v2": {
            "historical: in progress": has(h["text"], "in_progress"),
            "historical: no result": not any(k in h["text"] for k in ('"verdict"', '"outcome"')),
            "historical: no later report": _no_later_report(h["text"], cutoff),
            **current,
        }
    }


REPLACES = {"action_follow_up_v2": "action_follow_up"}


async def main(label: str) -> None:
    token = INSTANCE["presenter"]["token"]
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=60)
    async with http, streamable_http_client(URL, http_client=http) as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            discovery = Run(s)
            await discovery.call("who_am_i", {})
            run = Run(s)
            results = await tasks(run)
            # A retried read gives the same answer (no state changes on reads).
            r1 = await run.call(
                "team_overview", {"team_id": TEAMS["lifesnaps-11"], "week": "2021-07-19"}, ("week",)
            )
            r2 = await run.call(
                "team_overview", {"team_id": TEAMS["lifesnaps-11"], "week": "2021-07-19"}, ("week",)
            )
            results["tool_failures"]["retry gives the same answer"] = r1["text"] == r2["text"]
            later = Run(s)
            newer = await versioned(later, results)
    results["scope_and_authorization"] |= await other_checks()
    passed = {k: all(v.values()) for k, v in results.items()}
    # The revised suite: the frozen one with each versioned task in place of the one it replaces.
    revised = {k: v for k, v in passed.items() if k not in REPLACES.values()}
    revised |= {k: all(v.values()) for k, v in newer.items()}
    calls = run.calls
    summary = {
        "label": label,
        "commit": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip(),
        # The server's code can differ from this script's checkout (the baseline runs apart).
        "server_revision": os.environ.get("FA_EVAL_SERVER_REVISION", "this checkout"),
        "date": date.today().isoformat(),
        "tools": tools,
        "tasks_passed": f"{sum(passed.values())}/{len(passed)}",
        "passed": passed,
        "checks": results,
        # Reported apart: the frozen score above is the one on record.
        "revised": {
            "replaces": REPLACES,
            "tasks_passed": f"{sum(revised.values())}/{len(revised)}",
            "passed": revised,
            "checks": newer,
            "calls": len(later.calls),
        },
        "calls": {
            "discovery": len(discovery.calls),
            "task_calls": len(calls),
            "failed_calls": sum(not c["ok"] for c in calls),
            "bytes": sum(c["bytes"] for c in calls),
            "seconds": round(sum(c["seconds"] for c in calls), 3),
        },
    }
    out = Path("eval/results") / f"supervisor_{label}_{date.today().isoformat()}.json"
    out.write_text(json.dumps(summary, indent=1) + "\n")
    print(
        json.dumps(
            {k: summary[k] for k in ("label", "server_revision", "tasks_passed", "calls")}
            | {"revised_tasks_passed": summary["revised"]["tasks_passed"]},
            indent=1,
        )
    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "run"))
