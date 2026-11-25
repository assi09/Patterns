# ruff: noqa: F811 (the fixtures imported from test_google_connect)
"""Google Calendar: events reduced to daily counts (never stored as events), the privacy of what is
asked for, the sync, and the team's meeting load under the team rules."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx2
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from test_google_connect import (  # noqa: F401 (fixtures)
    NOW,
    box,
    client,
    credentials,
    engine,
    oauth,
    signed_in,
)

from app.analysis.evidence import Window
from app.analysis.team_calendar import team_load
from app.api import google
from app.db.daily import load_daily, save_daily
from app.db.models import DailyMetric, GoogleConnection, SyncRun, User
from app.db.session import session_scope
from app.sync import calendar
from app.sync.connections import save_connection
from app.sync.google_auth import SyncError
from app.teams import memberships

BEIRUT = ZoneInfo("Asia/Beirut")
MONDAY = date(2026, 11, 16)


def at(day: date, hour: int, minute: int = 0) -> str:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=BEIRUT).isoformat()


def meeting(day, start, end, **extra) -> dict:
    """A timed event with the person and one other attendee."""
    return {
        "status": "confirmed",
        "start": {"dateTime": at(day, *start)},
        "end": {"dateTime": at(day, *end)},
        "attendees": [{"self": True, "responseStatus": "accepted"}, {}],
        **extra,
    }


def load(events, first=MONDAY, last=MONDAY + timedelta(days=6)) -> pd.DataFrame:
    return calendar.daily_load(events, BEIRUT, first, last)


# Reducing events to counts


def test_a_meeting_counts_once_even_when_overlapping():
    day = load([meeting(MONDAY, (10, 0), (11, 0)), meeting(MONDAY, (10, 30), (11, 30))]).iloc[0]
    assert day.meeting_minutes == 90
    assert day.meetings == 2


@pytest.mark.parametrize(
    "event",
    [
        meeting(MONDAY, (10, 0), (11, 0), status="cancelled"),
        meeting(MONDAY, (10, 0), (11, 0), transparency="transparent"),
        meeting(
            MONDAY,
            (10, 0),
            (11, 0),
            attendees=[{"self": True, "responseStatus": "declined"}, {}],
        ),
        {**meeting(MONDAY, (10, 0), (11, 0)), "attendees": []},  # a block for oneself
        {
            "status": "confirmed",
            "start": {"date": MONDAY.isoformat()},
            "end": {"date": (MONDAY + timedelta(days=1)).isoformat()},
            "attendees": [{"self": True}, {}],
        },  # all day
    ],
)
def test_what_is_not_a_meeting_is_left_out(event):
    day = load([event]).iloc[0]
    assert day.meeting_minutes == 0 and day.meetings == 0


def test_after_hours_and_weekends():
    saturday = MONDAY + timedelta(days=5)
    frame = load(
        [
            meeting(MONDAY, (7, 0), (9, 0)),  # an hour before 08:00
            meeting(MONDAY, (17, 30), (19, 0)),  # an hour after 18:00
            meeting(saturday, (11, 0), (12, 0)),  # all of it
        ]
    )
    assert frame.loc[pd.Timestamp(MONDAY), "after_hours_minutes"] == 120
    assert frame.loc[pd.Timestamp(saturday), "after_hours_minutes"] == 60


def test_back_to_back_and_focus_and_out_of_office():
    tuesday = MONDAY + timedelta(days=1)
    frame = load(
        [
            meeting(MONDAY, (9, 0), (10, 0)),
            meeting(MONDAY, (10, 3), (11, 0)),  # within five minutes
            meeting(MONDAY, (11, 30), (12, 0)),  # a real break
            {**meeting(MONDAY, (14, 0), (16, 0)), "eventType": "focusTime", "attendees": []},
            {**meeting(tuesday, (0, 0), (23, 59)), "eventType": "outOfOffice", "attendees": []},
        ]
    )
    monday = frame.loc[pd.Timestamp(MONDAY)]
    assert monday.back_to_back == 1
    assert monday.focus_minutes == 120
    assert frame.loc[pd.Timestamp(tuesday), "out_of_office"] == 1
    assert frame.loc[pd.Timestamp(tuesday), "meeting_minutes"] == 0


def test_a_meeting_across_midnight_is_split_by_local_day():
    event = {
        **meeting(MONDAY, (23, 0), (23, 0)),
        "end": {"dateTime": at(MONDAY + timedelta(days=1), 1, 0)},
    }
    frame = load([event])
    assert list(frame.meeting_minutes.iloc[:2]) == [60, 60]


def test_times_in_utc_land_on_the_local_day():
    # 23:30 UTC on Sunday is 01:30 on Monday in Beirut.
    sunday = MONDAY - timedelta(days=1)
    event = {
        **meeting(MONDAY, (0, 0), (0, 0)),
        "start": {"dateTime": f"{sunday.isoformat()}T23:30:00Z"},
        "end": {"dateTime": f"{sunday.isoformat()}T23:45:00Z"},
    }
    frame = load([event])
    assert frame.loc[pd.Timestamp(MONDAY), "meeting_minutes"] == 15


def test_every_day_in_range_is_a_value_and_nothing_else_is_kept():
    frame = load([])
    assert len(frame) == 7
    assert (frame.values == 0).all()
    assert list(frame.columns) == list(calendar.METRICS)


# What is asked of Google


class FakeCalendar:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(200, json=self.pages.pop(0))


def test_only_times_are_asked_for_and_every_page_is_read():
    api = FakeCalendar(
        {"items": [meeting(MONDAY, (9, 0), (10, 0))], "nextPageToken": "p2"},
        {"items": [meeting(MONDAY, (11, 0), (12, 0))]},
    )
    client = calendar.CalendarClient(
        lambda: "token", http=httpx2.Client(transport=httpx2.MockTransport(api))
    )
    start = datetime(2026, 11, 16, tzinfo=UTC)
    events = list(client.events(start, start + timedelta(days=7)))
    assert len(events) == 2
    first = api.requests[0].url.params
    assert first["singleEvents"] == "true"
    for field in ("summary", "description", "location", "email", "displayName"):
        assert field not in first["fields"]
    assert api.requests[1].url.params["pageToken"] == "p2"


# The sync


def fake_client(api):
    def client_for(token):
        return calendar.CalendarClient(
            token,
            http=httpx2.Client(transport=httpx2.MockTransport(api)),
            max_retries=0,
            sleep=lambda _: None,
        )

    return client_for


def connected_person(engine, box):
    """Someone who connected Google Calendar (its own sign-in)."""
    with session_scope(engine) as db:
        person = User(email="p@example.com", status="approved")
        db.add(person)
        db.flush()
        calendar.save_connection(db, box, person.id, credentials())
        return person.id


def test_sync_stores_counts_under_their_own_source(engine, box):
    person_id = connected_person(engine, box)
    api = FakeCalendar({"items": [meeting(MONDAY, (9, 0), (10, 0))]})
    sessions = lambda: session_scope(engine)  # noqa: E731
    written = calendar.sync(sessions, box, person_id, BEIRUT, MONDAY, fake_client(api))
    assert written == calendar.DAYS_BACK + calendar.DAYS_AHEAD + 1
    with session_scope(engine) as db:
        frame = load_daily(db, person_id, calendar.SOURCE)
        assert frame.loc[pd.Timestamp(MONDAY), "meeting_minutes"] == 60
        assert load_daily(db, person_id, "google_health").empty  # one source per history
        run = db.scalar(select(SyncRun).where(SyncRun.source == calendar.SOURCE))
        assert run.status == "succeeded" and run.days_written == written


class Failing:
    def __init__(self, status: int):
        self.status = status

    def __call__(self, request):
        return httpx2.Response(self.status, json={"error": {"message": "Backend Error"}})


@pytest.mark.parametrize("status", [500, 403])
def test_a_failed_sync_is_saved_as_failed_and_shown(engine, box, client, status):
    """Regression: the failure used to roll back with the work it interrupted, so Settings kept
    saying it was reading, or showed an older success."""
    headers = signed_in(client, engine)
    with session_scope(engine) as db:
        person = db.scalar(select(User).where(User.email == "person@example.com"))
        calendar.save_connection(db, box, person.id, credentials())
        person_id = person.id
    sessions = lambda: session_scope(engine)  # noqa: E731
    calendar.sync(
        sessions, box, person_id, BEIRUT, MONDAY, fake_client(FakeCalendar({"items": []}))
    )
    with pytest.raises(SyncError):
        calendar.sync(sessions, box, person_id, BEIRUT, MONDAY, fake_client(Failing(status)))
    with session_scope(engine) as db:
        runs = db.scalars(
            select(SyncRun).where(SyncRun.source == calendar.SOURCE).order_by(SyncRun.started_at)
        ).all()
        assert [r.status for r in runs] == ["succeeded", "failed"]
        assert runs[-1].error and runs[-1].finished_at is not None
    shown = client.get("/calendar/status", headers=headers).json()
    assert shown["lastError"] == runs[-1].error  # Settings says the latest sync failed


def test_the_background_sync_records_a_failure_without_raising(engine, box):
    person_id = connected_person(engine, box)
    with session_scope(engine) as db:
        calendar.save_connection(db, box, person_id, credentials())
    sessions = lambda: session_scope(engine)  # noqa: E731
    original = calendar.CalendarClient
    calendar.CalendarClient = lambda token: original(  # type: ignore[misc]
        token, http=httpx2.Client(transport=httpx2.MockTransport(Failing(500))), max_retries=0
    )
    try:
        assert calendar.sync_person(sessions, box, person_id, MONDAY, "UTC") == 0
    finally:
        calendar.CalendarClient = original
    with session_scope(engine) as db:
        assert (
            db.scalar(select(SyncRun.status).where(SyncRun.source == calendar.SOURCE)) == "failed"
        )


def test_without_the_calendar_scope_nothing_is_read(engine, box):
    with session_scope(engine) as db:
        person = User(email="p@example.com", status="approved")
        db.add(person)
        db.flush()
        save_connection(db, box, person.id, credentials())
        person_id = person.id
    assert calendar.sync_person(lambda: session_scope(engine), box, person_id, MONDAY, "UTC") == 0
    with session_scope(engine) as db:
        assert db.scalar(select(SyncRun).where(SyncRun.source == calendar.SOURCE)) is None


def test_the_calendar_gets_its_own_sign_in_and_health_never_carries_it(client, engine):
    """Regression: the calendar permission was added to Google Health's sign-in, and Google's
    Health API refuses a token that carries it, so health syncs stopped. The calendar now asks
    for that permission alone, kept in its own connection; a health sign-in never includes it."""
    headers = signed_in(client, engine)
    url = client.post("/google/connect", headers=headers, json={"capability": "calendar"})
    state = parse_qs(urlparse(url.json()["url"]).query)["state"][0]
    assert tuple(google.sign_ins._pending[state].scopes) == (calendar.SCOPE,)
    callback = client.get("/google/callback", params={"state": state, "code": "c"})
    assert callback.headers["location"].endswith("google=connected")
    with session_scope(engine) as db:
        person = db.scalar(select(User).where(User.email == "person@example.com"))
        assert calendar.connection_for(db, person.id) is not None
        assert db.get(GoogleConnection, person.id) is None  # health untouched
    again = client.post("/google/connect", headers=headers).json()["url"]
    state = parse_qs(urlparse(again).query)["state"][0]
    assert calendar.SCOPE not in google.sign_ins._pending[state].scopes


def test_a_shared_token_from_before_is_split_by_the_migration(tmp_path):
    """Upgrading moves a Google Health token that carried the calendar permission to the
    calendar's own connection and asks for Google Health to be connected again."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    url = f"sqlite:///{tmp_path / 'm.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "0035")
    db = create_engine(url)
    with db.begin() as conn:
        uid = uuid.uuid4().hex
        conn.execute(
            text(
                "INSERT INTO users (id, email, status, role, created_at) "
                "VALUES (:id, 'a@x.com', 'approved', 'member', '2026-11-25')"
            ),
            {"id": uid},
        )
        conn.execute(
            text(
                "INSERT INTO google_connections "
                "(user_id, encrypted_token, scopes, status, connected_at, updated_at) "
                "VALUES (:id, :t, :s, 'active', '2026-11-25', '2026-11-25')"
            ),
            {"id": uid, "t": b"sealed", "s": json.dumps(["health", calendar.SCOPE])},
        )
    command.upgrade(config, "head")
    with db.begin() as conn:
        health = conn.execute(text("SELECT status, scopes FROM google_connections")).one()
        moved = conn.execute(text("SELECT scopes, status FROM calendar_connections")).one()
    assert health.status == "reconnect_needed" and calendar.SCOPE not in json.loads(health.scopes)
    assert json.loads(moved.scopes) == [calendar.SCOPE] and moved.status == "active"


