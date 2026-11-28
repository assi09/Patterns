# ruff: noqa: F811 (the engine fixture imported from test_team_briefing)
"""The weekly team metric explorer, end to end from the live sync (docs/team-metrics.md).

Each member's days start as made-up responses in the shapes the Google Health API returns, go
through the production parser and persistence (`app.sync.pull.pull`: `load_daily` then
`save_daily`), and come back out as team figures through the app API and MCP. Nothing here starts
from finished daily rows, except the Takeout history that must never reach a live figure.

Every expected figure is worked out by hand in the comments: values are constant in a window or
alternate evenly, so each person's change is exact and the median is one person's change."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from sqlalchemy import func, select
from test_api_daily import FakeHealth, level_interval, rollup, sleep
from test_mcp import build as build_mcp
from test_mcp import call as call_mcp
from test_team_briefing import engine  # noqa: F401

from app.analysis.team import TEAM_METRICS
from app.db.daily import load_daily, save_daily
from app.db.models import Team, TeamMetricWeek, TeamReport, User
from app.db.session import session_scope
from app.sync.pull import pull
from app.teams import explorer, memberships, reports

# The week browsed, its 28 days before, and a week after it that must never show.
WEEK = date(2026, 10, 12)  # Monday; the week is Oct 12-18
WEEK_END = date(2026, 10, 18)
BASELINE = (date(2026, 9, 14), date(2026, 10, 11))
SYNC_START, SYNC_END = date(2026, 9, 7), date(2026, 10, 26)  # [start, end): one week each side
NOW = datetime(2026, 10, 20, 9, tzinfo=UTC)  # the Tuesday after: the figures are made then
TODAY = NOW.date()

# Time asleep: the 28 days alternate 470 and 430 (mean 450, 14 nights each); the week is 450 - d.
SLEEP_DROPS = [54, 56, 58, 60, 62, 64, 66]  # median 60, so the team figure is -60 min
# REM on staged nights: the 28 days alternate 95 and 105 (mean 100); the week is 100 + r.
REM_RISES = [10, 15, 20, 25, 30]  # median 20, so +20 min from the 5 people with stages
# Cardio zone, actual minutes: 10 a day before, 20 in the week (+10). Fat burn zone 20 throughout.
# Weighted AZM is fat burn + 2 x cardio: 20 + 20 = 40 before, 20 + 40 = 60 in the week (+20).
# Peak zone is never reached: a worn day's roll-up has no PEAK entry, a genuine 0 every day.
LATER = 600  # the week after: anything leaking from it would move every figure


def night(day: date, asleep: int, rem: int | None) -> dict:
    """The main sleep that ended on local `day`, 23:00 to 07:00 at UTC+3 (480 min in bed).
    `rem=None` makes it a CLASSIC night, which has no stages."""
    start = f"{day - timedelta(days=1)}T20:00:00Z"
    end = f"{day}T04:00:00Z"
    if rem is None:
        return sleep(start, end, asleep, kind="CLASSIC")
    return sleep(start, end, asleep, stages={"DEEP": 80, "LIGHT": 200, "REM": rem, "AWAKE": 30})


def zones(day: date, cardio: int) -> tuple[dict, dict]:
    elapsed = rollup(
        str(day),
        "timeInHeartRateZone",
        {
            "timeInHeartRateZones": [
                {"heartRateZone": "LIGHT", "duration": "3600s"},
                {"heartRateZone": "MODERATE", "duration": "1200s"},
                {"heartRateZone": "VIGOROUS", "duration": f"{cardio * 60}s"},
            ]
        },
    )
    # The API's cardio sum already counts each minute twice; no peak sum on a day without one.
    weighted = rollup(
        str(day),
        "activeZoneMinutes",
        {"sumInFatBurnHeartZone": "20", "sumInCardioHeartZone": str(2 * cardio)},
    )
    return elapsed, weighted


def api_responses(drop: int, rise: int | None, rem_week: int | None = None) -> FakeHealth:
    """One member's Google Health responses over SYNC_START..SYNC_END. `rise=None`: every night
    is CLASSIC. `rem_week` overrides the week's REM, for a later re-sync."""
    sleeps, steps, elapsed, weighted, levels = [], [], [], [], []
    day = SYNC_START
    while day < SYNC_END:
        in_week, after = WEEK <= day <= WEEK_END, day > WEEK_END
        even = (day - SYNC_START).days % 2 == 0
        asleep = LATER if after else (450 - drop if in_week else (470 if even else 430))
        rem = None
        if rise is not None:
            usual = 95 if even else 105
            rem = LATER if after else ((rem_week or 100 + rise) if in_week else usual)
        sleeps.append(night(day, asleep, rem))
        steps.append(rollup(str(day), "steps", {"countSum": "9000" if in_week else "8000"}))
        z, w = zones(day, LATER if after else (20 if in_week else 10))
        elapsed.append(z)
        weighted.append(w)
        # Worn 08:00-22:00 local, 840 minutes, so activity is never left out as low wear.
        levels.append(
            level_interval(str(day), f"{day}T05:00:00Z", f"{day}T19:00:00Z", kind="LIGHT")
        )
        day += timedelta(days=1)
    return FakeHealth(
        rollups={
            "steps": steps,
            "time-in-heart-rate-zone": elapsed,
            "active-zone-minutes": weighted,
        },
        points={"sleep": sleeps, "activity-level": levels},
    )


