"""The weekly team metric explorer on real people: every metric, every week, through the app and
MCP, checked against figures recomputed from the dataset files. Free, no model.

Run from the repository root (Sentry off):
    FA_SENTRY_DSN= PYTHONPATH=backend:eval python eval/explorer_real.py

Fixed before the first run (2026-11-28), on the teams frozen by `eval/varied_teams.py` (its spec
and assignment hashes are checked first): LifeSnaps teams of 3, 4, 5, 6, 9, 11 and 13 people and
PMData teams of 1, 4, 5 and 6, 67 people, no one in two teams, every Monday-to-Sunday week from
28 days after a dataset's first day to its last.

- **Two arms, each its own database.**
  - `recorded`: everyone's days as the dataset has them; everyone joined before the first day.
  - `staggered`: each person's days begin 0, 7, 14, 21, 28, 35 or 42 days after the dataset's
    first day (drawn once per person with `SEED`), so a team mixes long and short histories and
    people cross the 14-day baseline minimum week by week. In every team of 5 or more, one
    person (drawn with `SEED`) leaves three quarters of the way through the weeks.
- **How the figures are made, as in production.** Weeks run in order, each with its report made
  by the weekly job's code (`reports.build_report`) on the Monday after, 06:00 UTC. From the
  middle week on, the job also stores the explorer's figures right after the report, as
  `python -m app.teams weekly` does; the weeks before stand for those reported before the
  explorer existed, so their figures are first made when someone opens them. After the last
  week, the supervisor opens every week through both the app API and the MCP server, the app
  first on even weeks and MCP first on odd ones, the list and then every metric's evidence.
- **Checks, pass or fail.**
  - The app and MCP agree on every week's state, roster, people with data and day made, and on
    every metric's state, evidence id, contributors, change and withheld text, in the list and
    the evidence.
  - Every metric's figure matches one recomputed from the dataset files with the Python
    standard library (no pandas, no app code): each contributor's mean over the week minus their
    mean over the 28 days before, with at least 4 and 14 days, and the median over contributors,
    shown only from 5 people; the contributors, and the counts higher, lower and the same. The
    contributors are the people in the team when the week's report was made, less anyone who
    has left since the figures were made. Zeros that cannot be real (steps, time asleep and in
    bed, resting heart rate, HRV) are missing, as in `eval/real_data.py`; neither dataset
    records wear time, so no day is dropped as barely worn. The three scores are computed by
    the app from several inputs and are not recomputed; neither dataset has heart-rate zone
    minutes, so those must show no data.
  - Coverage: the roster is the team at the report, people with data never exceed it, no
    figure is from fewer than 5 people, and every reported week is offered.
  - Privacy: no member's email in anything either interface returns, and the evidence carries
    only the counts and the median (no per-person values, no quartiles).
  - A later sync cannot change a shown figure: every member's days in each team's first three
    weeks with a steps figure are rewritten (steps doubled, 90 more minutes asleep), both
    interfaces are read again and must return exactly what they did, while a fresh computation
    from the rewritten days must differ (so the check could fail).
  - With the report (`recorded` arm, where the report and the explorer read the same people):
    for each metric in both, the explorer never counts fewer people than the report (the report
    also needs a non-zero spread before), and when they count the same people, the medians
    match.
- **Counted, not pass or fail.** Figures, withheld and no-data rows per arm; metrics at 4 and at
  5 contributors (the minimum's boundary); and, where the report says a metric changed, whether
  the explorer's median moved the same way (the report tests the mean of standardized changes,
  the explorer shows the median raw change, so they can disagree).

Writes aggregates only to `eval/results/explorer_real_<date>.json` and the per-case records to the
git-ignored `data/eval/explorer_real/`. Prints pass or fail per check and exits 1 on any failure.
The datasets: see `eval/varied_teams.py`.
"""

import asyncio
import contextlib
import json
import logging
import math
import os
import random
import re
import statistics
import subprocess
import sys
import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import real_data
import varied_teams as vt