# The team's load


def member_frame(seed: int, extra: float = 0.0, days: int = 50) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.date_range(MONDAY - timedelta(days=days - 14), periods=days, name="date")
    frame = pd.DataFrame(0.0, index=index, columns=list(calendar.METRICS))
    frame["meeting_minutes"] = rng.normal(180, 30, days).clip(0)
    week = (index >= pd.Timestamp(MONDAY)) & (index <= pd.Timestamp(MONDAY + timedelta(days=6)))
    frame.loc[week, "meeting_minutes"] += extra
    return frame


WEEK = Window(start=MONDAY, end=MONDAY + timedelta(days=6))


def test_a_heavier_week_shows_in_the_team_load():
    load = {e.metrics[0]: e for e in team_load([member_frame(i, 120) for i in range(6)], WEEK)}
    meetings = load["meeting_minutes"]
    assert meetings.sufficient and meetings.n == 6
    assert meetings.stats["median_change"] > 600  # two more hours a day, seven days
    assert meetings.stats["members_up"] == 6
    assert "median_planned" in meetings.stats


def test_fewer_than_five_people_give_no_figures():
    for e in team_load([member_frame(i, 120) for i in range(4)], WEEK):
        assert not e.sufficient
        assert set(e.stats) == {"label", "unit", "members", "minimum"}


