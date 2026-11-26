"""Varied team sizes on real people: what a supervisor would see, week by week. Free, no model.

Run from the repository root:
    PYTHONPATH=backend:eval python eval/varied_teams.py freeze   # once, before any outcome
    PYTHONPATH=backend:eval python eval/varied_teams.py run      # checks the freeze, then runs

`freeze` writes `eval/varied_teams_spec.json` (committed before the first run: the rules below, the
dataset versions, the windows and a SHA-256 of the assignment) and the assignment itself to the
git-ignored `data/eval/varied_teams/`. `run` refuses unless the data and the assignment still hash
to the frozen values. It writes aggregate results to `eval/results/varied_teams_<date>.json` and the
per-case outputs (team figures from at least 5 people, never a person's values) to
`data/eval/varied_teams/`.

Fixed before the first run (2026-11-26):

- **People**: LifeSnaps, everyone with at least 28 days of sleep and steps (`real_data.enough`);
  PMData, all 16 participants as they are, including one with less data than that, since a real
  roster has such people. No one is left out, and no one is in two teams.
- **Teams**: the sorted ids of each dataset shuffled with `SEED`, then cut in the order of
  `SIZES`: LifeSnaps into 3, 4, 5, 6, 9, 11 and 13; PMData into 1, 4, 5 and 6. Eleven teams, each
  with its own research supervisor account, so no two teams share a supervisor or a person.
- **Weeks**: per dataset, every Monday-to-Sunday week starting at least 28 days after the
  dataset's earliest day and ending by its latest day. Original dates are kept; missing readings
  stay missing (zeros that cannot be real are already missing in `real_data`).
- **Each team-week**: members joined before the dataset's first day; the report is made with the
  production code (`reports.build_report`) as of the Monday after the week, then briefed
  (`briefing.brief`) with a stub in place of the model. The stub refuses every call, so the
  briefing falls back to the code's own ranking: the deterministic path. A case where a live
  model would choose the highlights (more than one priority) is counted as such. Each team-week
  is briefed on its own: a proposal it makes is recorded, then removed, so an unanswered
  suggestion never blocks the next week's.
- **Outcomes**: withheld (no metric from 5 people); ready-quiet (no section changed and no
  priority); ready-partial (at least one metric withheld for too few contributors); ready-full
  (every team metric from at least 5 people). A week can be both quiet and partial; both are
  counted.
- **Contributors**: per metric, the people the report used (the evidence's n), against the
  roster. The 4-to-5 boundary is counted where it occurs naturally.
- **Independent recompute**: time asleep, steps and resting heart rate are recomputed for every
  reported section from the source files with the Python standard library (no pandas, no app
  code): each member's mean over the week minus their mean over the 28 days before, with at least
  4 and 14 days, a non-zero spread before, and the median over members. It must match the stored
  figure (to the stored rounding) and its number of members.
- **Objective checks on each briefing and on the fixed-order report** (every section in the
  report's order): numbers in the text match their evidence; every cited evidence id exists in
  the report; the evidence is for this week; no causal wording; no member's email in any text;
  every figure from at least 5 people; a briefing for every ready report and none for a withheld
  one.
- **Cases for the rubric**: the teams are split once, by `SEED`, into rubric-development teams
  and reserved teams, so no person is in both. Reserved cases are scored for relevance and
  action only after the rubric is final.

Datasets: LifeSnaps (Yfantidou et al., Scientific Data 2022; CC BY 4.0;
https://zenodo.org/records/7229547) and PMData (Thambawita et al., MMSys 2020; CC BY 4.0;
https://datasets.simula.no/pmdata/). Neither records wear time, workplace relationships or a
calendar: the teams are formed by us, not real teams, and no calendar line can appear.
"""

import csv
import hashlib
import json
import math
import random
import re
import statistics
import subprocess
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import real_data

