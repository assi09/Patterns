"""A local Patterns instance for the supervisor tasks (eval/supervisor_tasks.json). Local only.

Run from the repository root after `eval/varied_teams.py run`:

    PYTHONPATH=backend:eval python eval/supervisor_instance.py

It copies the varied-team run database to data/eval/supervisor/local.db (never committed) and adds:
- a made-up supervisor (presenter@example.org) who is given two research teams from the
  rubric-development set, LifeSnaps 11 and LifeSnaps 4. Their reports are the ones the varied-team
  run stored; nothing is recomputed. Reserved teams are left with their own research supervisors
  and are never read;
- three labelled synthetic teams for the same supervisor, made by the demo-team code: one with
  made-up calendar days (a lasting sleep drop in a busy week), one of three people (withheld), and
  one with an approved, finished team change, reported for a week while it ran and for the last
  full week;
- a second made-up supervisor with a synthetic team of their own, for authorization checks;
- an MCP token for each supervisor, and one revoked token.

The tokens, the team ids and the supervisor's password are written to
data/eval/supervisor/instance.json (git-ignored), for the scripted runs and real assistants.
"""

import json
import os
import secrets
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

RUN_DB = Path("data/eval/varied_teams/run.db")
# Another folder keeps a second instance apart, e.g. one built at the baseline revision.
OUT = Path(os.environ.get("FA_SUPERVISOR_INSTANCE", "data/eval/supervisor"))


def main() -> None:
    if not RUN_DB.exists():
        sys.exit("run eval/varied_teams.py first: its database is the source of the research teams")
    OUT.mkdir(parents=True, exist_ok=True)
    db_path = OUT / "local.db"
    shutil.copy(RUN_DB, db_path)
    url = f"sqlite:///{db_path}"
    env = {**os.environ, "FA_DATABASE_URL": url}
    subprocess.run(
        ["alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
        check=True,
        capture_output=True,
        env=env,
    )
    import varied_teams
    from app.auth import accounts
    from app.db.models import Team, TeamAction, User
    from app.harness import tokens
    from app.teams import demo, reports
    from app.teams.briefing import brief
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import Session

    engine = create_engine(url)
    event.listen(engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
    now = datetime.now(UTC)
    today = now.date()
    last = reports.last_full_week(today)
    password = secrets.token_urlsafe(12)
    out: dict = {"url": url, "made": now.isoformat(), "last_full_week": last.start.isoformat()}
    with Session(engine) as db:
        boss = User(email="presenter@example.org", status="approved", role="supervisor")
        other = User(email="other-supervisor@example.org", status="approved", role="supervisor")
        db.add_all([boss, other])
        db.flush()
        accounts.set_password(db, boss, password)
        teams = {}
        for key in ("lifesnaps-11", "lifesnaps-4"):
            team = db.scalar(select(Team).where(Team.name == f"Research {key} (real data)"))
            team.supervisor_id = boss.id
            team.name = {
                "lifesnaps-11": "LifeSnaps group A, 11 people (real research participants)",
                "lifesnaps-4": "LifeSnaps group B, 4 people (real research participants)",
            }[key]
            teams[key] = str(team.id)

        def made(supervisor, name, count, prefix, lasting):
            team, _ = demo.create_demo_team(
                db, supervisor, name, count, prefix, lasting, today, now
            )
            return team

        both = made(boss, "Demo team (synthetic data)", 8, "demo-both", True)
        small = made(boss, "Small demo team (synthetic data)", 3, "demo-small", False)
        acted = made(boss, "Demo team with a past change (synthetic data)", 8, "demo-acted", True)
        theirs = made(other, "Another supervisor's team (synthetic data)", 6, "demo-other", True)
        # A change the supervisor approved: it ran for three weeks up to the end of the last full
        # week, so the report of the week before last was written while it ran, and its result
        # is known only from the last week's report.
        began = last.start - timedelta(days=14)
        db.add(
            TeamAction(
                team_id=acted.id,
                kind="challenge",
                title="No meetings after 5 pm",
                body="No team meetings or calls after 5 pm on working days.",
                metric="sleep_minutes",
                starts_on=began,
                ends_on=last.end,
                status="approved",
                source="supervisor",
                play="no_late_meetings",
                proposed_at=now - timedelta(days=16),
                decided_at=now - timedelta(days=16),
            )
        )
        db.flush()
        during = reports.week_of(last.start - timedelta(days=7))
        for team, week in (
            (both, last),
            (small, last),
            (acted, during),
            (acted, last),
            (theirs, last),
        ):
            at = datetime.combine(week.end + timedelta(days=1), datetime.min.time(), UTC)
            report = reports.build_report(db, team, week, at)
            # The code's ranking, never a model (the stub refuses every call). Whatever the
            # briefing proposes is left as the code made it.
            brief(varied_teams.Stub(), db, team, report, week.end + timedelta(days=1), at, 0.0)
        made_ids = {
            "demo_both": str(both.id),
            "demo_small": str(small.id),
            "demo_acted": str(acted.id),
            "other_supervisors_team": str(theirs.id),
        }
        _, token = tokens.make(db, boss, "supervisor tasks", now)
        _, other_token = tokens.make(db, other, "authorization checks", now)
        revoked_row, revoked = tokens.make(db, boss, "revoked on purpose", now)
        tokens.revoke(db, boss, str(revoked_row.id), now)
        db.commit()
        out |= {
            "teams": teams | made_ids,
            "action_week": during.start.isoformat(),
            "presenter": {"email": boss.email, "password": password, "token": token},
            "other_supervisor_token": other_token,
            "revoked_token": revoked,
        }
    (OUT / "instance.json").write_text(json.dumps(out, indent=1) + "\n")
    print("local instance:", db_path, "| teams:", ", ".join(out["teams"]))


if __name__ == "__main__":
    main()