def test_a_member_without_a_usual_week_is_left_out():
    short = member_frame(9, days=20)  # starts six days before the week
    load = team_load([member_frame(i) for i in range(5)] + [short], WEEK)
    assert load[0].n == 5


def test_the_team_endpoint_is_the_supervisors_and_aggregates_only(client, engine):
    boss_headers = signed_in(client, engine, "boss@example.com")
    with session_scope(engine) as db:
        boss = db.scalar(select(User).where(User.email == "boss@example.com"))
        boss.role = "supervisor"
        team = memberships.create_team(db, boss, "Design", None, datetime.now(UTC))
        for i in range(6):
            person = User(email=f"m{i}@example.com", status="approved")
            db.add(person)
            db.flush()
            save_daily(db, person.id, calendar.SOURCE, member_frame(i, 120))
            memberships.join(db, team, person, datetime.now(UTC))
        team_id = str(team.id)
    body = client.get(
        f"/teams/{team_id}/calendar", headers=boss_headers, params={"week": MONDAY.isoformat()}
    ).json()
    assert body["connected"] == 6
    meetings = next(m for m in body["metrics"] if m["metric"] == "meeting_minutes")
    assert meetings["sufficient"] and meetings["membersUp"] == 6
    assert "m0@example.com" not in str(body)
    member = signed_in(client, engine, "someone@example.com")
    assert client.get(f"/teams/{team_id}/calendar", headers=member).status_code == 403