HERE = Path(__file__).parent
SPEC = HERE / "varied_teams_spec.json"
PRIVATE = Path("data/eval/varied_teams")
SEED = 20261126
SIZES = {"lifesnaps": [3, 4, 5, 6, 9, 11, 13], "pmdata": [1, 4, 5, 6]}
BASELINE_DAYS = 28
RUBRIC_TEAMS = (
    3  # teams held for designing the rubric; the rest are reserved for scoring
)
RECOMPUTED = ("sleep_minutes", "steps", "resting_hr")


# --- freezing -------------------------------------------------------------------------------


def _sha(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(real_data.ROOT)).encode())
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    return digest.hexdigest()


def dataset_versions() -> dict:
    return {
        "lifesnaps": _sha(
            [real_data.LIFESNAPS / "daily_fitbit_sema_df_unprocessed.csv"]
        ),
        "pmdata": _sha(sorted(real_data.PMDATA.glob("p[0-9]*/fitbit/*.json"))),
    }


def people() -> dict[str, dict]:
    return {"lifesnaps": real_data.load_lifesnaps(), "pmdata": real_data.load_pmdata()}


def assign(ids: dict[str, list[str]]) -> dict[str, list[str]]:
    teams = {}
    for dataset, sizes in SIZES.items():
        order = sorted(ids[dataset])
        assert len(order) == sum(sizes), (dataset, len(order), sum(sizes))
        random.Random(SEED).shuffle(order)
        start = 0
        for size in sizes:
            teams[f"{dataset}-{size}"] = sorted(order[start : start + size])
            start += size
    return teams


def windows(frames: dict) -> list[str]:
    first = min(f.index.min().date() for f in frames.values()) + timedelta(
        days=BASELINE_DAYS
    )
    last = max(f.index.max().date() for f in frames.values())
    monday = first + timedelta(days=(7 - first.weekday()) % 7)
    weeks = []
    while monday + timedelta(days=6) <= last:
        weeks.append(monday.isoformat())
        monday += timedelta(days=7)
    return weeks


def rubric_split(teams: list[str]) -> dict[str, list[str]]:
    eligible = sorted(
        t for t in teams if int(t.split("-")[1]) >= 5
    )  # only these can be ready
    chosen = sorted(random.Random(SEED + 1).sample(eligible, RUBRIC_TEAMS))
    return {
        "rubric_development": chosen,
        "reserved": [t for t in eligible if t not in chosen],
    }


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def freeze() -> None:
    data = people()
    teams = assign({k: list(v) for k, v in data.items()})
    spec = {
        "frozen": date.today().isoformat(),
        "seed": SEED,
        "sizes": SIZES,
        "people": {k: len(v) for k, v in data.items()},
        "people_with_28_days": {
            k: sum(real_data.enough(f) for f in v.values()) for k, v in data.items()
        },
        "teams": {name: len(ids) for name, ids in teams.items()},
        "assignment_sha256": _hash(teams),
        "weeks": {k: windows(v) for k, v in data.items()},
        "cases": rubric_split(list(teams)),
        "datasets": {
            "lifesnaps": "Yfantidou et al. 2022, Scientific Data; CC BY 4.0; zenodo.org/records/7229547",
            "pmdata": "Thambawita et al. 2020, MMSys; CC BY 4.0; datasets.simula.no/pmdata",
        },
        "dataset_sha256": dataset_versions(),
        "rules": "the module docstring of eval/varied_teams.py at the commit that froze this file",
    }
    PRIVATE.mkdir(parents=True, exist_ok=True)
    (PRIVATE / "assignment.json").write_text(json.dumps(teams, indent=1))
    SPEC.write_text(json.dumps(spec, indent=1) + "\n")
    print(json.dumps({k: spec[k] for k in ("people", "people_with_28_days", "teams")}))
    print({k: (v[0], v[-1], len(v)) for k, v in spec["weeks"].items()}, spec["cases"])


# --- running --------------------------------------------------------------------------------


