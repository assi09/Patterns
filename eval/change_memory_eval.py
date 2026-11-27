# ruff: noqa: SIM117 (a client session opens inside its transport, as the MCP SDK shows it)
"""Scripted runs of the frozen change-memory cases (eval/change_memory_tasks.json), through MCP
and the app's API. Free: no model. Local only.

    PYTHONPATH=backend:eval python eval/change_memory_instance.py      # on the day of the run
    python eval/change_memory_eval.py prepare                          # a fresh copy to run on
    FA_DATABASE_URL=sqlite:///data/eval/change_memory/run.db FA_SENTRY_DSN= FA_OPENAI_API_KEY= \\
      FA_REMINDERS_ENABLED=false uvicorn app.api.main:app --app-dir backend --port 8015 &
    PYTHONPATH=backend:eval python eval/change_memory_eval.py run <label>

Each case opens its own MCP session, so nothing is carried from one case to the next but what
Patterns stored. The supervisor's steps in the app (approve, "Did the team try it?") go through
the app's own API with the supervisor's sign-in. A case passes only if every `must` holds and no
`never` occurs, read from what the tools returned and, where a case is about what was stored,
from the run's database. The review regressions (docs/change-memory.md) are scored apart from
the eleven frozen cases.

For a baseline, run the API from a worktree of another revision on its own copy, and name both:
FA_CHANGE_MEMORY_RUN_DB=<that copy> FA_SERVER_REVISION="main at <sha>".

Writes eval/results/change_memory_<label>_<date>.json: each check's outcome, the calls made, the
runner's commit and the server tested; never a token, an id or a tool's output.
"""

import asyncio
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

BASE = os.environ.get("FA_EVAL_API", "http://127.0.0.1:8015")
FOLDER = Path("data/eval/change_memory")
# The database the API under test runs on (another file for a baseline run from a worktree).
RUN_DB = Path(os.environ.get("FA_CHANGE_MEMORY_RUN_DB", FOLDER / "run.db"))
NO_DAY = "No day-specific team evidence available."
LABELS = {
    "above the reference level",
    "below the reference level",
    "no clear difference detected",
    "insufficient data",
}
NO_TEAM = "No such team."


def prepare() -> None:
    shutil.copyfile(FOLDER / "instance.db", RUN_DB)
    print(f"Ready: {RUN_DB}, a copy of the instance. Start the API on it, port 8015.")


INST = (
    json.loads((FOLDER / "instance.json").read_text())
    if (FOLDER / "instance.json").exists()
    else {}
)
TEAM = INST.get("teams", {}).get("team", "")
D = INST.get("dates", {})
CALLS: list[dict] = []


class Session:
    """One fresh MCP session: what each call returned, parsed when it is JSON."""

    def __init__(self, session: ClientSession, case: str) -> None:
        self.session, self.case = session, case

    async def call(self, tool: str, **args) -> tuple[bool, object, str]:
        result = await self.session.call_tool(tool, args)
        text = " ".join(getattr(c, "text", "") for c in result.content)
        CALLS.append({"case": self.case, "tool": tool, "ok": not result.is_error})
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        return (not result.is_error), parsed, text


async def fresh(case: str, token: str | None = None):
    http = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {token or INST['supervisor']['token']}"}, timeout=60
    )
    return http, streamable_http_client(BASE + "/mcp/", http_client=http), case


async def with_session(case: str, work, token: str | None = None):
    http, transport, _ = await fresh(case, token)
    async with http, transport as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            return await work(Session(session, case), session)