HERE = Path(__file__).parent
PRIVATE = Path("data/eval/explorer_real")
SEED = 20261128
OFFSETS = (0, 7, 14, 21, 28, 35, 42)
ARMS = ("recorded", "staggered")
DOMAIN = "research.example.org"
BASELINE_DAYS = 28
SCORES = ("recovery_score", "strain", "stress_score")
ZONES = tuple(f"hr_zone_{z}_minutes" for z in ("light", "moderate", "vigorous", "peak"))
NEVER_ZERO = ("steps", "sleep_minutes", "time_in_bed", "hrv_ms", "resting_hr")
# What the evidence may hold: counts and the median, nothing per person.
STATS_KEYS = {
    "members",
    "minimum_members",
    "descriptive",
    "median_change",
    "members_up",
    "members_down",
    "members_unchanged",
}


# --- the dataset files, read again with the standard library -----------------------------------


def _num(text) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) else value


def _put(days: dict, day: date, metric: str, value: float | None) -> None:
    if value is None or (metric in NEVER_ZERO and value == 0):
        return
    days.setdefault(day, {})[metric] = value


def ls_source() -> dict[str, dict[date, dict[str, float]]]:
    import csv

    direct = {
        "minutesAsleep": ("sleep_minutes", 1.0),
        "sleep_duration": ("time_in_bed", 1 / 60_000),
        "minutesAwake": ("awake_in_bed_minutes", 1.0),
        "sleep_efficiency": ("sleep_efficiency", 1.0),
        "steps": ("steps", 1.0),
        "distance": ("distance_km", 1 / 1000),
        "calories": ("calories", 1.0),
        "resting_hr": ("resting_hr", 1.0),
        "rmssd": ("hrv_ms", 1.0),
        "lightly_active_minutes": ("lightly_active_minutes", 1.0),
        "moderately_active_minutes": ("moderately_active_minutes", 1.0),
        "very_active_minutes": ("very_active_minutes", 1.0),
    }
    out: dict[str, dict] = {}
    path = real_data.LIFESNAPS / "daily_fitbit_sema_df_unprocessed.csv"
    seen: set[tuple[str, date]] = set()
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            pid = f"ls_{row['id'][-6:]}"
            day = date.fromisoformat(row["date"][:10])
            if (pid, day) in seen:
                continue  # a day's first row only, as `real_data` keeps it
            seen.add((pid, day))
            days = out.setdefault(pid, {})
            for column, (metric, factor) in direct.items():
                value = _num(row[column])
                _put(days, day, metric, None if value is None else value * factor)
            z = [_num(row[f"minutes_in_default_zone_{n}"]) for n in (1, 2, 3)]
            if all(v is not None for v in z):
                _put(days, day, "active_zone_minutes", z[0] + 2 * (z[1] + z[2]))
    return out


def _sums(path: Path, divide: float = 1.0) -> dict[date, float]:
    found: dict[date, float] = {}
    for row in vt._rows(path):
        value = _num(row["value"])
        day = vt._day(row["dateTime"])
        found[day] = found.get(day, 0.0) + (value or 0.0)
    return {d: v / divide for d, v in found.items()}


def _last(path: Path) -> dict[date, float]:
    found: dict[date, float] = {}
    for row in vt._rows(path):
        value = _num(row["value"])
        day = vt._day(row["dateTime"])
        if value is not None:  # as pandas' groupby last(), which skips a missing value
            found[day] = value
    return found