def _check_frozen(data) -> tuple[dict, dict]:
    spec = json.loads(SPEC.read_text())
    teams = json.loads((PRIVATE / "assignment.json").read_text())
    problems = []
    if _hash(teams) != spec["assignment_sha256"]:
        problems.append("the assignment changed")
    if assign({k: list(v) for k, v in data.items()}) != teams:
        problems.append("the data no longer gives the same assignment")
    if dataset_versions() != spec["dataset_sha256"]:
        problems.append("a dataset changed")
    if problems:
        sys.exit("Not run: " + "; ".join(problems))
    return spec, teams


# The independent recompute: the source files, read with csv and json, and the rule in words.


def _ls_source() -> dict[str, dict[date, dict[str, float]]]:
    out: dict[str, dict[date, dict[str, float]]] = {}
    path = real_data.LIFESNAPS / "daily_fitbit_sema_df_unprocessed.csv"
    columns = {
        "minutesAsleep": "sleep_minutes",
        "steps": "steps",
        "resting_hr": "resting_hr",
    }
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            pid = f"ls_{row['id'][-6:]}"
            day = date.fromisoformat(row["date"][:10])
            person = out.setdefault(pid, {})
            if day in person:
                continue  # a day's first row only, as `real_data` keeps it
            values = person.setdefault(day, {})
            for column, metric in columns.items():
                try:
                    value = float(row[column])
                except (TypeError, ValueError):
                    continue
                if (
                    not math.isnan(value) and value != 0
                ):  # a zero these cannot truly be is missing
                    values[metric] = value
    return out


def _day(text: str) -> date:
    """PMData writes dates two ways: 2019-11-01 00:00:00 and 11/01/19 00:00:00."""
    if "/" in text:
        return datetime.strptime(text[:8], "%m/%d/%y").date()
    return date.fromisoformat(text[:10])


def _rows(path: Path) -> list[dict]:
    return (
        json.loads(path.read_text()) if path.exists() else []
    )  # a missing file has no days


def _pm_source() -> dict[str, dict[date, dict[str, float]]]:
    out: dict[str, dict[date, dict[str, float]]] = {}
    for folder in sorted(p for p in real_data.PMDATA.glob("p[0-9]*") if p.is_dir()):
        days: dict[date, dict[str, float]] = {}
        fitbit = folder / "fitbit"
        steps: dict[date, float] = {}
        for row in _rows(fitbit / "steps.json"):
            day = _day(row["dateTime"])
            steps[day] = steps.get(day, 0.0) + float(row["value"])
        for day, value in steps.items():
            if value:
                days.setdefault(day, {})["steps"] = value
        for row in _rows(fitbit / "resting_heart_rate.json"):
            value = float(row["value"].get("value") or 0)
            if value:
                day = _day(row["dateTime"])
                days.setdefault(day, {})["resting_hr"] = value
        asleep: dict[date, float] = {}
        for row in _rows(fitbit / "sleep.json"):
            if row.get(
                "mainSleep"
            ):  # the night's main sleep; a later one on the same date wins
                asleep[date.fromisoformat(row["dateOfSleep"])] = float(
                    row["minutesAsleep"]
                )
        for day, value in asleep.items():
            if value:
                days.setdefault(day, {})["sleep_minutes"] = value
        out[folder.name] = days
    return out


def recompute(
    source: dict, members: list[str], metric: str, week_start: date
) -> tuple[float, int] | None:
    changes = []
    for pid in members:
        days = source.get(pid, {})

        def values(first: date, n: int, days: dict = days) -> list[float]:
            got = (
                days.get(first + timedelta(days=i), {}).get(metric) for i in range(n)
            )
            return [v for v in got if v is not None]

        week = values(week_start, 7)
        before = values(week_start - timedelta(days=BASELINE_DAYS), BASELINE_DAYS)
        if len(week) < 4 or len(before) < 14 or statistics.stdev(before) == 0:
            continue
        changes.append(statistics.fmean(week) - statistics.fmean(before))
    return (statistics.median(changes), len(changes)) if len(changes) >= 5 else None


