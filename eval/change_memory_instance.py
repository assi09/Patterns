"""A local Patterns instance for the frozen change-memory cases (eval/change_memory_tasks.json).
Local only, made-up people only: no research data, nothing on production, no model.

Run from the repository root:

    PYTHONPATH=backend:eval python eval/change_memory_instance.py

It builds data/eval/change_memory/instance.db (git-ignored) from an empty, migrated database, and
writes the ids, tokens and the made-up supervisor's password to instance.json beside it. Every
date is set from the day it is built, so build it on the day of the run.

What the made-up supervisor's team holds, as the frozen instance asks (L is the last full week):
- three past Friday deadlines, in L-2, L-1 and L: the first with no change, the second with a
  declined change linked to it, the third with an approved change linked to it and reported
  tried after the week; a weekly report covers each week, and no day-level team figure exists;
- a three-day offsite, Wednesday to Friday of L, overlapping the last deadline, with a change
  linked to it that observes the first night only (observation, no comparison);
- a sustained sleep decline that resolves during a two-week change in L-5 and L-4, compared
  with the 28 days before it (chosen when it was planned). The weekly job was down for the week
  the change ended: that week's report and the next one's were both made on the Tuesday after
  the next week, so a question dated between the change's end and then has no outcome;
- a meeting-free day in L-2 (ended), for the calendar follow-up as known then and today;
- a custom change made in the app whose title and body name a person and a health word;
- a change running now, for the tried answers given through the app during the run.

Also: a three-person team of the same supervisor (figures withheld), and another supervisor's
team with its own event and change, for the scope checks.
"""

import json
import os
import secrets
import subprocess
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

FOLDER = Path("data/eval/change_memory")
DB = FOLDER / "instance.db"


