"""Google Calendar, read-only, reduced to daily counts of a person's meeting load (docs/pivot.md).

The calendar is the cause side of the team product: meeting load, meetings after hours and
back-to-back days beside the team's sleep and recovery. Privacy is kept by what is asked for and
what is stored:

- **Asked for:** only times, status, event type, transparency and the person's own response
  (`FIELDS`). Titles, descriptions, locations and other attendees' names never leave Google.
- **Stored:** daily counts per person under the source `google_calendar`, in the same daily
  table as the Fitbit metrics; never an event.

Rules, all in `daily_load` and its constants:
- cancelled events, all-day events, events marked free and events the person declined are left out;
- a **meeting** is a timed event with at least one other attendee; overlapping meetings count once;
- **after hours** is meeting time outside WORK_START to WORK_END local time, and all weekend time;
- **back to back** counts meetings that start within BACK_TO_BACK of the previous one's end;
- **focus time** and **out of office** come from Google's own event types.
Days in the synced range without events are stored as zero: no meetings is a value, not a gap.
"""

import logging
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from sqlalchemy.orm import Session

from app.db.daily import load_daily, save_daily
from app.db.models import CalendarConnection, SyncRun, User
from app.sync.client import HealthClient
from app.sync.connections import TokenBox
from app.sync.google_auth import ReconnectNeeded, SyncError

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
SOURCE = "google_calendar"
# Days a member approved from a harness (docs/mcp.md): the same counts, labelled by where they came
# from. A person's calendar is read from one source only, Google's when connected.
HARNESS_SOURCE = "harness_calendar"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
FIELDS = (
    "nextPageToken,items(status,eventType,transparency,start(dateTime,date),"
    "end(dateTime,date),attendees(self,responseStatus))"
)
WORK_START = time(8, 0)
WORK_END = time(18, 0)
WEEKEND = (5, 6)  # Saturday and Sunday
BACK_TO_BACK = timedelta(minutes=5)
DAYS_BACK = 63  # nine weeks: this week, the four before it as a baseline, and room for more
DAYS_AHEAD = 14  # what is already planned shows a crunch coming
METRICS = (
    "meeting_minutes",
    "meetings",
    "after_hours_minutes",
    "back_to_back",
    "focus_minutes",
    "out_of_office",
)


class CalendarClient(HealthClient):
    """The Google API client's paging, timeouts and retries, pointed at Calendar."""

    def events(self, start: datetime, end: datetime) -> Iterator[dict]:
        params: dict[str, str | int] = {
            "timeMin": start.astimezone(UTC).isoformat(),
            "timeMax": end.astimezone(UTC).isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 250,
            "fields": FIELDS,
        }
        while True:
            body = self._request("GET", EVENTS_URL, params=params)
            yield from body.get("items", [])
            token = body.get("nextPageToken")
            if not token:
                return
            params = {**params, "pageToken": token}


def connection_for(session: Session, user_id: uuid.UUID) -> CalendarConnection | None:
    """The person's own calendar sign-in, apart from Google Health's, if they made one."""
    return session.get(CalendarConnection, user_id)


def save_connection(
    session: Session, box: TokenBox, user_id: uuid.UUID, credentials
) -> CalendarConnection:
    """Keeps the calendar sign-in on its own. Google's Health API refuses a token that also
    carries the calendar permission, so the calendar never shares Google Health's token."""
    if not credentials.refresh_token:
        raise ReconnectNeeded("Google did not return a lasting sign-in; connect again.")
    connection = session.get(CalendarConnection, user_id) or CalendarConnection(user_id=user_id)
    connection.encrypted_token = box.seal(credentials)
    connection.scopes = sorted(credentials.granted_scopes or credentials.scopes or [])
    connection.status = "active"
    session.add(connection)
    session.flush()
    return connection


def credentials_for(session: Session, box: TokenBox, user_id: uuid.UUID):
    """Valid calendar credentials, refreshed and stored again if needed; marks a dead sign-in."""
    connection = connection_for(session, user_id)
    if connection is None or connection.status != "active":
        raise ReconnectNeeded("Connect Google Calendar first.")
    credentials = box.open(connection.encrypted_token)
    if credentials.valid:
        return credentials
    try:
        credentials.refresh(Request())
    except RefreshError as exc:
        connection.status = "reconnect_needed"
        session.commit()  # kept although the caller's session rolls back on the error
        raise ReconnectNeeded(
            "Your Google Calendar sign-in expired (in testing it lasts 7 days); connect again."
        ) from exc
    connection.encrypted_token = box.seal(credentials)
    return credentials


# --- reducing events to daily counts --------------------------------------------------------


def _moment(value: dict, zone: ZoneInfo) -> datetime | None:
    if "dateTime" not in value:
        return None  # an all-day event
    return datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00")).astimezone(zone)


def _declined(event: dict) -> bool:
    return any(
        a.get("self") and a.get("responseStatus") == "declined" for a in event.get("attendees", [])
    )


def _is_meeting(event: dict) -> bool:
    return event.get("eventType", "default") == "default" and len(event.get("attendees", [])) >= 2


def _by_day(start: datetime, end: datetime) -> Iterator[tuple[date, datetime, datetime]]:
    """Splits [start, end) at local midnights."""
    while start < end:
        midnight = datetime.combine(start.date() + timedelta(days=1), time(0), start.tzinfo)
        piece = min(end, midnight)
        yield start.date(), start, piece
        start = piece