def sessions(engine):
    return lambda: session_scope(engine)


def sync(engine, email: str, health: FakeHealth) -> None:
    run = pull(sessions(engine), health, email, SYNC_START, SYNC_END)
    assert run.status == "succeeded"


def supervisor(db, email: str) -> User:
    boss = User(email=email, status="approved", role="supervisor")
    db.add(boss)
    db.flush()
    return boss


def team_with(engine, boss_email: str, name: str, members: list[tuple[str, FakeHealth | None]]):
    """A team whose members' days came through the live sync; `None` syncs nothing."""
    for email, health in members:
        if health is not None:
            sync(engine, email, health)
    with session_scope(engine) as db:
        boss = db.scalar(select(User).where(User.email == boss_email)) or supervisor(db, boss_email)
        team = memberships.create_team(db, boss, name, None, NOW - timedelta(days=60))
        for email, _ in members:
            person = db.scalar(select(User).where(User.email == email))
            if person is None:
                person = User(email=email, status="approved")
                db.add(person)
                db.flush()
            memberships.join(db, team, person, NOW - timedelta(days=60))
        return str(team.id)


@pytest.fixture
def teams(engine):
    # Team A: seven people; the first five have staged nights, the last two classic ones only.
    a = team_with(
        engine,
        "boss@example.com",
        "Design",
        [
            (f"a{i}@example.com", api_responses(SLEEP_DROPS[i], REM_RISES[i] if i < 5 else None))
            for i in range(7)
        ],
    )
    # Team B, another supervisor's: six people, only four with staged nights.
    b = team_with(
        engine,
        "other@example.com",
        "Ops",
        [
            (f"b{i}@example.com", api_responses(SLEEP_DROPS[i], REM_RISES[i] if i < 4 else None))
            for i in range(6)
        ],
    )
    # Team C, a third supervisor's: five people with Takeout history only, and no live sync.
    c = team_with(
        engine, "third@example.com", "Labs", [(f"c{i}@example.com", None) for i in range(5)]
    )
    with session_scope(engine) as db:
        takeout = takeout_frame()
        for email in [f"c{i}@example.com" for i in range(5)] + ["a5@example.com"]:
            person = db.scalar(select(User).where(User.email == email))
            save_daily(db, person.id, "takeout", takeout)
        # Each week's report made at NOW: who belonged then is who its figures describe.
        for team_id in (a, b, c):
            reports.build_report(db, db.get(Team, uuid.UUID(team_id)), reports.week_of(WEEK), NOW)
    return a, b, c


