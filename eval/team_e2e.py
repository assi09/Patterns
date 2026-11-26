"""End to end through the API, as each person: check-in alerts (no consent, send now, stop, the
hour running out, no second alert, marks, who sees what, HR removed) and the team report.

Team A is PMData's 16 real people (`eval/mcp_red_team_seed.py`). Members' real histories are
moved to end yesterday with a severe week planted at the end (150 minutes less sleep, 12 more
resting beats), so the rule has a fresh week; the first three whose week meets the rule take the
three paths. A flow test, not a statistics test: `eval/checkin_real.py` measures the rule.

Against a local API on the seeded throwaway database (port 8012, Sentry off), from the
repository root:
    PYTHONPATH=backend python eval/team_e2e.py sqlite:////tmp/rt.db /tmp/tokens.json
Prints pass/fail only and exits 1 on any failure.
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
from app.db.daily import load_daily, save_daily
from app.db.models import DailyMetric, User
from app.teams import checkin, memberships
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

DB = sys.argv[1]
TOKENS = json.loads(Path(sys.argv[2]).read_text())
A = TOKENS["team_a"]
api = httpx2.Client(base_url="http://127.0.0.1:8012", timeout=60)
engine = create_engine(DB)
now = datetime.now(UTC)
failures = 0


def check(name, ok):
    global failures
    failures += 0 if ok else 1
    print(("PASS " if ok else "FAIL ") + name)


def login(email):
    r = api.post("/auth/login", json={"email": email, "password": "rt-password-1"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


# Members' real histories, moved to end yesterday with a severe planted week; the first three whose
# week meets the rule take the three paths (send now, stop, the hour running out).
from app.analysis.day import with_scores

chosen, qualified = [], 0
with Session(engine) as db:
    for i in range(1, 17):
        email = f"pm-{i:02d}@example.com"
        person = db.scalar(select(User).where(User.email == email))
        frame = load_daily(
            db,
            person.id,
            "google_health",
            datetime(2019, 1, 1).date(),
            datetime(2021, 1, 1).date(),
        )
        if "resting_hr" not in frame or "sleep_minutes" not in frame:
            continue  # this person never recorded one of the two planted signals
        frame = frame.iloc[-60:].copy()
        shift = (now.date() - timedelta(days=1)) - frame.index.max().date()
        frame.index = frame.index + timedelta(days=shift.days)
        last7 = frame.index[-7:]
        frame.loc[last7, "sleep_minutes"] = (
            frame.loc[last7, "sleep_minutes"] - 150
        ).clip(lower=60)
        frame.loc[last7, "resting_hr"] = frame.loc[last7, "resting_hr"] + 12
        frame["wear_minutes"] = 900.0
        if checkin.detect(with_scores(frame), now.date()):
            qualified += 1
            if len(chosen) < 3:
                db.query(DailyMetric).filter(DailyMetric.user_id == person.id).delete()
                save_daily(db, person.id, "google_health", frame)
                chosen.append(email)
    db.commit()
print(
    f"members whose planted week (150 min less sleep, 12 bpm more) meets the rule: {qualified} of 16"
)
other = next(
    f"pm-{i:02d}@example.com"
    for i in range(1, 17)
    if f"pm-{i:02d}@example.com" not in chosen
)

boss, hr, boss_b = (
    login("boss-a@example.com"),
    login("hr@example.com"),
    login("boss-b@example.com"),
)
m1, m2, m3, m4 = (login(e) for e in [*chosen, other])
ids = {}
with Session(engine) as db:
    for i, e in enumerate([*chosen, other], 1):
        ids[i] = db.scalar(select(User.id).where(User.email == e))

# No consent, no alert.
with Session(engine) as db:
    check(
        "without consent the rule raises nothing",
        checkin.after_sync(db, ids[1], now) == 0,
    )
    db.commit()

for m in (m1, m2, m3):
    api.post(
        f"/me/teams/{A}/levels",
        headers=m,
        json={"share": True, "consent_version": memberships.LEVELS_CONSENT_VERSION},
    )
    r = api.post(
        f"/me/teams/{A}/checkin",
        headers=m,
        json={"share": True, "consent_version": checkin.CONSENT_VERSION},
    )
check("three members turn on check-in alerts", r.status_code == 200)

with Session(engine) as db:
    raised = [checkin.after_sync(db, ids[i], now) for i in (1, 2, 3)]
    db.commit()
check("the sync after a severe week raises one alert each", raised == [1, 1, 1])
mine = api.get("/me/checkins", headers=m1).json()
check(
    "the person sees it waiting, with when it goes out",
    len(mine) == 1 and mine[0]["status"] == "waiting",
)
check(
    "...and the evidence behind it",
    "evidence" in json.dumps(mine[0]).lower()
    or "signal" in json.dumps(mine[0]).lower(),
)
check(
    "nobody else sees a waiting alert",
    api.get("/checkins", headers=boss).json() == []
    and api.get("/checkins", headers=hr).json() == [],
)

api.post(f"/me/checkins/{mine[0]['id']}/send", headers=m1)
seen_boss = api.get("/checkins", headers=boss).json()
seen_hr = api.get("/checkins", headers=hr).json()
check(
    "send now: the supervisor and HR each get it",
    len(seen_boss) == 1 and len(seen_hr) == 1,
)
inbox = json.dumps(api.get("/notifications", headers=boss).json())
check(
    "their inbox says only 'You have a check-in request', no name",
    "check-in request" in inbox and "pm-" not in inbox,
)
check(
    "no metric or value reaches a recipient",
    not any(
        w in json.dumps(seen_boss).lower()
        for w in ("sleep", "heart", "resting", "minutes")
    ),
)

two = api.get("/me/checkins", headers=m2).json()[0]
api.post(f"/me/checkins/{two['id']}/stop", headers=m2)
check(
    "stopped: it never reaches anyone",
    len(api.get("/checkins", headers=boss).json()) == 1,
)

with Session(engine) as db:
    sent = checkin.send_due(db, now + timedelta(minutes=61))
    db.commit()
check(
    "left alone, it goes out when the hour is up",
    sent == 1 and len(api.get("/checkins", headers=boss).json()) == 2,
)

with Session(engine) as db:
    again = checkin.after_sync(db, ids[1], now + timedelta(hours=3))
    db.commit()
check("a later sync raises no second alert", again == 0)

first = api.get("/checkins", headers=boss).json()[0]
marked = api.post(
    f"/checkins/{first['id']}/mark", headers=boss, json={"outcome": "checked_in"}
)
check("the supervisor marks one checked in", marked.status_code == 200)
check(
    "another team's supervisor sees none",
    api.get("/checkins", headers=boss_b).json() == [],
)
r = api.get("/checkins", headers=m4)
check("a member sees none", r.status_code in (403, 404) or r.json() == [])

api.put(f"/teams/{A}/hr", headers=boss, json={"email": None})
r = api.get("/checkins", headers=hr)
check(
    "HR removed from the team: their access ends at once",
    r.status_code in (403, 404) or r.json() == [],
)

# The team report and an assistant's event approved into a note.
reports = api.get(f"/teams/{A}/reports", headers=boss)
check(
    "the supervisor reads the team's report",
    reports.status_code == 200 and len(reports.json()) >= 1,
)
check(
    "members cannot read it",
    api.get(f"/teams/{A}/reports", headers=m4).status_code in (403, 404),
)
print("failures:", failures)
sys.exit(1 if failures else 0)