def pm_source() -> dict[str, dict[date, dict[str, float]]]:
    out: dict[str, dict] = {}
    for folder in sorted(p for p in real_data.PMDATA.glob("p[0-9]*") if p.is_dir()):
        fitbit = folder / "fitbit"
        days: dict[date, dict] = {}
        for day, v in _sums(fitbit / "steps.json").items():
            _put(days, day, "steps", v)
        for day, v in _sums(fitbit / "calories.json").items():
            _put(days, day, "calories", v)
        for day, v in _sums(fitbit / "distance.json", 100_000).items():
            _put(days, day, "distance_km", v)
        for row in vt._rows(fitbit / "resting_heart_rate.json"):
            value = (row.get("value") or {}).get("value")
            if value:
                _put(days, vt._day(row["dateTime"]), "resting_hr", float(value))
        for name in ("lightly", "moderately", "very"):
            for day, v in _last(fitbit / f"{name}_active_minutes.json").items():
                _put(days, day, f"{name}_active_minutes", v)
        for row in vt._rows(fitbit / "time_in_heart_rate_zones.json"):
            zones = (row.get("value") or {}).get("valuesInZones") or {}
            weighted = zones.get("IN_DEFAULT_ZONE_1", 0) + 2 * (
                zones.get("IN_DEFAULT_ZONE_2", 0) + zones.get("IN_DEFAULT_ZONE_3", 0)
            )
            _put(days, vt._day(row["dateTime"]), "active_zone_minutes", float(weighted))
        nights: dict[date, dict] = {}
        for row in vt._rows(fitbit / "sleep.json"):
            if not row.get("mainSleep"):
                continue
            stages = (row.get("levels") or {}).get("summary") or {}
            clock = row["startTime"][11:16]
            hour = int(clock[:2]) + int(clock[3:]) / 60
            nights[date.fromisoformat(row["dateOfSleep"])] = {  # a later one on a date wins
                "sleep_minutes": _num(row.get("minutesAsleep")),
                "time_in_bed": _num(row.get("timeInBed")),
                "sleep_efficiency": _num(row.get("efficiency")),
                "awake_in_bed_minutes": _num(row.get("minutesAwake")),
                "bedtime_hour": hour - 24 if hour >= 12 else hour,
                "deep_sleep_minutes": _num((stages.get("deep") or {}).get("minutes")),
                "light_sleep_minutes": _num((stages.get("light") or {}).get("minutes")),
                "rem_sleep_minutes": _num((stages.get("rem") or {}).get("minutes")),
            }
        for day, values in nights.items():
            for metric, v in values.items():
                _put(days, day, metric, v)
        out[folder.name] = days
    return out


def expected(
    days_of: dict, members: list[str], metric: str, week: date, starts: dict[str, date]
) -> dict:
    """The explorer's figure for `metric`, worked out again from the source days."""
    changes = []
    for pid in members:
        days, first = days_of.get(pid, {}), starts.get(pid, date.min)

        def values(begin: date, n: int, days=days, first=first) -> list[float]:
            got = []
            for i in range(n):
                day = begin + timedelta(days=i)
                if day >= first and (v := days.get(day, {}).get(metric)) is not None:
                    got.append(v)
            return got

        recent = values(week, 7)
        before = values(week - timedelta(days=BASELINE_DAYS), BASELINE_DAYS)
        if len(recent) >= 4 and len(before) >= 14:
            changes.append(statistics.fmean(recent) - statistics.fmean(before))
    out = {"n": len(changes), "sufficient": len(changes) >= 5}
    if out["sufficient"]:
        out |= {
            "median": statistics.median(changes),
            "up": sum(c > 0 for c in changes),
            "down": sum(c < 0 for c in changes),
            "same": sum(c == 0 for c in changes),
        }
    return out


# --- the two interfaces -------------------------------------------------------------------------