def takeout_frame() -> pd.DataFrame:
    """Takeout days covering the same dates, with values no live figure may show: REM 999 a
    night, so a classic-night member with Takeout REM would move team A's figure."""
    days = pd.date_range(SYNC_START, SYNC_END - timedelta(days=1), freq="D")
    rem = [999.0 if WEEK <= d.date() <= WEEK_END else 1.0 for d in days]
    return pd.DataFrame(
        {"rem_sleep_minutes": rem, "sleep_minutes": 999.0, "steps": 99999.0},
        index=pd.DatetimeIndex(days, name="date"),
    )


def api(engine, email: str, now: datetime = NOW):
    from fastapi.testclient import TestClient

    from app.api import auth
    from app.api.main import create_app
    from app.auth import accounts

    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[auth.now] = lambda: now
    client = TestClient(app)
    with session_scope(engine) as session:
        person = session.scalar(select(User).where(User.email == email))
        accounts.set_password(session, person, "correct horse battery")
    token = client.post(
        "/auth/login", json={"email": email, "password": "correct horse battery"}
    ).json()["token"]
    return client, {"Authorization": f"Bearer {token}"}


def user_id(engine, email: str) -> uuid.UUID:
    with session_scope(engine) as db:
        return db.scalar(select(User.id).where(User.email == email))


def rows_of(listing: dict) -> dict[str, dict]:
    return {
        m["metric"]: m
        for category in listing["categories"]
        for group in category["subgroups"]
        for m in group["metrics"]
    }


def test_the_sync_stores_missing_stages_as_missing_and_unreached_zones_as_zero(teams, engine):
    with session_scope(engine) as db:
        classic = db.scalar(select(User.id).where(User.email == "a5@example.com"))
        staged = db.scalar(select(User.id).where(User.email == "a0@example.com"))
        live = load_daily(db, classic, "google_health", SYNC_START, SYNC_END)
        staged_live = load_daily(db, staged, "google_health", SYNC_START, SYNC_END)
    # A classic night has time asleep but no stages: missing, never 0.
    assert live["sleep_minutes"].notna().all()
    assert "rem_sleep_minutes" not in live.columns or live["rem_sleep_minutes"].isna().all()
    # A zone the heart rate never reached is a real 0 on every worn day.
    assert (staged_live["hr_zone_peak_minutes"] == 0).all()
    # Patterns' own efficiency: 470 of 480 minutes in bed rounds to 98, 430 to 90.
    first_baseline_day = pd.Timestamp(BASELINE[0])
    assert staged_live.loc[first_baseline_day, "time_in_bed"] == 480
    assert staged_live.loc[first_baseline_day, "sleep_efficiency"] in (98, 90)