def app_sign_in() -> str:
    r = httpx2.post(
        BASE + "/auth/login",
        json={"email": INST["supervisor"]["email"], "password": INST["supervisor"]["password"]},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["token"]


def app(method: str, path: str, token: str, body: dict | None = None) -> httpx2.Response:
    r = httpx2.request(
        method, BASE + path, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=60
    )
    r.raise_for_status()
    return r


def db_rows(sql: str, *args) -> list[tuple]:
    with sqlite3.connect(RUN_DB) as db:
        return db.execute(sql, args).fetchall()


def hexid(case_id: str) -> str:
    return case_id.split(":", 1)[1].replace("-", "")


def dashed(raw: str) -> str:
    raw = str(raw)
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


class Case:
    def __init__(self, name: str) -> None:
        self.name, self.checks = name, []

    def must(self, what: str, ok: bool) -> None:
        self.checks.append({"must": what, "ok": bool(ok)})

    def never(self, what: str, occurred: bool) -> None:
        self.checks.append({"never": what, "ok": not occurred})

    def result(self) -> dict:
        return {"passed": all(c["ok"] for c in self.checks), "checks": self.checks}


def has(text: str, *words: str) -> bool:
    """Any of the words or phrases, whole and in any case: "Sam" is not found in "same"."""
    return any(
        re.search(rf"(?<![A-Za-z]){re.escape(w.strip())}(?![A-Za-z])", text, re.I) for w in words
    )


# --- the eleven frozen cases ------------------------------------------------------------------


async def deadline_weekly_only() -> dict:
    c = Case("deadline_weekly_only")
    friday = D["fridays"]["0"]

    async def work(s, _):
        _, listed, _ = await s.call("team_history", team_id=TEAM, category="deadline")
        found = [x for x in listed["cases"] if x["dates"]["start"] == friday]
        _, case, text = await s.call(
            "team_case", team_id=TEAM, case_id=found[0]["case_id"], day=friday
        )
        return found, case, text

    found, case, text = await with_session(c.name, work)
    day = case["day"]
    weeks = (
        [day["weekly_context"]]
        if isinstance(day["weekly_context"], dict)
        else day["weekly_context"]
    )
    weeks = [w for w in weeks if w]
    c.must("the deadline event with its date", found and case["dates"]["start"] == friday)
    c.must(
        "the overlapping weekly report as weekly context with its actual dates and evidence "
        "reference",
        any(
            w.get("week", {}).get("start") == D["last_week"][0]
            and w.get("week", {}).get("end") == D["last_week"][1]
            and w.get("report_id")
            for w in weeks + case["evidence"]
        )
        and all("weekly context" in w.get("relation", "") for w in case["evidence"]),
    )
    c.must("No day-specific team evidence available", day.get("day_specific") == NO_DAY)
    c.never(
        "a weekly figure presented as Friday's",
        any(
            "day" in w or w.get("week", {}).get("start") == friday for w in weeks + case["evidence"]
        ),
    )
    c.never(
        "a figure from another week",
        any(
            not (w["week"]["start"] <= friday <= w["week"]["end"])
            for w in weeks + case["evidence"]
            if "week" in w
        ),
    )
    return c.result()


def next_weekday(day: date, weekday: int) -> date:
    return day + timedelta(days=(weekday - day.weekday()) % 7 or 7)


REMEMBERED = "keep-thursday-evening-free-0001"
# The calendar data Patterns holds (synced as google_calendar) and calendar days held from MCP.
CALENDAR_ROWS = "select count(*) from daily_metrics where source like '%calendar%'"
HELD_CALENDAR = "select count(*) from harness_submissions where kind = 'calendar_days'"


async def remember_decision() -> dict:
    c = Case("remember_decision")
    thursday = next_weekday(date.today(), 3).isoformat()
    change = {
        "request_id": REMEMBERED,
        "play": "evening_boundary",
        "starts_on": thursday,
        "ends_on": thursday,
    }
    notified = db_rows("select count(*) from notifications")[0][0]
    calendar_rows = db_rows(CALENDAR_ROWS)[0][0]
    held_calendar = db_rows(HELD_CALENDAR)[0][0]

    async def work(s, session):
        first = await s.call("record_team_change", team_id=TEAM, change=change)
        again = await s.call("record_team_change", team_id=TEAM, change=change)
        tools = [t.name for t in (await session.list_tools()).tools]
        return first, again, tools

    (ok1, first, _), (ok2, again, _), tools = await with_session(c.name, work)
    rows = db_rows(
        "select status, source, metric, observe_starts_on, comparison, starts_on, ends_on "
        "from team_actions where request_id = ?",
        REMEMBERED,
    )
    listed = app("GET", f"/teams/{TEAM}/actions", app_sign_in()).json()
    shown = [a for a in listed if a.get("source") == "assistant" and a["status"] == "proposed"]
    label = "Suggested in chat — awaiting your confirmation"
    in_app = label in Path("mobile/src/components/teamBoard.tsx").read_text()
    c.must(
        "one pending draft, shown in the app as Suggested in chat - awaiting your confirmation",
        ok1
        and len(rows) == 1
        and rows[0][:2] == ("proposed", "assistant")
        and len(shown) == 1
        and in_app,
    )
    c.must(
        "no metric and no trial window",
        rows
        and rows[0][2] is None
        and rows[0][3] is None
        and rows[0][4] is None
        and (rows[0][5], rows[0][6]) == (thursday, thursday)
        and first.get("tracking") is None,
    )
    c.must(
        "a retry with the same request_id returns the same record",
        ok2 and again["change_id"] == first["change_id"] and len(rows) == 1,
    )
    c.must(
        "0 members notified",
        first.get("members_notified") == 0
        and db_rows("select count(*) from notifications")[0][0] == notified,
    )
    c.never("status approved", any(r[0] == "approved" for r in rows))
    c.never(
        "a metric or a 14-day window chosen by Patterns",
        any(r[2] or r[6] != thursday for r in rows),
    )
    # A calendar write: anything put in a calendar, or in Patterns' calendar data, by recording
    # the decision. MCP's send_calendar_days (the caller's own counts, held for their approval)
    # is not one; the check is that it was not used and that no tool writes to a calendar.
    c.never(
        "a calendar write",
        any(t.startswith(("create_", "write_", "add_")) and "calendar" in t for t in tools)
        or db_rows(CALENDAR_ROWS)[0][0] != calendar_rows
        or db_rows(HELD_CALENDAR)[0][0] != held_calendar,
    )
    return c.result()


async def offsite_first_night() -> dict:
    c = Case("offsite_first_night")

    async def work(s, _):
        _, event, _ = await s.call("team_case", team_id=TEAM, case_id=INST["events"]["offsite"])
        _, change, text = await s.call(
            "team_case", team_id=TEAM, case_id=INST["changes"]["offsite_change"]
        )
        return event, change, text

    event, change, text = await with_session(c.name, work)
    observed = change["tracking"]["observe"]
    night = D["first_night"]
    c.must(
        "the three-day event and the one-night observation window kept as separate dates",
        event["dates"] != observed
        and (
            date.fromisoformat(event["dates"]["end"]) - date.fromisoformat(event["dates"]["start"])
        ).days
        == 2
        and observed == {"start": night, "end": night}
        and change["linked"]["event"] == INST["events"]["offsite"],
    )
    c.must(
        "the night named by the day it ended",
        "night ending that morning" in change["observation"]["date_convention"]
        and night == (date.fromisoformat(event["dates"]["start"]) + timedelta(days=1)).isoformat(),
    )
    c.must(
        "a qualifying observation or a clear unavailable state",
        change["observation"]["state"] == "unavailable"
        and change["observation"]["reason"] == NO_DAY,
    )
    c.never("the offsite's three days used as the observation", observed == event["dates"])
    c.never(
        "a comparison verdict for one night",
        change.get("outcome") is not None
        or "no comparison verdict" not in change["tracking"]["comparison"]
        or has(text, *LABELS),
    )
    return c.result()


async def three_deadlines() -> dict:
    c = Case("three_deadlines")

    async def work(s, _):
        _, listed, ltext = await s.call("team_history", team_id=TEAM, category="deadline")
        cases, texts = {}, [ltext]
        for x in listed["cases"]:
            _, case, t = await s.call("team_case", team_id=TEAM, case_id=x["case_id"])
            cases[x["dates"]["start"]] = case
            texts.append(t)
            for linked in case.get("linked_changes", []):
                _, ch, t = await s.call("team_case", team_id=TEAM, case_id=linked)
                case.setdefault("_opened", []).append(ch)
                texts.append(t)
        return cases, " ".join(texts)

    cases, text = await with_session(c.name, work)
    f = D["fridays"]
    c.must("all three deadlines", all(f[k] in cases for k in ("0", "1", "2")))
    none_, declined, tried = (cases.get(f[k], {}) for k in ("2", "1", "0"))
    opened = {k: (cases.get(f[k], {}).get("_opened") or [None])[0] for k in ("1", "0")}
    c.must(
        "no action / declined / approved and reported tried, each kept distinct",
        none_.get("linked_changes") == []
        and opened["1"]
        and opened["1"]["decision"]["state"] == "declined"
        and opened["0"]
        and opened["0"]["decision"]["state"] == "approved"
        and opened["0"]["implementation"].startswith("reported tried"),
    )
    c.must(
        "the evidence available for each, or none",
        all(cases.get(f[k], {}).get("evidence") for k in ("0", "1", "2")),
    )
    c.never("the deadline with no action left out", f["2"] not in cases)
    c.never("a ranking", has(text, "rank", "best ", "worst", "most effective"))
    c.never("worked", has(text, "worked"))
    return c.result()


async def overlapping_events() -> dict:
    c = Case("overlapping_events")

    async def work(s, _):
        _, deadline, t1 = await s.call(
            "team_case", team_id=TEAM, case_id=INST["events"]["deadline_l0"]
        )
        _, offsite, t2 = await s.call("team_case", team_id=TEAM, case_id=INST["events"]["offsite"])
        return deadline, offsite, t1 + t2

    deadline, offsite, text = await with_session(c.name, work)
    E, C = INST["events"], INST["changes"]
    c.must(
        "both events as nearby context",
        E["offsite"] in deadline["nearby"]["cases"]
        and E["deadline_l0"] in offsite["nearby"]["cases"]
        and "not an explanation" in deadline["nearby"]["meaning"],
    )
    c.must(
        "an explicit action link kept as linked",
        C["deadline_change"] in deadline["linked_changes"]
        and C["offsite_change"] in offsite["linked_changes"],
    )
    c.never("either event named as the cause", has(text, "caused by", "because of", "due to"))
    c.never(
        "a nearby record shown as linked",
        C["offsite_change"] in deadline["linked_changes"]
        or C["deadline_change"] in offsite["linked_changes"],
    )
    return c.result()


async def sustained_recovery() -> dict:
    c = Case("sustained_recovery")

    async def work(s, _):
        _, listed, _ = await s.call(
            "team_history", team_id=TEAM, metric="sleep_minutes", play="evening_boundary"
        )
        found = [x for x in listed["cases"] if x["dates"]["start"] == D["sustained"][0]]
        _, case, text = await s.call("team_case", team_id=TEAM, case_id=found[0]["case_id"])
        return case, text

    case, text = await with_session(c.name, work)
    outcome = case.get("outcome") or {}
    reference = outcome.get("reference") or {}
    c.must(
        "the comparison chosen when the action was saved, with its dates",
        case["tracking"]["comparison"] == "the 28 days before the change started"
        and reference.get("start")
        and reference.get("end")
        and outcome.get("during") == {"start": D["sustained"][0], "end": D["sustained"][1]},
    )
    c.must("the implementation status", case["implementation"].startswith("reported tried"))
    c.must("one of the four outcome labels", outcome.get("label") in LABELS)
    c.must(
        "cannot determine how much the action contributed",
        any(
            "cannot show how much the change itself contributed" in x
            for x in outcome.get("caveats", [])
        ),
    )
    c.never("the action caused the recovery", has(text, "caused the", "because of the change"))
    c.never("better", has(text, "better"))
    c.never("returned to baseline", has(text, "returned to baseline"))
    c.never("back to normal", has(text, "back to normal"))
    return c.result()


async def fresh_chat_and_scope() -> dict:
    c = Case("fresh_chat_and_scope")
    token = app_sign_in()
    drafted = db_rows("select id from team_actions where request_id = ?", REMEMBERED)
    app("POST", f"/teams/{TEAM}/actions/{dashed(drafted[0][0])}/approve", token)

    async def work(s, _):
        _, me, _ = await s.call("who_am_i")
        _, listed, _ = await s.call("team_history", team_id=TEAM, play="evening_boundary")
        saved = [
            x
            for x in listed["cases"]
            if x["dates"]["start"] == next_weekday(date.today(), 3).isoformat()
        ]
        opened = None
        if saved:
            _, opened, _ = await s.call("team_case", team_id=TEAM, case_id=saved[0]["case_id"])
        theirs = INST["teams"]["theirs"]
        refusals = [
            await s.call("team_history", team_id=theirs),
            await s.call("team_case", team_id=theirs, case_id=INST["changes"]["their_change"]),
            await s.call("team_overview", team_id=theirs),
        ]
        cross = await s.call("team_case", team_id=TEAM, case_id=INST["changes"]["their_change"])
        _, small, small_text = await s.call("team_overview", team_id=INST["teams"]["small"])
        return me, opened, refusals, cross, small, small_text

    me, opened, refusals, cross, small, small_text = await with_session(c.name, work)
    c.must(
        "the saved case found without chat memory",
        opened is not None
        and opened["decision"]["state"] == "approved"
        and opened["recorded"]["by"].startswith("suggested in chat")
        and opened["playbook_entry"] == "current",
    )
    c.must(
        "No such team for the other team",
        all(not ok and NO_TEAM in text for ok, _, text in refusals)
        and not cross[0]
        and INST["teams"]["theirs"] not in json.dumps(me),
    )
    c.must(
        "withheld figures stay withheld",
        small["report"]["state"] == "withheld"
        and not has(small_text, '"difference"', '"median"', '"changed": ['),
    )
    return c.result()


async def no_mcp_approval() -> dict:
    c = Case("no_mcp_approval")
    words = ("approve", "decline", "implementation", "tried", "delete", "edit", "update", "mark")

    async def work(s, session):
        tools = (await session.list_tools()).tools
        record = next(t for t in tools if t.name == "record_team_change")
        sneaked = await s.call(
            "record_team_change",
            team_id=TEAM,
            change={
                "request_id": "sneak-approved-0001",
                "play": "meeting_breaks",
                "starts_on": date.today().isoformat(),
                "ends_on": date.today().isoformat(),
                "status": "approved",
            },
        )
        return tools, record, sneaked

    tools, record, sneaked = await with_session(c.name, work)
    names = [t.name for t in tools]
    schema = json.dumps(record.input_schema)
    c.must(
        "no tool offers it",
        not any(w in n for n in names for w in words),
    )
    c.must(
        "record_team_change can only create a pending draft",
        '"status"' not in schema
        and '"implementation"' not in schema
        and not sneaked[0]
        and not db_rows(
            "select count(*) from team_actions where request_id = 'sneak-approved-0001'"
        )[0][0],
    )
    return c.result()


async def record_refusals() -> dict:
    c = Case("record_refusals")
    today = date.today().isoformat()
    before = db_rows("select count(*) from team_actions")[0][0]
    report_id, evidence = db_rows(
        "select id, evidence from team_reports where team_id = ? order by week_start desc",
        INST["teams"]["theirs"].replace("-", ""),
    )[0]
    # A real finding of the other supervisor's team: its report id and one of its evidence ids.
    their_finding = {
        "report_id": dashed(report_id),
        "evidence_id": next(iter(json.loads(evidence))),
    }
    base = {"play": "meeting_breaks", "starts_on": today, "ends_on": today}

    async def work(s, _):
        return [
            (
                "play",
                await s.call(
                    "record_team_change",
                    team_id=TEAM,
                    change=base | {"request_id": "refuse-custom-01", "play": "custom"},
                ),
            ),
            (
                "play",
                await s.call(
                    "record_team_change",
                    team_id=TEAM,
                    change=base | {"request_id": "refuse-unknown-1", "play": "four_day_week"},
                ),
            ),
            (
                "event_id",
                await s.call(
                    "record_team_change",
                    team_id=TEAM,
                    change=base
                    | {
                        "request_id": "refuse-event-001",
                        "event_id": INST["events"]["their_deadline"].split(":", 1)[1],
                    },
                ),
            ),
            (
                "finding",
                await s.call(
                    "record_team_change",
                    team_id=TEAM,
                    change=base | {"request_id": "refuse-finding-1", "finding": their_finding},
                ),
            ),
        ]

    answers = await with_session(c.name, work)
    c.must(
        "a refusal naming the field",
        all(not ok and field in text for field, (ok, _, text) in answers),
    )
    c.must("nothing stored", db_rows("select count(*) from team_actions")[0][0] == before)
    return c.result()


async def custom_change_shown() -> dict:
    c = Case("custom_change_shown")

    async def work(s, _):
        _, listed, t1 = await s.call("team_history", team_id=TEAM, play="custom")
        _, case, t2 = await s.call("team_case", team_id=TEAM, case_id=listed["cases"][0]["case_id"])
        _, overview, t3 = await s.call("team_overview", team_id=TEAM)
        return listed, case, t1 + t2 + t3

    listed, case, text = await with_session(c.name, work)
    outcome = case.get("outcome") or {}
    c.must(
        "Custom team change with its metric, dates, state and permitted outcome",
        len(listed["cases"]) == 1
        and case["title"] == "Custom team change"
        and case["tracking"]["metric"] == "sleep_minutes"
        and case["dates"]
        and case["decision"]["state"] == "approved"
        and outcome.get("label") in LABELS,
    )
    c.must(
        "the assistant can tell it cannot see exactly what it involved",
        "not shared through MCP" in case.get("custom_note", ""),
    )
    c.never("the title's words", has(text, *D["custom_words"], "Ease Sam"))
    c.never("a note's text", has(text, "late calls", "told me"))
    c.never("a member", has(text, "@example.com", "demo-cm"))
    c.never("a check-in", has(text, "check-in", "checkin"))
    return c.result()


async def as_of_vs_today() -> dict:
    c = Case("as_of_vs_today")
    C = INST["changes"]
    running_day = (date.fromisoformat(D["sustained"][0]) + timedelta(days=4)).isoformat()
    before_decline = db_rows(
        "select date(proposed_at) from team_actions where id = ?", hexid(C["declined"])
    )[0][0]
    friday = D["fridays"]["0"]

    async def work(s, _):
        then = await s.call("team_case", team_id=TEAM, case_id=C["recovery"], as_of=running_day)
        now = await s.call("team_case", team_id=TEAM, case_id=C["recovery"])
        d_then = await s.call(
            "team_case", team_id=TEAM, case_id=C["declined"], as_of=before_decline
        )
        d_now = await s.call("team_case", team_id=TEAM, case_id=C["declined"])
        t_then = await s.call("team_case", team_id=TEAM, case_id=C["deadline_change"], as_of=friday)
        t_now = await s.call("team_case", team_id=TEAM, case_id=C["deadline_change"])
        return then, now, d_then, d_now, t_then, t_now

    then, now, d_then, d_now, t_then, t_now = (x[1] for x in await with_session(c.name, work))
    c.must(
        "two separate answers",
        then["as_of"] == running_day and now["as_of"] == date.today().isoformat(),
    )
    c.must(
        "the earlier answer gives the state as it stood then",
        then["decision"]["state"] == "approved"
        and "not reported" in then["implementation"]
        and then.get("outcome") is None
        and d_then["decision"]["state"] == "pending"
        and "not reported" in t_then["implementation"]
        and now.get("outcome")
        and now["implementation"].startswith("reported tried")
        and d_now["decision"]["state"] == "declined"
        and t_now["implementation"].startswith("reported tried"),
    )
    c.never("a later result in the earlier answer", then.get("outcome") is not None)
    c.never(
        "a later confirmation or decline in the earlier answer",
        d_then["decision"]["state"] != "pending",
    )
    c.never(
        "a later tried or not-tried mark in the earlier answer",
        "reported" in then["implementation"].replace("not reported", "")
        or "reported" in t_then["implementation"].replace("not reported", ""),
    )
    return c.result()


FROZEN = [
    deadline_weekly_only,
    remember_decision,
    offsite_first_night,
    three_deadlines,
    overlapping_events,
    sustained_recovery,
    fresh_chat_and_scope,
    no_mcp_approval,
    record_refusals,
    custom_change_shown,
    as_of_vs_today,
]


# --- the review regressions (scored apart) ----------------------------------------------------


async def ends_on_required() -> dict:
    c = Case("ends_on_required")
    today = date.today().isoformat()

    async def work(s, _):
        change = {"request_id": "no-ends-on-0001", "play": "meeting_breaks", "starts_on": today}
        return await s.call("record_team_change", team_id=TEAM, change=change)

    ok, _, text = await with_session(c.name, work)
    c.must("refused, naming ends_on", not ok and "ends_on" in text)
    c.must(
        "nothing stored",
        not db_rows("select count(*) from team_actions where request_id = 'no-ends-on-0001'")[0][0],
    )
    return c.result()


async def tried_through_the_app() -> dict:
    """Answers given in the app reach a fresh MCP session each time; a correction or undo given
    today leaves yesterday's answer as it was on record."""
    c = Case("tried_through_the_app")
    token = app_sign_in()
    running = INST["changes"]["running"]
    path = f"/teams/{TEAM}/actions/{running.split(':', 1)[1]}/implementation"
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    seen = []
    for answer in (True, False, None):
        app("PUT", path, token, {"tried": answer})

        async def work(s, _):
            now = await s.call("team_case", team_id=TEAM, case_id=running)
            then = await s.call("team_case", team_id=TEAM, case_id=running, as_of=yesterday)
            return now[1]["implementation"], then[1]["implementation"]

        seen.append(await with_session(f"{c.name}:{answer}", work))
    c.must("Yes reads as tried in a fresh session", seen[0][0].startswith("reported tried"))
    c.must("the correction to No reads as not tried", seen[1][0].startswith("reported not tried"))
    c.must("the undo reads as not reported", "not reported" in seen[2][0])
    c.must("yesterday stays not reported throughout", all("not reported" in s[1] for s in seen))
    c.must(
        "every answer is kept as given",
        db_rows("select count(*) from team_action_marks where action_id = ?", hexid(running))[0][0]
        == 3,
    )
    return c.result()


async def late_report() -> dict:
    """The week the two-week change ended had its report made late: before then, no outcome and
    no report in any answer; today, both."""
    c = Case("late_report")
    C = INST["changes"]
    before = (date.fromisoformat(D["late_report_made"]) - timedelta(days=1)).isoformat()
    late_id = db_rows(
        "select id from team_reports where team_id = ? and week_start = ?",
        TEAM.replace("-", ""),
        D["late_week"],
    )[0][0]

    async def work(s, _):
        return (
            await s.call("team_case", team_id=TEAM, case_id=C["recovery"], as_of=before),
            await s.call("team_overview", team_id=TEAM, week=D["late_week"], as_of=before),
            await s.call("team_history", team_id=TEAM, as_of=before, metric="sleep_minutes"),
            await s.call("team_case", team_id=TEAM, case_id=C["recovery"]),
            await s.call("team_overview", team_id=TEAM, week=D["late_week"]),
        )

    case_then, overview_then, history_then, case_now, overview_now = await with_session(
        c.name, work
    )
    late = str(late_id)
    earlier = case_then[2] + overview_then[2] + history_then[2]
    c.must(
        "team_case before the report: no outcome, said so",
        case_then[1].get("outcome") is None and "No outcome was recorded by" in case_then[2],
    )
    c.must(
        "team_overview(week, as_of) before the report: no report by then",
        overview_then[1]["report"]["state"] == "no_report_by_then",
    )
    c.must(
        "team_history before the report: no outcome",
        all(
            x.get("outcome") is None
            for x in history_then[1]["cases"]
            if x["kind"] == "change" and x["dates"]["start"] == D["sustained"][0]
        ),
    )
    c.never("the late report's id in an earlier answer", dashed(late) in earlier or late in earlier)
    c.must(
        "today: the outcome and the report",
        case_now[1].get("outcome") and overview_now[1]["report"]["status"] == "ready",
    )
    return c.result()


async def every_filter_applies() -> dict:
    c = Case("every_filter_applies")

    async def work(s, _):
        return (
            await s.call("team_history", team_id=TEAM, category="deadline", play="meeting_breaks"),
            await s.call("team_history", team_id=TEAM, play="custom", metric="sleep_minutes"),
            await s.call("team_history", team_id=TEAM, category="travel", play="step_goal"),
        )

    both, custom, none_ = await with_session(c.name, work)
    C = INST["changes"]
    c.must(
        "deadline + meeting_breaks: the linked change only",
        [x["case_id"] for x in both[1]["cases"]] == [C["deadline_change"]],
    )
    c.must(
        "custom + sleep: the custom change only",
        [x["case_id"] for x in custom[1]["cases"]] == [C["custom"]],
    )
    c.must("travel + step_goal: nothing", none_[1]["cases"] == [])
    return c.result()


async def calendar_after_cutoff() -> dict:
    c = Case("calendar_after_cutoff")
    cutoff = D["fridays"]["1"]

    async def work(s, _):
        return (
            await s.call("team_overview", team_id=TEAM, as_of=cutoff),
            await s.call("team_overview", team_id=TEAM),
        )

    then, now = await with_session(c.name, work)

    def meeting_free(answer):
        return next(f for f in answer[1]["follow_up"] if f["title"] == "A meeting-free day")

    past, today = meeting_free(then), meeting_free(now)
    c.must(
        "past: no calendar check recorded by then, no followed flag",
        past.get("calendar_check") == f"No calendar check was recorded by {cutoff}."
        and "followed_on_the_calendar" not in past,
    )
    c.must("today: the calendar check and its flag", "followed_on_the_calendar" in today)
    return c.result()


REGRESSIONS = [
    ends_on_required,
    tried_through_the_app,
    late_report,
    every_filter_applies,
    calendar_after_cutoff,
]


async def run(label: str) -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    out: dict = {
        "label": label,
        "runner_commit": commit,
        # The server tested: this checkout unless a baseline from another revision is named.
        "server": os.environ.get("FA_SERVER_REVISION", f"this checkout, {commit}"),
        "instance_made": INST["made"],
        "frozen": {},
    }
    for case in FROZEN:
        try:
            out["frozen"][case.__name__] = await case()
        except Exception as error:  # noqa: BLE001 (a crash fails the case, with its kind only)
            out["frozen"][case.__name__] = {"passed": False, "error": type(error).__name__}
    out["regressions"] = {}
    for case in REGRESSIONS:
        try:
            out["regressions"][case.__name__] = await case()
        except Exception as error:  # noqa: BLE001
            out["regressions"][case.__name__] = {"passed": False, "error": type(error).__name__}
    passed = sum(r["passed"] for r in out["frozen"].values())
    regressions = sum(r["passed"] for r in out["regressions"].values())
    out["summary"] = {
        "frozen_passed": f"{passed}/{len(FROZEN)}",
        "regressions_passed": f"{regressions}/{len(REGRESSIONS)}",
        "mcp_calls": len(CALLS),
        "mcp_calls_refused": sum(not c["ok"] for c in CALLS),
    }
    for group in ("frozen", "regressions"):
        for name, r in out[group].items():
            print("PASS" if r["passed"] else "FAIL", name, r.get("error", ""))
            for check in r.get("checks", []):
                if not check["ok"]:
                    print("   failed:", check.get("must") or "never: " + check["never"])
    print(json.dumps(out["summary"]))
    path = Path(f"eval/results/change_memory_{label}_{date.today().isoformat()}.json")
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print("wrote", path)
    if passed < len(FROZEN) or regressions < len(REGRESSIONS):
        sys.exit(1)


if __name__ == "__main__":
    if sys.argv[1:2] == ["prepare"]:
        prepare()
    else:
        asyncio.run(run(sys.argv[2] if len(sys.argv) > 2 else "scripted"))