def test_a_person_sees_their_own_days_and_status(client, engine):
    headers = signed_in(client, engine)
    assert client.get("/calendar/status", headers=headers).json()["connected"] is False
    with session_scope(engine) as db:
        person = db.scalar(select(User).where(User.email == "person@example.com"))
        days = pd.date_range(NOW.date() - timedelta(days=19), periods=20, name="date")
        frame = pd.DataFrame(30.0, index=days, columns=list(calendar.METRICS))
        save_daily(db, person.id, calendar.SOURCE, frame)
    days = client.get("/me/calendar", headers=headers).json()
    assert days and set(days[0]) == {"date"} | {
        "meetingMinutes",
        "meetings",
        "afterHoursMinutes",
        "backToBack",
        "focusMinutes",
        "outOfOffice",
    }
    assert client.get("/calendar/status", headers=headers).json()["days"] == 20


def test_calendar_rows_never_mix_with_health_rows(engine):
    with session_scope(engine) as db:
        person = User(email="p@example.com", status="approved")
        db.add(person)
        db.flush()
        save_daily(db, person.id, calendar.SOURCE, member_frame(1))
        sources = set(db.scalars(select(DailyMetric.source)))
    assert sources == {calendar.SOURCE}


@pytest.mark.parametrize(
    ("health", "expected"),
    [
        ("succeeds", ["health", "checkin"]),
        ("finds nothing new", ["health"]),  # no successful run: no check-in
        ("raises", ["health"]),  # a crash stops neither the server nor the calendar's own run
    ],
)
def test_after_a_health_sync_the_check_in_rule_only_if_it_succeeded(monkeypatch, health, expected):
    calls = []

    def fake_health(sessions, box, user_id, health_for, today):
        calls.append("health")
        if health == "raises":
            raise RuntimeError("boom")

    monkeypatch.setattr(google.connections, "sync", fake_health)
    monkeypatch.setattr(
        google.connections, "succeeded_since", lambda db, uid, since: health == "succeeds"
    )
    monkeypatch.setattr(google.checkin, "after_sync", lambda db, uid, now: calls.append("checkin"))

    class Session:
        def __enter__(self):
            return None

        def __exit__(self, *exc):
            return False

    google.sync_health(google.GoogleParts(None, None, None), Session, uuid.uuid4(), MONDAY)
    assert calls == expected