def test_briefing_highlights_sleep_and_rem_is_retrieved_alike_in_app_and_mcp(teams, engine):
    a, _, _ = teams
    with session_scope(engine) as db:
        report = reports.build_report(db, db.get(Team, uuid.UUID(a)), reports.week_of(WEEK), NOW)
        headline, cited = report.headline.lower(), report.evidence
    # The weekly report highlights time asleep; REM is not among its metrics at all.
    assert "time asleep" in headline
    assert not any("rem_sleep_minutes" in e["metrics"] for e in cited.values())
    assert "rem_sleep_minutes" not in TEAM_METRICS

    client, headers = api(engine, "boss@example.com")
    listing = client.get(f"/teams/{a}/metrics", params={"week": "2026-10-14"}, headers=headers)
    assert listing.status_code == 200
    body = listing.json()
    assert body["state"] == "ready"
    assert body["week"] == {"start": "2026-10-12", "end": "2026-10-18"}
    assert body["baseline"] == {"start": "2026-09-14", "end": "2026-10-11"}
    assert body["madeOn"] == "2026-10-20"
    row = {
        m["metric"]: m for c in body["categories"] for g in c["subgroups"] for m in g["metrics"]
    }["rem_sleep_minutes"]
    assert row["state"] == "figure" and row["contributors"] == 5
    assert row["change"] == {"value": 20.0, "unit": "min", "text": "+20 min"}

    detail = client.get(f"/teams/{a}/metrics/2026-10-12/rem_sleep_minutes", headers=headers).json()
    assert detail["evidenceId"] == row["evidenceId"]
    assert detail["figureLabel"] == "Median change from each person's own previous 28 days"
    assert detail["coverage"] == {"contributors": 5, "minimum": 5, "roster": 7, "withAnyData": 7}
    assert (detail["higher"], detail["lower"], detail["unchanged"]) == (5, 0, 0)

    server = build_mcp(engine)
    error, mcp = call_mcp(
        server,
        user_id(engine, "boss@example.com"),
        "team_metric",
        team_id=a,
        metric="rem_sleep_minutes",
        week="2026-10-12",
    )
    assert not error
    assert mcp["evidence_id"] == row["evidenceId"]
    assert mcp["change"] == {"value": 20.0, "unit": "min", "text": "+20 min"}
    assert mcp["coverage"]["contributors"] == 5
    # The list through MCP is the app's list, field for field.
    error, mcp_list = call_mcp(
        server, user_id(engine, "boss@example.com"), "team_metrics", team_id=a, week="2026-10-12"
    )
    assert not error
    assert rows_of(mcp_list)["rem_sleep_minutes"]["evidence_id"] == row["evidenceId"]
    assert mcp_list["categories"] == explorer_view(engine, a)["categories"]


def explorer_view(engine, team_id: str) -> dict:
    with session_scope(engine) as db:
        return explorer.metrics_view(db, db.get(Team, uuid.UUID(team_id)), WEEK, NOW)


def test_hand_calculated_figures_for_sleep_movement_and_heart(teams, engine):
    a, _, _ = teams
    rows = rows_of(explorer_view(engine, a))
    figure = {k: (r["change"] or {}).get("value") for k, r in rows.items()}
    who = {k: r["contributors"] for k, r in rows.items()}
    assert figure["sleep_minutes"] == -60.0 and who["sleep_minutes"] == 7
    assert figure["time_in_bed"] == 0.0
    assert figure["bedtime_hour"] == 0  # 23:00 every night
    # Efficiency, Patterns-calculated: 14 nights at 98 and 14 at 90 (mean 94); the median member
    # sleeps 390 of 480 minutes in the week, 81.25 rounded to 81: 81 - 94 = -13 points.
    assert figure["sleep_efficiency"] == -13.0
    assert rows["sleep_efficiency"]["unit"] == "percentage points"
    assert figure["steps"] == 1000
    # Actual cardio-zone minutes rose by 10; weighted Active Zone Minutes by 20.
    assert figure["hr_zone_vigorous_minutes"] == 10.0
    assert figure["active_zone_minutes"] == 20.0
    assert figure["hr_zone_moderate_minutes"] == 0.0
    # Never in the peak zone: a figure of 0 from all seven, not a missing one.
    assert rows["hr_zone_peak_minutes"]["state"] == "figure"
    assert figure["hr_zone_peak_minutes"] == 0.0 and who["hr_zone_peak_minutes"] == 7
    # No resting heart rate or HRV was synced: unavailable, not 0.
    assert rows["resting_hr"]["state"] == "no_data" and rows["resting_hr"]["change"] is None
    assert "Unavailable" in rows["resting_hr"]["withheld"]