def _snake(value):
    """The app's JSON in MCP's key style (the API writes camelCase)."""
    if isinstance(value, dict):
        return {re.sub(r"(?<!^)([A-Z])", r"_\1", k).lower(): _snake(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_snake(v) for v in value]
    return value


class Interfaces:
    """The app API (as the supervisor, signed in) and the MCP server's tools (as the same
    account), over one database."""

    def __init__(self, engine, boss_email: str, now: datetime) -> None:
        from fastapi.testclient import TestClient
        from sqlalchemy import select

        from app.api import auth
        from app.api.main import create_app
        from app.auth import accounts
        from app.db.models import User
        from app.db.session import session_scope
        from app.harness import server as mcp_server

        app = create_app()

        def db():
            with session_scope(engine) as session:
                yield session

        app.dependency_overrides[auth.get_db] = db
        app.dependency_overrides[auth.now] = lambda: now
        self.client = TestClient(app)
        with session_scope(engine) as session:
            boss = session.scalar(select(User).where(User.email == boss_email))
            accounts.set_password(session, boss, "correct horse battery")
            self.boss_id = boss.id
        token = self.client.post(
            "/auth/login", json={"email": boss_email, "password": "correct horse battery"}
        ).json()["token"]
        self.headers = {"Authorization": f"Bearer {token}"}
        self.mcp = mcp_server.build(lambda: session_scope(engine), "https://api.example")
        # The 60-a-minute limit guards production against a harness in a loop; this run reads
        # every metric of every week on purpose, so it lifts the limit for itself only.
        mcp_server.limits.per_minute = 10**9

    def app_list(self, team_id: str, week: str) -> dict:
        r = self.client.get(
            f"/teams/{team_id}/metrics", params={"week": week}, headers=self.headers
        )
        assert r.status_code == 200, (r.status_code, r.text[:200])
        return _snake(r.json())

    def app_metric(self, team_id: str, week: str, metric: str) -> dict:
        r = self.client.get(f"/teams/{team_id}/metrics/{week}/{metric}", headers=self.headers)
        assert r.status_code == 200, (r.status_code, r.text[:200])
        return _snake(r.json())

    def _call(self, tool: str, **arguments) -> dict:
        from mcp.server.auth.middleware.auth_context import auth_context_var
        from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
        from mcp.server.auth.provider import AccessToken

        async def run():
            handle = auth_context_var.set(
                AuthenticatedUser(
                    AccessToken(
                        token="", client_id="eval", scopes=[], subject=str(self.boss_id), claims={}
                    )
                )
            )
            try:
                return await self.mcp.call_tool(tool, arguments)
            finally:
                auth_context_var.reset(handle)

        result = asyncio.run(run())
        assert not result.is_error, " ".join(getattr(c, "text", "") for c in result.content)
        structured = result.structured_content
        if structured is None:
            structured = json.loads(" ".join(getattr(c, "text", "") for c in result.content))
        if isinstance(structured, dict) and set(structured) == {"result"}:
            structured = structured["result"]
        return structured

    def mcp_list(self, team_id: str, week: str) -> dict:
        return self._call("team_metrics", team_id=team_id, week=week)

    def mcp_metric(self, team_id: str, week: str, metric: str) -> dict:
        return self._call("team_metric", team_id=team_id, week=week, metric=metric)


def _list_view(listing: dict) -> dict:
    """What both interfaces must agree on in a week's list (not `weeks`: each has its own today)."""
    rows = {
        m["metric"]: {
            k: m.get(k) for k in ("state", "evidence_id", "contributors", "change", "withheld")
        }
        for c in listing.get("categories") or []
        for g in c["subgroups"]
        for m in g["metrics"]
    }
    head = {k: listing.get(k) for k in ("state", "roster", "members_with_data", "made_on", "week")}
    return head | {"rows": rows}


EVIDENCE_KEYS = (
    "state",
    "evidence_id",
    "change",
    "higher",
    "lower",
    "unchanged",
    "coverage",
    "withheld",
    "week",
    "baseline",
    "made_on",
)


def _metric_view(record: dict) -> dict:
    return {k: record.get(k) for k in EVIDENCE_KEYS}


def read_week(ui: Interfaces, team_id: str, week: str, app_first: bool) -> dict:
    """Both interfaces' list and every metric's evidence, in the order given."""
    from app.teams.explorer import CATALOG

    out = {}
    order = ("app", "mcp") if app_first else ("mcp", "app")
    for side in order:
        listing = ui.app_list(team_id, week) if side == "app" else ui.mcp_list(team_id, week)
        out[side] = {"list": listing, "metrics": {}}
    for metric in CATALOG:
        for side in order:
            get = ui.app_metric if side == "app" else ui.mcp_metric
            out[side]["metrics"][metric.key] = get(team_id, week, metric.key)
    return out


# --- one arm ------------------------------------------------------------------------------------


class Checks:
    def __init__(self) -> None:
        self.counts: Counter = Counter()
        self.failures: dict[str, list] = defaultdict(list)

    def check(self, name: str, ok: bool, case=None) -> None:
        self.counts[(name, ok)] += 1
        if not ok and len(self.failures[name]) < 5:
            self.failures[name].append(case)

    def summary(self) -> dict:
        names = sorted({n for n, _ in self.counts})
        return {
            n: f"{self.counts[(n, True)]}/{self.counts[(n, True)] + self.counts[(n, False)]}"
            for n in names
        }

    @property
    def failed(self) -> int:
        return sum(v for (n, ok), v in self.counts.items() if not ok)


def run_arm(arm: str, data: dict, spec: dict, teams: dict, source: dict) -> dict:
    PRIVATE.mkdir(parents=True, exist_ok=True)
    db_path = PRIVATE / f"{arm}.db"
    db_path.unlink(missing_ok=True)
    url = f"sqlite:///{db_path.resolve()}"
    subprocess.run(
        ["alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
        check=True,
        capture_output=True,
        env={**os.environ, "FA_DATABASE_URL": url},
    )
    import pandas as pd
    from sqlalchemy import create_engine, event, select

    from app.analysis.team import week_of
    from app.db.daily import load_daily, save_daily
    from app.db.models import Team, TeamReport, User
    from app.db.session import session_scope
    from app.teams import explorer, memberships, reports

    engine = create_engine(url)
    event.listen(engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
    rng = random.Random(SEED)
    checks, cases = Checks(), []
    tally: Counter = Counter()
    direction: Counter = Counter()

    for name, ids in teams.items():
        dataset = name.split("-")[0]
        weeks = spec["weeks"][dataset]
        first_day = min(data[dataset][p].index.min().date() for p in ids)
        starts = {p: first_day for p in ids}
        leaver = None
        if arm == "staggered":
            starts = {p: first_day + timedelta(days=rng.choice(OFFSETS)) for p in ids}
            if len(ids) >= 5:
                leaver = rng.choice(ids)
        deploy, leave_at = len(weeks) // 2, (3 * len(weeks)) // 4
        boss_email = f"explorer-{arm}-{name}@{DOMAIN}"
        joined = datetime.combine(first_day - timedelta(days=1), datetime.min.time(), UTC)
        users: dict[str, uuid.UUID] = {}
        with session_scope(engine) as db:
            boss = User(email=boss_email, status="approved", role="supervisor")
            db.add(boss)
            db.flush()
            team = memberships.create_team(
                db, boss, f"Explorer {arm} {name} (real data)", None, joined
            )
            team_id = str(team.id)
            for pid in ids:
                person = User(email=f"{arm}-{pid}@{DOMAIN}", status="approved")
                db.add(person)
                db.flush()
                frame = data[dataset][pid]
                frame = frame.loc[pd.Timestamp(starts[pid]) :].dropna(how="all")
                save_daily(db, person.id, reports.SOURCE, frame)
                memberships.join(db, team, person, joined)
                users[pid] = person.id
        # The weekly job, week by week.
        made_by_job = {}
        for i, start in enumerate(weeks):
            week = week_of(date.fromisoformat(start))
            job = datetime.combine(week.end + timedelta(days=1), datetime.min.time(), UTC)
            job += timedelta(hours=6)
            with session_scope(engine) as db:
                team = db.get(Team, uuid.UUID(team_id))
                if leaver and i == leave_at:
                    person = db.get(User, users[leaver])
                    memberships.leave(db, person, team_id, job - timedelta(hours=12))
                reports.build_report(db, team, week, job)
                if i >= deploy:
                    with db.begin_nested():
                        explorer.week_figures(db, team, week, job)
                    made_by_job[start] = job
        end = datetime.combine(
            date.fromisoformat(weeks[-1]) + timedelta(days=9), datetime.min.time(), UTC
        )
        ui = Interfaces(engine, boss_email, end)
        emails = {f"{arm}-{pid}@{DOMAIN}" for pid in ids}

        first_reads = {}
        for i, start in enumerate(weeks):
            app_first = i % 2 == 0
            got = read_week(ui, team_id, start, app_first)
            first_reads[start] = got
            app, mcp = got["app"], got["mcp"]
            case_id = f"{arm}/{name}/{start}"
            # Who the week's figures describe, worked out from the timeline above.
            cut_has_leaver = leaver is not None and i < leave_at
            roster = len(ids) - (0 if leaver is None or cut_has_leaver else 1)
            job_made = start in made_by_job
            # A leaver counts only in figures the job made before they left.
            counted = [p for p in ids if p != leaver or (job_made and cut_has_leaver)]
            listing = app["list"]
            checks.check("state ready", listing["state"] == "ready", case_id)
            checks.check(
                "app and MCP list agree",
                _list_view(app["list"]) == _list_view(mcp["list"]),
                case_id,
            )
            checks.check("roster at the report", listing.get("roster") == roster, case_id)
            checks.check(
                "with data within the roster",
                (listing.get("members_with_data") or 0) <= (listing.get("roster") or 0),
                case_id,
            )
            checks.check("the week is offered", start in listing.get("weeks", []), case_id)
            blob = json.dumps(got)
            checks.check("no member email", not any(e in blob for e in emails), case_id)
            rows = _list_view(listing)["rows"]
            with session_scope(engine) as db:
                stored = explorer._stored(
                    db, db.get(Team, uuid.UUID(team_id)), week_of(date.fromisoformat(start))
                )
                results = dict(stored.results)
                report = db.scalar(
                    select(TeamReport).where(
                        TeamReport.team_id == uuid.UUID(team_id),
                        TeamReport.week_start == date.fromisoformat(start),
                    )
                )
                report_evidence = dict(report.evidence or {})
                sections = list((report.body or {}).get("sections", []))
            for key, record in results.items():
                checks.check(
                    "evidence holds counts and the median only",
                    set(record["stats"]) <= STATS_KEYS,
                    (case_id, key),
                )
            for metric, row in rows.items():
                a, m = app["metrics"][metric], mcp["metrics"][metric]
                checks.check(
                    "app and MCP evidence agree",
                    _metric_view(a) == _metric_view(m),
                    (case_id, metric),
                )
                checks.check(
                    "list and evidence agree",
                    a["evidence_id"] == row["evidence_id"] and a["state"] == row["state"],
                    (case_id, metric),
                )
                n = row["contributors"]
                tally[(row["state"])] += 1
                if n in (4, 5):
                    tally[f"at_{n}"] += 1
                checks.check(
                    "a figure only from 5 or more",
                    (row["state"] == "figure") == (n >= 5) and (n > 0 or row["state"] == "no_data"),
                    (case_id, metric),
                )
                checks.check(
                    "contributors within the roster",
                    n <= (listing.get("roster") or 0),
                    (case_id, metric),
                )
                if metric in SCORES:
                    continue
                if metric in ZONES:
                    checks.check("no zone minutes in these datasets", n == 0, (case_id, metric))
                    continue
                truth = expected(
                    source[dataset], counted, metric, date.fromisoformat(start), starts
                )
                record = results[metric]
                ok = truth["n"] == record["n"] and truth["sufficient"] == record["sufficient"]
                if ok and truth["sufficient"]:
                    stats = record["stats"]
                    ok = (
                        abs(truth["median"] - stats["median_change"]) <= 0.0051
                        and truth["up"] == stats["members_up"]
                        and truth["down"] == stats["members_down"]
                        and truth["same"] == stats["members_unchanged"]
                    )
                checks.check(
                    f"recompute agrees: {metric}", ok, (case_id, metric, truth["n"], record["n"])
                )
                checks.check("recompute agrees (all metrics)", ok, (case_id, metric))
            # With the report, in the arm where both read the same people.
            if arm == "recorded":
                for s in sections:
                    eid = s.get("evidence_id")
                    ev = report_evidence.get(eid) if eid else None
                    if not ev or s["metric"] not in results:
                        continue
                    mine = results[s["metric"]]
                    rn = (ev.get("stats") or {}).get("members", ev.get("n"))
                    checks.check(
                        "explorer counts at least the report's people",
                        mine["n"] >= (rn or 0),
                        (case_id, s["metric"], rn, mine["n"]),
                    )
                    r_med = (ev.get("stats") or {}).get("median_change")
                    if rn == mine["n"] and mine["sufficient"] and r_med is not None:
                        checks.check(
                            "same people, same median as the report",
                            abs(r_med - mine["stats"]["median_change"]) <= 0.0051,
                            (case_id, s["metric"]),
                        )
                    if s.get("status") == "changed" and mine["sufficient"]:
                        way = (ev.get("stats") or {}).get("mean_standardized_change")
                        med = mine["stats"]["median_change"]
                        if way is not None and med != 0:
                            direction["same way" if (way > 0) == (med > 0) else "opposite"] += 1
            cases.append(
                {
                    "case": case_id,
                    "roster": listing.get("roster"),
                    "with_data": listing.get("members_with_data"),
                    "made_by": "job" if job_made else ("app" if app_first else "mcp"),
                    "states": Counter(r["state"] for r in rows.values()),
                    "leaver_counted": leaver is not None and leaver in counted,
                }
            )
            tally["team_weeks"] += 1
            tally["made_by_" + ("job" if job_made else ("app" if app_first else "mcp"))] += 1
            tally["reads"] += 2 * (1 + len(rows))

        # A later sync rewrites every member's days in the first three weeks with a steps
        # figure (steps doubled, 90 more minutes asleep), which moves every member's change.
        changed = [
            w for w in weeks if first_reads[w]["mcp"]["metrics"]["steps"]["state"] == "figure"
        ][:3]
        with session_scope(engine) as db:
            for uid in users.values():
                frame = load_daily(db, uid, reports.SOURCE)
                for start in changed:
                    lo = pd.Timestamp(start)
                    part = frame.loc[lo : lo + pd.Timedelta(days=6)].copy()
                    if part.empty:
                        continue
                    if "steps" in part:
                        part["steps"] = part["steps"] * 2
                    if "sleep_minutes" in part:
                        part["sleep_minutes"] = part["sleep_minutes"] + 90
                    save_daily(db, uid, reports.SOURCE, part)
        for start in changed:
            again = read_week(ui, team_id, start, app_first=True)
            before = first_reads[start]
            same = all(
                _list_view(again[s]["list"]) == _list_view(before[s]["list"])
                and all(
                    _metric_view(again[s]["metrics"][k]) == _metric_view(before[s]["metrics"][k])
                    for k in before[s]["metrics"]
                )
                for s in ("app", "mcp")
            )
            checks.check("a later sync leaves shown figures as they were", same, (arm, name, start))
            with session_scope(engine) as db:
                team = db.get(Team, uuid.UUID(team_id))
                week = week_of(date.fromisoformat(start))
                _, eligible = explorer.historical_roster(
                    db, team, explorer.roster_cutoff(db, team, week)
                )
                frames = [
                    f
                    for u in eligible
                    if not (
                        f := load_daily(
                            db,
                            u,
                            reports.SOURCE,
                            week.start - timedelta(days=reports.HISTORY_DAYS),
                            week.end + timedelta(days=1),
                        )
                    ).empty
                ]
                fresh = {
                    k: e.model_dump(mode="json") for k, e in explorer.compute(frames, week).items()
                }
                stored = explorer._stored(db, team, week).results
            moved = any(
                (fresh[k]["stats"].get("median_change"), fresh[k]["n"])
                != (stored[k]["stats"].get("median_change"), stored[k]["n"])
                for k in ("steps", "sleep_minutes")
            )
            checks.check("a fresh computation would differ", moved, (arm, name, start))
        print(f"{arm} {name}: {len(weeks)} weeks, failures so far {checks.failed}", flush=True)

    PRIVATE.mkdir(parents=True, exist_ok=True)
    with (PRIVATE / f"{arm}_cases.jsonl").open("w") as handle:
        for case in cases:
            handle.write(json.dumps(case, default=dict) + "\n")
    return {
        "checks": checks.summary(),
        "failures": {k: [str(c) for c in v] for k, v in checks.failures.items()},
        "failed": checks.failed,
        "counts": dict(tally),
        "report_vs_explorer_direction": dict(direction),
    }


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    data = vt.people()
    spec, teams = vt._check_frozen(data)
    PRIVATE.mkdir(parents=True, exist_ok=True)
    source = {"lifesnaps": ls_source(), "pmdata": pm_source()}
    out = {"spec_sha256": vt._hash(spec), "teams": {k: len(v) for k, v in teams.items()}}
    failed = 0
    for arm in ARMS:
        out[arm] = run_arm(arm, data, spec, teams, source)
        failed += out[arm]["failed"]
        for name, result in out[arm]["checks"].items():
            got, total = result.split("/")
            print(("PASS " if got == total else "FAIL ") + f"{arm}: {name} {result}")
    out["commit"] = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], check=False, capture_output=True, text=True
    ).stdout.strip()
    path = HERE / "results" / f"explorer_real_{date.today().isoformat()}.json"
    path.write_text(json.dumps(out, indent=1, default=str) + "\n")
    print("written", path)
    with contextlib.suppress(Exception):
        sys.stdout.flush()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