def test_a_failing_calendar_sync_is_contained(monkeypatch):
    def broken(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(google.calendar, "sync_person", broken)
    google.sync_calendar(google.GoogleParts(None, None, None), None, uuid.uuid4(), MONDAY)


# Two sign-ins, scheduled and disconnected apart


def wait_for(registry):
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and registry._running:
        time.sleep(0.02)
    assert not registry._running


def scheduler_parts(monkeypatch, oauth, box, api):
    from test_google_connect import FakeHealth

    from app import background
    from app.api.google import GoogleParts
    from app.sync.connections import Syncs

    monkeypatch.setattr(google, "get_google", lambda: GoogleParts(oauth, box, FakeHealth))
    monkeypatch.setattr(google, "syncs", Syncs())
    monkeypatch.setattr(google, "calendar_syncs", Syncs())
    original = calendar.CalendarClient
    monkeypatch.setattr(
        calendar,
        "CalendarClient",
        lambda token: original(
            token, http=httpx2.Client(transport=httpx2.MockTransport(api)), max_retries=0
        ),
    )
    return background


def test_the_calendar_keeps_syncing_when_google_health_has_expired(engine, box, oauth, monkeypatch):
    """Regression: the scheduler only picked people with an active Google Health sign-in, so a
    calendar that was still connected stopped updating once Health expired."""
    background = scheduler_parts(
        monkeypatch, oauth, box, FakeCalendar({"items": [meeting(MONDAY, (9, 0), (10, 0))]})
    )
    with session_scope(engine) as db:
        person = User(email="p@example.com", status="approved")
        db.add(person)
        db.flush()
        save_connection(db, box, person.id, credentials())
        db.get(GoogleConnection, person.id).status = "reconnect_needed"  # Health expired
        calendar.save_connection(db, box, person.id, credentials())
        person_id = person.id
    sessions = lambda: session_scope(engine)  # noqa: E731
    now = datetime.now(UTC)
    assert background.start_due_syncs(now, sessions) == 1  # the calendar, on its own
    wait_for(google.calendar_syncs)
    with session_scope(engine) as db:
        runs = db.scalars(select(SyncRun).where(SyncRun.user_id == person_id)).all()
    assert [(r.source, r.status) for r in runs] == [(calendar.SOURCE, "succeeded")]
    assert background.start_due_syncs(now + timedelta(minutes=20), sessions) == 0  # not so soon
    assert background.start_due_syncs(now + timedelta(minutes=40), sessions) == 1  # every 30 min


def test_google_health_keeps_syncing_after_the_calendar_is_disconnected(
    client, engine, box, oauth, monkeypatch
):
    """Disconnecting the calendar removes only its sign-in; Google Health stays connected and is
    still scheduled, and the calendar is no longer read."""
    background = scheduler_parts(monkeypatch, oauth, box, FakeCalendar())
    headers = signed_in(client, engine)
    with session_scope(engine) as db:
        person = db.scalar(select(User).where(User.email == "person@example.com"))
        save_connection(db, box, person.id, credentials())
        calendar.save_connection(db, box, person.id, credentials())
        person_id = person.id
    assert client.get("/calendar/status", headers=headers).json()["connected"] is True
    off = client.post("/calendar/disconnect", headers=headers)
    assert off.status_code == 200 and off.json()["connected"] is False
    assert client.get("/google/status", headers=headers).json()["status"] == "active"
    with session_scope(engine) as db:
        assert calendar.connection_for(db, person_id) is None
        assert db.get(GoogleConnection, person_id) is not None
    sessions = lambda: session_scope(engine)  # noqa: E731
    assert background.start_due_syncs(datetime.now(UTC), sessions) == 1  # Google Health only
    wait_for(google.syncs)
    with session_scope(engine) as db:
        sources = {
            r.source for r in db.scalars(select(SyncRun).where(SyncRun.user_id == person_id))
        }
    assert sources == {"google_health"}


def test_disconnecting_google_health_leaves_the_calendar(client, engine, box):
    headers = signed_in(client, engine)
    with session_scope(engine) as db:
        person = db.scalar(select(User).where(User.email == "person@example.com"))
        save_connection(db, box, person.id, credentials())
        calendar.save_connection(db, box, person.id, credentials())
    client.post("/google/disconnect", headers=headers)
    assert client.get("/calendar/status", headers=headers).json()["connected"] is True


def test_sync_now_does_not_start_a_second_calendar_run_while_one_is_running(
    client, engine, box, oauth, monkeypatch
):
    """Regression: connecting or "Sync now" ran the calendar outside the calendar registry, so
    a scheduled calendar run already in progress could be joined by a second, both fetching and
    writing the same person's calendar. Every start now goes through the one registry."""
    import threading

    release, entered = threading.Event(), threading.Event()
    fetches: list[int] = []

    def held_api(request):
        fetches.append(1)
        entered.set()
        release.wait(5)  # the scheduled run stays inside its fetch until released
        return httpx2.Response(200, json={"items": []})

    background = scheduler_parts(monkeypatch, oauth, box, held_api)
    headers = signed_in(client, engine)
    with session_scope(engine) as db:
        person = db.scalar(select(User).where(User.email == "person@example.com"))
        save_connection(db, box, person.id, credentials())
        calendar.save_connection(db, box, person.id, credentials())
        person_id = person.id
    sessions = lambda: session_scope(engine)  # noqa: E731
    background.start_due_syncs(datetime.now(UTC), sessions)
    assert entered.wait(5)  # the scheduled calendar run is fetching
    assert google.calendar_syncs.running(person_id)

    synced = client.post("/google/sync", headers=headers, json={"force": True})
    assert synced.status_code == 202
    release.set()
    wait_for(google.calendar_syncs)
    wait_for(google.syncs)

    assert len(fetches) == 1  # one calendar fetch, not two
    with session_scope(engine) as db:
        runs = db.scalars(
            select(SyncRun).where(SyncRun.user_id == person_id, SyncRun.source == calendar.SOURCE)
        ).all()
    assert len(runs) == 1