def test_five_qualifying_members_give_a_figure_and_four_withhold_it(teams, engine):
    a, b, _ = teams
    rem_a = rows_of(explorer_view(engine, a))["rem_sleep_minutes"]
    rem_b = rows_of(explorer_view(engine, b))["rem_sleep_minutes"]
    assert (rem_a["state"], rem_a["contributors"]) == ("figure", 5)
    assert (rem_b["state"], rem_b["contributors"], rem_b["change"]) == ("below_minimum", 4, None)
    assert rem_b["withheld"].startswith("Withheld: 4 of the 5 people needed")
    # The same team still has a time-asleep figure: coverage is applied per metric.
    sleep_b = rows_of(explorer_view(engine, b))["sleep_minutes"]
    assert (sleep_b["state"], sleep_b["contributors"]) == ("figure", 6)


def test_takeout_history_cannot_produce_or_fill_a_live_figure(teams, engine):
    a, _, c = teams
    # Team C has five members with Takeout days covering the week: no live figure at all.
    listing = explorer_view(engine, c)
    assert listing["members_with_data"] == 0
    assert {r["state"] for r in rows_of(listing).values()} == {"no_data"}
    # a5's Takeout REM (999 in the week) does not fill their classic live nights: still five
    # contributors and +20, where counting it would make six and move the median.
    rem = rows_of(explorer_view(engine, a))["rem_sleep_minutes"]
    assert (rem["contributors"], rem["change"]["value"]) == (5, 20.0)
    assert rows_of(explorer_view(engine, a))["steps"]["change"]["value"] == 1000


def test_another_teams_evidence_is_not_reachable(teams, engine):
    a, b, _ = teams
    client, headers = api(engine, "boss@example.com")
    assert client.get(f"/teams/{b}/metrics", headers=headers).status_code == 404
    assert (
        client.get(f"/teams/{b}/metrics/2026-10-12/rem_sleep_minutes", headers=headers).status_code
        == 404
    )
    error, text = call_mcp(
        build_mcp(engine),
        user_id(engine, "boss@example.com"),
        "team_metric",
        team_id=b,
        metric="sleep_minutes",
        week="2026-10-12",
    )
    assert error and "No such team" in text
    # An unknown metric is refused by name, never another record.
    response = client.get(f"/teams/{a}/metrics/2026-10-12/team_id", headers=headers)
    assert response.status_code == 404
    # A member is not a supervisor.
    member, member_headers = api(engine, "a0@example.com")
    assert member.get(f"/teams/{a}/metrics", headers=member_headers).status_code == 403


def test_a_historical_lookup_reveals_nothing_later(teams, engine):
    a, b, _ = teams
    client, headers = api(engine, "boss@example.com")
    first = client.get(f"/teams/{a}/metrics/2026-10-12/rem_sleep_minutes", headers=headers).json()
    # The week after had 600 everywhere, and none of it reached the figures above. Now a0's
    # week is re-synced with REM 400 a night; the figure shown stays as it was made.
    sync(engine, "a0@example.com", api_responses(SLEEP_DROPS[0], REM_RISES[0], rem_week=400))
    again = client.get(f"/teams/{a}/metrics/2026-10-12/rem_sleep_minutes", headers=headers).json()
    assert again["evidenceId"] == first["evidenceId"] and again["change"] == first["change"]
    assert again["madeOn"] == "2026-10-20"

    server, boss = build_mcp(engine), user_id(engine, "boss@example.com")
    # Asked as of a day before the figures were made: not available then.
    error, before = call_mcp(
        server, boss, "team_metric", team_id=a, metric="rem_sleep_minutes",
        week="2026-10-12", as_of="2026-10-19",
    )  # fmt: skip
    assert not error and before["state"] == "not_available_then" and "evidence_id" not in before
    error, then = call_mcp(
        server, boss, "team_metric", team_id=a, metric="rem_sleep_minutes",
        week="2026-10-12", as_of="2026-10-20",
    )  # fmt: skip
    assert not error and then["evidence_id"] == first["evidenceId"]

    # A past as_of with nothing stored is not made now from days synced since.
    other, other_headers = api(engine, "other@example.com")
    error, none_then = call_mcp(
        server, user_id(engine, "other@example.com"), "team_metrics", team_id=b,
        week="2026-10-12", as_of="2026-10-19",
    )  # fmt: skip
    assert not error and none_then["state"] == "not_available_then"
    with session_scope(engine) as db:
        stored = db.scalar(
            select(func.count())
            .select_from(TeamMetricWeek)
            .where(TeamMetricWeek.team_id == uuid.UUID(b))
        )
    assert stored == 0

    # The week in progress has no figures.
    current = client.get(f"/teams/{a}/metrics", params={"week": "2026-10-20"}, headers=headers)
    assert current.json()["state"] == "week_not_over" and current.json()["categories"] == []