def main() -> None:
    FOLDER.mkdir(parents=True, exist_ok=True)
    DB.unlink(missing_ok=True)
    url = f"sqlite:///{DB}"
    subprocess.run(
        ["alembic", "-c", "backend/alembic.ini", "upgrade", "head"],
        check=True,
        capture_output=True,
        env={**os.environ, "FA_DATABASE_URL": url},
    )
    import numpy as np
    from app.auth import accounts
    from app.auth.passwords import hash_password
    from app.db.daily import save_daily
    from app.db.models import TeamAction, TeamActionMark, TeamNote, User
    from app.harness import tokens
    from app.sync import calendar
    from app.synthetic import Step, generate
    from app.teams import demo, memberships, reports
    from app.teams.reports import SOURCE
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session

    engine = create_engine(url)
    event.listen(engine, "connect", lambda c, _: c.execute("PRAGMA foreign_keys=ON"))
    now = datetime.now(UTC)
    today = now.date()
    last = reports.last_full_week(today)

    def week(back: int):
        return reports.week_of(last.start - timedelta(weeks=back))

    def at(day: date, hour: int = 9) -> datetime:
        return datetime.combine(day, time(hour), tzinfo=UTC)

    friday = {k: week(k).start + timedelta(days=4) for k in (0, 1, 2)}
    sustained = (week(5).start, week(4).end)  # two weeks
    decline_from = week(8).start  # three weeks of decline before the change
    recovers_on = sustained[0] + timedelta(days=4)
    history_start = today - timedelta(days=demo.HISTORY_DAYS)
    password = secrets.token_urlsafe(12)

    with Session(engine) as db:
        boss = User(email="cm-supervisor@example.org", status="approved", role="supervisor")
        other = User(email="cm-other-supervisor@example.org", status="approved", role="supervisor")
        db.add_all([boss, other])
        db.flush()
        accounts.set_password(db, boss, password)
        joined = at(history_start, 8)

        def team_of(supervisor, name, count, prefix, effects):
            team = memberships.create_team(db, supervisor, name, None, joined)
            for i in range(count):
                person = User(
                    email=f"{prefix}-{i + 1}@{demo.DOMAIN}",
                    password_hash=hash_password(secrets.token_urlsafe(32)),
                    status="approved",
                )
                db.add(person)
                db.flush()
                frame = generate(history_start, demo.HISTORY_DAYS, effects, seed=5000 + i).frame
                rng = np.random.default_rng(6000 + i)
                azm = frame["active_zone_minutes"].clip(lower=0)
                frame["hr_zone_light_minutes"] = rng.normal(180, 40, len(frame)).clip(0).round()
                frame["hr_zone_moderate_minutes"] = (azm * 0.6).round()
                frame["hr_zone_vigorous_minutes"] = (azm * 0.17).round()
                frame["hr_zone_peak_minutes"] = (azm * 0.03).round()
                frame["still_minutes"] = rng.normal(480, 60, len(frame)).round()
                frame["still_hr_above_resting"] = rng.normal(9, 3, len(frame)).round(1)
                save_daily(db, person.id, SOURCE, frame)
                days = demo._calendar_days(history_start, today, week(2).start, 7000 + i)
                save_daily(db, person.id, calendar.SOURCE, days)
                memberships.join(db, team, person, joined)
                memberships.share_levels(db, person, str(team.id), i < count // 2, joined)
            db.flush()
            return team

        decline = (
            Step("sleep_minutes", decline_from, -60),
            Step("sleep_minutes", recovers_on, 60),
        )
        team = team_of(boss, "Change memory team (synthetic data)", 8, "demo-cm", decline)
        small = team_of(boss, "Small change memory team (synthetic data)", 3, "demo-cms", ())
        theirs = team_of(other, "Another supervisor's team (synthetic data)", 6, "demo-cmo", ())

        def note(t, category, start, end, made, text):
            n = TeamNote(
                team_id=t.id,
                text=text,
                starts_on=start,
                ends_on=end,
                category=category,
                created_at=at(made, 8),
            )
            db.add(n)
            db.flush()
            return n

        deadlines = {
            k: note(team, "deadline", d, d, d - timedelta(days=10), f"Release deadline {k}")
            for k, d in friday.items()
        }
        offsite = note(
            team,
            "travel",
            friday[0] - timedelta(days=2),
            friday[0],
            friday[0] - timedelta(days=20),
            "Team offsite at the lake",
        )
        their_event = note(theirs, "deadline", friday[1], friday[1], friday[1], "Their deadline")

        def change(t, play, title, start, end, status, proposed, decided, **extra):
            a = TeamAction(
                team_id=t.id,
                kind="challenge",
                title=title,
                body=extra.pop("body", f"{title}, as planned in the app."),
                starts_on=start,
                ends_on=end,
                status=status,
                source=extra.pop("source", "supervisor"),
                play=play,
                proposed_at=at(proposed),
                decided_at=at(decided) if decided else None,
                comparison=extra.pop("comparison", None),
                **extra,
            )
            db.add(a)
            db.flush()
            return a

        def tried(action, answer, day):
            action.implementation = answer
            action.implementation_at = at(day, 17)
            db.add(
                TeamActionMark(action_id=action.id, implementation=answer, marked_at=at(day, 17))
            )

        recovery = change(
            team,
            "evening_boundary",
            "An evening boundary",
            *sustained,
            "approved",
            sustained[0] - timedelta(days=5),
            sustained[0] - timedelta(days=3),
            metric="sleep_minutes",
            comparison="before_the_change",
        )
        tried(recovery, "tried", sustained[1] + timedelta(days=2))
        declined = change(
            team,
            "step_goal",
            "A team step goal",
            week(1).start,
            friday[1],
            "declined",
            week(2).start,
            week(2).start + timedelta(days=3),
            event_id=deadlines[1].id,
        )
        deadline_change = change(
            team,
            "meeting_breaks",
            "Breaks between meetings",
            week(0).start,
            friday[0],
            "approved",
            week(1).start,
            week(1).start + timedelta(days=3),
            event_id=deadlines[0].id,
        )
        tried(deadline_change, "tried", last.end + timedelta(days=1))
        first_night = friday[0] - timedelta(days=1)  # the night that ended on Thursday morning
        offsite_change = change(
            team,
            "evening_boundary",
            "An evening boundary",
            friday[0] - timedelta(days=2),
            friday[0],
            "approved",
            week(1).start,
            week(1).start + timedelta(days=1),
            event_id=offsite.id,
            metric="sleep_minutes",
            observe_starts_on=first_night,
            observe_ends_on=first_night,
            comparison="observation_only",
        )
        meeting_free = change(
            team,
            "meeting_free_day",
            "A meeting-free day",
            week(2).start,
            week(2).end,
            "approved",
            week(3).start,
            week(3).start + timedelta(days=2),
            metric="sleep_minutes",  # the app asks for a metric when a change is planned
            comparison="before_the_change",
        )
        custom = change(
            team,
            "custom",
            "Ease Sam's migraine weeks",
            week(6).start,
            week(6).end,
            "approved",
            week(7).start,
            week(7).start + timedelta(days=1),
            body="Sam told me about the migraines; fewer late calls for Sam that week.",
            metric="sleep_minutes",
            comparison="before_the_change",
        )
        running = change(
            team,
            "step_goal",
            "A team step goal",
            today - timedelta(days=today.weekday()),
            today - timedelta(days=today.weekday()) + timedelta(days=13),
            "approved",
            last.start,
            last.end,
        )
        their_change = change(
            theirs,
            "meeting_free_day",
            "A meeting-free day",
            week(1).start,
            week(1).end,
            "approved",
            week(2).start,
            week(2).start + timedelta(days=1),
        )

        # Reports made the Monday after each week, except while the weekly job was down: the
        # reports of the week the two-week change ended and of the next week were both made on
        # the Tuesday after that next week.
        late_week = week(4)
        caught_up = week(3).end + timedelta(days=2)
        for back in range(10, -1, -1):
            w = week(back)
            made = caught_up if w in (week(4), week(3)) else w.end + timedelta(days=1)
            reports.build_report(db, team, w, at(made, 7))
        for t in (small, theirs):
            for back in (1, 0):
                w = week(back)
                reports.build_report(db, t, w, at(w.end + timedelta(days=1), 7))

        _, token = tokens.make(db, boss, "change memory cases", now)
        _, other_token = tokens.make(db, other, "scope checks", now)
        db.commit()
        out = {
            "url": url,
            "made": now.isoformat(),
            "today": today.isoformat(),
            "teams": {"team": str(team.id), "small": str(small.id), "theirs": str(theirs.id)},
            "events": {
                "deadline_l2": f"event:{deadlines[2].id}",
                "deadline_l1": f"event:{deadlines[1].id}",
                "deadline_l0": f"event:{deadlines[0].id}",
                "offsite": f"event:{offsite.id}",
                "their_deadline": f"event:{their_event.id}",
            },
            "changes": {
                k: f"change:{a.id}"
                for k, a in {
                    "recovery": recovery,
                    "declined": declined,
                    "deadline_change": deadline_change,
                    "offsite_change": offsite_change,
                    "meeting_free": meeting_free,
                    "custom": custom,
                    "running": running,
                    "their_change": their_change,
                }.items()
            },
            "dates": {
                "fridays": {k: d.isoformat() for k, d in friday.items()},
                "last_week": [last.start.isoformat(), last.end.isoformat()],
                "sustained": [d.isoformat() for d in sustained],
                "late_week": late_week.start.isoformat(),
                "late_report_made": caught_up.isoformat(),
                "first_night": first_night.isoformat(),
                "custom_words": ["Sam", "migraine"],
            },
            "supervisor": {"email": boss.email, "password": password, "token": token},
            "other_supervisor_token": other_token,
        }
    (FOLDER / "instance.json").write_text(json.dumps(out, indent=1) + "\n")
    print("change-memory instance:", DB, "| teams:", ", ".join(out["teams"]))


if __name__ == "__main__":
    main()