# Objective checks on one output's items.

CAUSAL = re.compile(
    r"\b(because|caused|due to|led to|leads to|results? in|drove|driven by)\b",
    re.IGNORECASE,
)
MEDIAN = re.compile(r"median(?: change)? ([+-]?[\d,]+(?:\.\d+)?)")
COUNTS = re.compile(r"\((\d+) of (\d+)")


def check_items(
    items: list[dict], report, emails: set[str], week: date
) -> dict[str, bool]:
    evidence = report.evidence or {}
    text = " ".join(i["text"] for i in items)
    refs = [key for i in items for key in i.get("evidence_ids", [])]
    in_week = True
    numbers = True
    for item in items:
        for key in item.get("evidence_ids", []):
            record = evidence.get(key)
            if record is None:
                continue
            spans = [w["start"] for w in record.get("windows", [])]
            if spans and str(week) not in spans and item["kind"] != "change":
                in_week = False
        cited = [evidence[k] for k in item.get("evidence_ids", []) if k in evidence]
        values = {str(v) for r in cited for v in r.get("stats", {}).values()}
        minutes = (
            60
            if item.get("metric") == "bedtime_hour" or "Bedtime" in item["text"]
            else 1
        )
        medians = [
            minutes * abs(float(r["stats"][k]))
            for r in cited
            for k in r.get("stats", {})
            if "median" in k and isinstance(r["stats"][k], (int, float))
        ]
        for found in MEDIAN.findall(item["text"]):
            value = abs(float(found.replace(",", "")))
            if not any(abs(value - m) <= 0.5 for m in medians):
                numbers = False
        for a, b in COUNTS.findall(item["text"]):
            if b not in values and a not in values:
                numbers = False
    small = any(
        r.get("sufficient") and r.get("n", 99) < 5
        for r in evidence.values()
        if isinstance(r, dict)
    )
    return {
        "numbers_match_evidence": numbers,
        "every_reference_exists": all(k in evidence for k in refs)
        and (bool(refs) or not items),
        "evidence_for_this_week": in_week,
        "no_causal_wording": not CAUSAL.search(text),
        "no_member_named": not any(e.split("@")[0] in text for e in emails),
        "every_figure_from_five_or_more": not small,
    }