def test_the_explorer_leaves_the_report_unchanged(teams, engine):
    a, _, _ = teams
    with session_scope(engine) as db:
        made = db.scalar(select(TeamReport).where(TeamReport.team_id == uuid.UUID(a)))
        sections_before = [s["metric"] for s in made.body["sections"]]
        headline_before = made.headline
    explorer_view(engine, a)
    with session_scope(engine) as db:
        # Remade from scratch after the explorer stored its figures: the same report.
        db.delete(db.scalar(select(TeamReport).where(TeamReport.team_id == uuid.UUID(a))))
        db.flush()
        after = reports.build_report(db, db.get(Team, uuid.UUID(a)), reports.week_of(WEEK), NOW)
        assert [s["metric"] for s in after.body["sections"]] == sections_before
        assert after.headline == headline_before
        assert {s["metric"] for s in after.body["sections"]} <= set(TEAM_METRICS)


def test_every_catalogue_metric_is_one_the_live_sync_writes():
    """The catalogue lists only columns `load_daily` produces, or Patterns' scores built from
    them; nothing the API lacks and nothing only Takeout has."""
    from app.sync.daily import NOT_IN_API

    live = set(load_daily_columns())
    scores = {"recovery_score", "strain", "stress_score"}
    for metric in explorer.CATALOG:
        assert metric.key in live or metric.key in scores, metric.key
        assert metric.key not in NOT_IN_API
    assert len({m.key for m in explorer.CATALOG}) == len(explorer.CATALOG)


def load_daily_columns() -> list[str]:
    from app.sync.daily import load_daily as live_daily

    return list(live_daily(api_responses(60, 20), SYNC_START, SYNC_END).frame.columns) + [
        "resting_hr",
        "hrv_ms",
    ]  # daily values this fake does not send; their parsing is tested in test_api_daily


def test_a_request_racing_another_returns_the_week_stored_first(teams, engine, monkeypatch):
    a, _, _ = teams
    shown = rows_of(explorer_view(engine, a))["rem_sleep_minutes"]["evidence_id"]
    # The race: this request's lookup misses, then its insert collides with the stored week.
    original, calls = explorer._stored, []

    def miss_once(db, team, week):
        calls.append(week)
        return None if len(calls) == 1 else original(db, team, week)

    monkeypatch.setattr(explorer, "_stored", miss_once)
    with session_scope(engine) as db:
        got = explorer.week_figures(db, db.get(Team, uuid.UUID(a)), reports.week_of(WEEK), NOW)
        assert got.results["rem_sleep_minutes"]["id"] == shown
        assert db.scalar(select(func.count()).select_from(TeamMetricWeek)) == 1


# The roster a week's figures describe (review of #267): the people in the team when that week's
# report was made, less any who have left since, never whoever is in the team when the week is
# first opened.
LATER_JOIN = NOW + timedelta(days=1)
OPENED = NOW + timedelta(days=2)