def _union_minutes(spans: list[tuple[datetime, datetime]]) -> float:
    total, current_start, current_end = 0.0, None, None
    for start, end in sorted(spans):
        if current_end is None or start > current_end:
            if current_end is not None:
                total += (current_end - current_start).total_seconds() / 60
            current_start, current_end = start, end
        else:
            current_end = max(current_end, end)
    if current_end is not None:
        total += (current_end - current_start).total_seconds() / 60
    return total


def _after_hours(spans: list[tuple[datetime, datetime]]) -> float:
    outside = []
    for start, end in spans:
        if start.weekday() in WEEKEND:
            outside.append((start, end))
            continue
        open_ = datetime.combine(start.date(), WORK_START, start.tzinfo)
        close = datetime.combine(start.date(), WORK_END, start.tzinfo)
        if start < open_:
            outside.append((start, min(end, open_)))
        if end > close:
            outside.append((max(start, close), end))
    return _union_minutes(outside)


def daily_load(events: list[dict], zone: ZoneInfo, first: date, last: date) -> pd.DataFrame:
    """One row per local day in [first, last] with the counts in METRICS."""
    meetings: dict[date, list[tuple[datetime, datetime]]] = {}
    focus: dict[date, list[tuple[datetime, datetime]]] = {}
    away: set[date] = set()
    for event in events:
        if event.get("status") == "cancelled" or _declined(event):
            continue
        start, end = _moment(event.get("start", {}), zone), _moment(event.get("end", {}), zone)
        if start is None or end is None or end <= start:
            continue
        kind = event.get("eventType", "default")
        for day, piece_start, piece_end in _by_day(start, end):
            if kind == "outOfOffice":
                away.add(day)
            elif kind == "focusTime":
                focus.setdefault(day, []).append((piece_start, piece_end))
            elif _is_meeting(event) and event.get("transparency") != "transparent":
                meetings.setdefault(day, []).append((piece_start, piece_end))
    rows = []
    days = pd.date_range(first, last, name="date")
    for stamp in days:
        day = stamp.date()
        spans = sorted(meetings.get(day, []))
        back_to_back = sum(
            1
            for previous, current in zip(spans, spans[1:], strict=False)
            if timedelta(0) <= current[0] - previous[1] <= BACK_TO_BACK
        )
        rows.append(
            {
                "meeting_minutes": round(_union_minutes(spans), 1),
                "meetings": len(spans),
                "after_hours_minutes": round(_after_hours(spans), 1),
                "back_to_back": back_to_back,
                "focus_minutes": round(_union_minutes(focus.get(day, [])), 1),
                "out_of_office": 1 if day in away else 0,
            }
        )
    return pd.DataFrame(rows, index=days, columns=list(METRICS))


# --- syncing --------------------------------------------------------------------------------


def sync(
    sessions,
    box: TokenBox,
    user_id: uuid.UUID,
    zone: ZoneInfo,
    today: date,
    client_for: Callable[[Callable[[], str]], CalendarClient] | None = None,
) -> int:
    """Reads the person's calendar from DAYS_BACK before today to DAYS_AHEAD after, stores the
    daily counts and returns the number of days written; raises what stopped it.

    The sync run is opened and closed in transactions of its own, so a failure is recorded even
    though the work it interrupted is rolled back: Settings then says the latest sync failed
    instead of still reading, or showing an older success.
    """
    first, last = today - timedelta(days=DAYS_BACK), today + timedelta(days=DAYS_AHEAD)
    with sessions() as session:
        run = SyncRun(
            user_id=user_id,
            source=SOURCE,
            status="running",
            range_start=first,
            range_end=last + timedelta(days=1),
            started_at=datetime.now(UTC),
        )
        session.add(run)
        session.flush()
        run_id = run.id
    try:
        with sessions() as session:
            credentials = credentials_for(session, box, user_id)
            client = (client_for or CalendarClient)(lambda: credentials.token)
            start = datetime.combine(first, time(0), zone)
            end = datetime.combine(last + timedelta(days=1), time(0), zone)
            frame = daily_load(list(client.events(start, end)), zone, first, last)
            written = save_daily(session, user_id, SOURCE, frame)
            done = session.get(SyncRun, run_id)
            done.status, done.days_written, done.finished_at = "succeeded", written, _now()
        return written
    except Exception as exc:
        with sessions() as session:
            failed = session.get(SyncRun, run_id)
            failed.status = "failed"
            failed.error = (
                str(exc)[:500] if isinstance(exc, SyncError) else "The calendar sync failed."
            )
            failed.finished_at = _now()
        raise


def _now() -> datetime:
    return datetime.now(UTC)


def sync_person(
    sessions, box: TokenBox, user_id: uuid.UUID, today: date, fallback_zone: str
) -> int:
    """For background syncs: the calendar of someone who allowed it, in their own time zone.
    Failures are recorded on the sync run and logged, not raised; returns the days written."""
    with sessions() as session:
        connection = connection_for(session, user_id)
        if connection is None or connection.status != "active":
            return 0
        user = session.get(User, user_id)
        try:
            zone = ZoneInfo(user.timezone or fallback_zone)
        except (ValueError, KeyError):
            zone = ZoneInfo("UTC")
    try:
        return sync(sessions, box, user_id, zone, today)
    except SyncError as exc:
        logger.warning("Calendar sync stopped: %s", exc)
    except Exception:
        logger.exception("Calendar sync failed")
    return 0


def frame_for(session: Session, user_id: uuid.UUID, start: date, end: date) -> pd.DataFrame:
    """A person's daily calendar counts for [start, end): Google Calendar when they connected it,
    otherwise the days they approved from a harness. Never the two mixed."""
    frame = load_daily(session, user_id, SOURCE, start, end)
    return frame if not frame.empty else load_daily(session, user_id, HARNESS_SOURCE, start, end)