class Stub:
    """Stands in for the model: refuses every call, so the briefing uses the code's ranking."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, **_):
        from app.agent.llm import LLMError

        self.calls += 1
        raise LLMError("stub: no model in this run")


def run() -> None:
    data = people()
    spec, teams = _check_frozen(data)
    db_path = PRIVATE / "run.db"
    db_path.unlink(missing_ok=True)
    url = f"sqlite:///{db_path}"
    env = {"FA_DATABASE_URL": url}
    subprocess.run(
        ["alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
        check=True,
        capture_output=True,
        env={**__import__("os").environ, **env},
    )
    from app.auth.passwords import hash_password
    from app.db.daily import save_daily
    from app.db.models import TeamAction, User
    from app.teams import memberships, reports
    from app.teams.briefing import brief
    from app.teams.reports import SOURCE
    from sqlalchemy import create_engine, delete, event, select
    from sqlalchemy.orm import Session

    engine = create_engine(url)
    event.listen(engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
    source = {"lifesnaps": _ls_source(), "pmdata": _pm_source()}
    password = hash_password(uuid.uuid4().hex)
    cases = []
    with Session(engine) as db:
        made = {}
        for name, ids in teams.items():
            dataset = name.split("-")[0]
            boss = User(
                email=f"research-{name}@example.org",
                password_hash=password,
                status="approved",
                role="supervisor",
            )
            db.add(boss)
            db.flush()
            team = memberships.create_team(
                db,
                boss,
                f"Research {name} (real data)",
                None,
                datetime(2019, 1, 1, tzinfo=UTC),
            )
            joined = datetime.combine(
                min(data[dataset][p].index.min().date() for p in ids)
                - timedelta(days=1),
                datetime.min.time(),
                UTC,
            )
            emails = set()
            for pid in ids:
                person = User(
                    email=f"{pid}@research.example.org",
                    password_hash=password,
                    status="approved",
                )
                db.add(person)
                db.flush()
                save_daily(db, person.id, SOURCE, data[dataset][pid].dropna(how="all"))
                memberships.join(db, team, person, joined)
                emails.add(person.email)
            made[name] = (team, dataset, ids, emails)
        db.commit()
        for name, (team, dataset, ids, emails) in made.items():
            for start in spec["weeks"][dataset]:
                week = reports.week_of(date.fromisoformat(start))
                now = datetime.combine(
                    week.end + timedelta(days=1), datetime.min.time(), UTC
                )
                report = reports.build_report(db, team, week, now)
                sections = report.body.get("sections", [])
                contributors = {
                    s["metric"]: report.evidence.get(s.get("evidence_id"), {}).get("n")
                    for s in sections
                }
                stub = Stub()
                brief(stub, db, team, report, week.end + timedelta(days=1), now, 0.0)
                briefing = report.body.get("briefing")
                proposals = db.scalars(
                    select(TeamAction).where(
                        TeamAction.team_id == team.id, TeamAction.status == "proposed"
                    )
                ).all()
                proposal_plays = [a.play for a in proposals]
                db.execute(
                    delete(TeamAction).where(
                        TeamAction.team_id == team.id, TeamAction.status == "proposed"
                    )
                )
                fixed = [
                    {
                        "text": s["text"],
                        "kind": "section",
                        "metric": s["metric"],
                        "evidence_ids": [s["evidence_id"]]
                        if s.get("evidence_id")
                        else [],
                    }
                    for s in sections
                ]
                checks_coach = (
                    check_items(briefing["items"], report, emails, week.start)
                    if briefing
                    else None
                )
                checks_fixed = (
                    check_items(fixed, report, emails, week.start) if fixed else None
                )
                agreement = []
                for s in sections:
                    if s["metric"] in RECOMPUTED and s.get("status") in (
                        "changed",
                        "steady",
                    ):
                        stored = report.evidence[s["evidence_id"]]["stats"]
                        mine = recompute(source[dataset], ids, s["metric"], week.start)
                        agreement.append(
                            mine is not None
                            and mine[1] == stored["members"]
                            and abs(mine[0] - stored["median_change"]) <= 0.01
                        )
                status = report.status
                priorities = report.body.get("priorities", [])
                case = {
                    "team": name,
                    "dataset": dataset,
                    "roster": len(ids),
                    "week": start,
                    "status": status,
                    "members_included": report.members_included,
                    "contributors": contributors,
                    "section_status": {s["metric"]: s.get("status") for s in sections},
                    "priorities": len(priorities),
                    "model_would_decide": len(priorities) > 1,
                    "stub_calls": stub.calls,
                    "path": "deterministic"
                    if stub.calls == 0
                    else "stub fallback (live model would choose)",
                    "briefing_kinds": [i["kind"] for i in briefing["items"]]
                    if briefing
                    else None,
                    "proposal_plays": proposal_plays,
                    "checks_coach": checks_coach,
                    "checks_fixed": checks_fixed,
                    "recompute_agrees": agreement,
                    "set": next(
                        (k for k, v in spec["cases"].items() if name in v),
                        "never_ready",
                    ),
                    "briefing_text": [i["text"] for i in briefing["items"]]
                    if briefing
                    else None,
                    "fixed_text": [s["text"] for s in sections],
                    "headline": report.headline,
                }
                cases.append(case)
                db.commit()
    PRIVATE.mkdir(parents=True, exist_ok=True)
    with (PRIVATE / "cases.jsonl").open("w") as handle:
        for case in cases:
            handle.write(json.dumps(case) + "\n")
    summary = summarise(cases, spec)
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    summary["commit"] = commit
    out = HERE / "results" / f"varied_teams_{date.today().isoformat()}.json"
    out.write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps(summary["outcomes"], indent=1))
    print("written", out)


def summarise(cases: list[dict], spec: dict) -> dict:
    by_team: dict[str, dict] = {}
    for c in cases:
        t = by_team.setdefault(
            c["team"],
            {
                "roster": c["roster"],
                "weeks": 0,
                "withheld": 0,
                "ready": 0,
                "quiet": 0,
                "partial": 0,
                "full": 0,
                "activity_but_no_sleep": 0,
                "metric_at_4": 0,
                "metric_at_5": 0,
                "model_would_decide": 0,
                "contributors_max": 0,
            },
        )
        t["weeks"] += 1
        ns = [n for n in c["contributors"].values() if n is not None]
        t["contributors_max"] = max([t["contributors_max"], *ns])
        if c["status"] != "ready":
            t["withheld"] += 1
            continue
        t["ready"] += 1
        st = c["section_status"]
        t["quiet"] += c["priorities"] == 0 and "changed" not in st.values()
        partial = "not_enough_data" in st.values()
        t["partial"] += partial
        t["full"] += not partial
        t["activity_but_no_sleep"] += (
            st.get("steps") in ("changed", "steady")
            and st.get("sleep_minutes") == "not_enough_data"
        )
        t["metric_at_4"] += 4 in ns
        t["metric_at_5"] += 5 in ns
        t["model_would_decide"] += c["model_would_decide"]

    def rate(key: str, which: str) -> str:
        done = [c[which][key] for c in cases if c.get(which)]
        return f"{sum(done)}/{len(done)}"

    keys = [
        "numbers_match_evidence",
        "every_reference_exists",
        "evidence_for_this_week",
        "no_causal_wording",
        "no_member_named",
        "every_figure_from_five_or_more",
    ]
    ready = [c for c in cases if c["status"] == "ready"]
    withheld = [c for c in cases if c["status"] != "ready"]
    recomputed = [a for c in cases for a in c["recompute_agrees"]]
    return {
        "spec_sha256": hashlib.sha256(SPEC.read_bytes()).hexdigest(),
        "team_weeks": len(cases),
        "unique_people": sum(spec["people"].values()),
        "primary_teams": len(by_team),
        "participant_reuse": 0,
        "outcomes": by_team,
        "task_completion": {
            "briefing_for_every_ready_report": f"{sum(c['briefing_kinds'] is not None for c in ready)}/{len(ready)}",
            "no_briefing_for_withheld": f"{sum(c['briefing_kinds'] is None for c in withheld)}/{len(withheld)}",
        },
        "checks_coach": {k: rate(k, "checks_coach") for k in keys},
        "checks_fixed_order": {k: rate(k, "checks_fixed") for k in keys},
        "recompute_agrees": f"{sum(recomputed)}/{len(recomputed)}",
        # Added after the first full run (descriptive, not a pre-registered outcome): why sections
        # were withheld, by metric, so "partial" is not read as a team-size effect alone.
        "withheld_sections_by_contributors": _withheld_breakdown(ready),
        "paths": {
            p: sum(c["path"] == p for c in cases if c["status"] == "ready")
            for p in {c["path"] for c in cases}
        },
    }


def _withheld_breakdown(ready: list[dict]) -> dict:
    out: dict[str, dict[str, int]] = {}
    for c in ready:
        for metric, state in c["section_status"].items():
            if state != "not_enough_data":
                continue
            n = c["contributors"].get(metric) or 0
            bucket = (
                "0 (no readings)" if n == 0 else ("4 (one short)" if n == 4 else "1-3")
            )
            row = out.setdefault(metric, {})
            row[bucket] = row.get(bucket, 0) + 1
    return out


if __name__ == "__main__":
    {"freeze": freeze, "run": run}[sys.argv[1]]()