def reported_team(engine, prefix: str, size: int) -> str:
    """`size` people with staged nights, in the team since well before the week, and the week's
    report made at NOW."""
    team_id = team_with(
        engine,
        "boss@example.com",
        f"Team {prefix}",
        [
            (f"{prefix}{i}@example.com", api_responses(SLEEP_DROPS[i], REM_RISES[i % 5]))
            for i in range(size)
        ],
    )
    with session_scope(engine) as db:
        reports.build_report(db, db.get(Team, uuid.UUID(team_id)), reports.week_of(WEEK), NOW)
    return team_id


def join_later(engine, team_id: str, email: str, i: int) -> None:
    """Someone with qualifying readings from before and during the week, joining after the
    week's report was made."""
    sync(engine, email, api_responses(SLEEP_DROPS[i], REM_RISES[i % 5]))
    with session_scope(engine) as db:
        person = db.scalar(select(User).where(User.email == email))
        memberships.join(db, db.get(Team, uuid.UUID(team_id)), person, LATER_JOIN)


def both_interfaces(engine, team_id: str, metric: str, app_first: bool) -> tuple[dict, dict]:
    """The week opened for the first time through one interface, then read through the other."""
    client, headers = api(engine, "boss@example.com", now=OPENED)

    def app():
        url = f"/teams/{team_id}/metrics/2026-10-12/{metric}"
        response = client.get(url, headers=headers)
        assert response.status_code == 200
        return response.json()

    def mcp():
        error, out = call_mcp(
            build_mcp(engine),
            user_id(engine, "boss@example.com"),
            "team_metric",
            team_id=team_id,
            metric=metric,
            week="2026-10-12",
        )
        assert not error
        return out

    if app_first:
        from_app = app()
        return from_app, mcp()
    from_mcp = mcp()
    return app(), from_mcp


@pytest.mark.parametrize("app_first", [True, False], ids=["app first", "mcp first"])
def test_someone_who_joined_after_the_report_never_makes_an_old_week_qualify(engine, app_first):
    team_id = reported_team(engine, "h", 4)  # four in the team when the report was made
    join_later(engine, team_id, "late@example.com", 4)
    from_app, from_mcp = both_interfaces(engine, team_id, "sleep_minutes", app_first)
    # Withheld in both, from the four who belonged then: the fifth's readings do not count.
    assert (from_app["state"], from_app["change"]) == ("below_minimum", None)
    assert (from_mcp["state"], from_mcp["change"]) == ("below_minimum", None)
    assert from_app["coverage"]["contributors"] == from_mcp["coverage"]["contributors"] == 4
    assert from_app["coverage"]["roster"] == from_mcp["coverage"]["roster"] == 4
    assert from_app["withheld"].startswith("Withheld: 4 of the 5 people needed")
    assert from_app["evidenceId"] == from_mcp["evidence_id"]


@pytest.mark.parametrize("app_first", [True, False], ids=["app first", "mcp first"])
def test_five_who_belonged_at_the_report_give_the_same_figure_in_both(engine, app_first):
    team_id = reported_team(engine, "f", 5)
    from_app, from_mcp = both_interfaces(engine, team_id, "sleep_minutes", app_first)
    # Drops of 54, 56, 58, 60 and 62 min: the median is -58.
    expected = {"value": -58.0, "unit": "min", "text": "-58 min"}
    assert from_app["state"] == from_mcp["state"] == "figure"
    assert from_app["change"] == from_mcp["change"] == expected
    assert from_app["coverage"]["contributors"] == from_mcp["coverage"]["contributors"] == 5
    assert from_app["evidenceId"] == from_mcp["evidence_id"]


def test_someone_who_left_since_the_report_is_left_out_of_a_new_snapshot(engine):
    team_id = reported_team(engine, "w", 5)
    with session_scope(engine) as db:
        leaver = db.scalar(select(User).where(User.email == "w4@example.com"))
        memberships.leave(db, leaver, team_id, LATER_JOIN)
    from_app, from_mcp = both_interfaces(engine, team_id, "sleep_minutes", app_first=True)
    assert from_app["state"] == from_mcp["state"] == "below_minimum"
    assert from_app["coverage"]["contributors"] == 4
    assert from_app["coverage"]["roster"] == 5  # five belonged then; one has withdrawn since


def test_a_week_whose_roster_is_not_on_record_is_unavailable_and_stores_nothing(teams, engine):
    team_id = team_with(
        engine,
        "boss@example.com",
        "Unreported",
        [(f"u{i}@example.com", api_responses(SLEEP_DROPS[i], REM_RISES[i])) for i in range(5)],
    )  # no report for the week: who belonged then is not on record
    client, headers = api(engine, "boss@example.com", now=OPENED)
    listing = client.get(
        f"/teams/{team_id}/metrics", params={"week": "2026-10-12"}, headers=headers
    )
    assert listing.json()["state"] == "roster_unavailable"
    assert listing.json()["categories"] == []
    error, out = call_mcp(
        build_mcp(engine),
        user_id(engine, "boss@example.com"),
        "team_metric",
        team_id=team_id,
        metric="sleep_minutes",
        week="2026-10-12",
    )
    assert not error and out["state"] == "roster_unavailable" and "evidence_id" not in out
    with session_scope(engine) as db:
        stored = select(func.count()).select_from(TeamMetricWeek)
        assert db.scalar(stored.where(TeamMetricWeek.team_id == uuid.UUID(team_id))) == 0


@pytest.mark.parametrize("app_first", [True, False], ids=["app first", "mcp first"])
def test_a_leaver_and_a_replacement_leave_four_eligible_though_the_team_is_still_five(
    engine, app_first
):
    team_id = reported_team(engine, "s", 5)  # five in the team when the report was made
    with session_scope(engine) as db:
        leaver = db.scalar(select(User).where(User.email == "s4@example.com"))
        memberships.leave(db, leaver, team_id, LATER_JOIN)
    join_later(engine, team_id, "replacement@example.com", 4)  # qualifying earlier readings
    with session_scope(engine) as db:
        assert memberships.active_members(db, db.get(Team, uuid.UUID(team_id))) == 5
    from_app, from_mcp = both_interfaces(engine, team_id, "sleep_minutes", app_first)
    # The replacement did not belong then and the leaver has withdrawn: four eligible, withheld.
    assert from_app["state"] == from_mcp["state"] == "below_minimum"
    assert from_app["change"] is None and from_mcp["change"] is None
    assert from_app["coverage"]["contributors"] == from_mcp["coverage"]["contributors"] == 4
    assert from_app["withheld"].startswith("Withheld: 4 of the 5 people needed")
    assert from_app["evidenceId"] == from_mcp["evidence_id"]


@pytest.mark.parametrize("app_first", [True, False], ids=["app first", "mcp first"])
def test_someone_who_left_and_rejoined_since_the_report_is_not_a_contributor(engine, app_first):
    team_id = reported_team(engine, "r", 5)  # five in the team when the report was made
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        person = db.scalar(select(User).where(User.email == "r4@example.com"))
        memberships.leave(db, person, team_id, LATER_JOIN)
        memberships.join(db, team, person, LATER_JOIN + timedelta(hours=1))  # a new record
        assert memberships.active_members(db, team) == 5
    from_app, from_mcp = both_interfaces(engine, team_id, "sleep_minutes", app_first)
    # Their membership at the report ended; the one they hold now began after it. Five belonged
    # then, four are eligible, and the figure is withheld in both.
    assert from_app["coverage"]["roster"] == from_mcp["coverage"]["roster"] == 5
    assert from_app["coverage"]["contributors"] == from_mcp["coverage"]["contributors"] == 4
    assert from_app["state"] == from_mcp["state"] == "below_minimum"
    assert from_app["change"] is None and from_mcp["change"] is None
    assert from_app["evidenceId"] == from_mcp["evidence_id"]
