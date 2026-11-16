"""One day's numbers next to the person's usual, and a metric's recent days, for Today.

The day's workouts and its steps hour by hour are not in the daily table: they are read from the
person's Google Health when asked, and kept for a few minutes.
"""

import logging
import threading
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

import pandas as pd
from fastapi import APIRouter, Depends, Query
from google.auth.exceptions import GoogleAuthError

from app.analysis import day as days
from app.analysis.tools import LOW_WEAR_MINUTES
from app.api import schemas
from app.api.auth import Db, Now, approved_user
from app.api.errors import ApiError
from app.api.store import LoadedData, get_data
from app.config import settings
from app.db import memory
from app.db.models import User
from app.sync.client import HealthClient
from app.sync.connections import credentials_for
from app.sync.google_auth import SyncError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["days"])
Data = Annotated[LoadedData, Depends(get_data)]
Person = Annotated[User, Depends(approved_user)]
LIVE_SECONDS = 300  # how long a day's workouts and hourly steps are kept before reading again
ZONES = {
    "lightTime": "light",
    "moderateTime": "moderate",
    "vigorousTime": "vigorous",
    "peakTime": "peak",
}


def _usual(usual: days.Usual | None) -> schemas.Usual | None:
    return schemas.Usual(**vars(usual)) if usual else None


def _range(data: LoadedData) -> tuple[date, date]:
    index = data.daily.frame.index
    return index.min().date(), index.max().date()


@router.get("/days/latest", response_model=schemas.Day)
def get_latest_day(data: Data, clock: Now) -> schemas.Day:
    """The newest day with data: what Today opens on."""
    return get_day(_range(data)[1], data, clock)


@router.get("/days/{day}", response_model=schemas.Day)
def get_day(day: date, data: Data, clock: Now) -> schemas.Day:
    first, last = _range(data)
    if not first <= day <= last:
        raise ApiError(404, "no_data", "There is no data for that day.")
    frame = data.daily.frame
    wear = frame["wear_minutes"].get(pd.Timestamp(day)) if "wear_minutes" in frame else None
    return schemas.Day(
        date=day,
        partial=day == clock.astimezone(ZoneInfo(settings.timezone)).date(),
        low_wear=bool(pd.notna(wear) and wear < LOW_WEAR_MINUTES),
        first=first,
        last=last,
        metrics=[
            schemas.DayMetric(
                metric=m.metric, value=m.value, usual=_usual(m.usual), recent=m.recent
            )
            for m in days.day_summary(frame, day)
        ],
        recovery=_recovery(frame, day),
        strain=_strain(frame, day),
        stress=_stress(frame, day),
    )


def _recovery(frame: pd.DataFrame, day: date) -> schemas.Recovery | None:
    parts = days.recovery_parts(frame, day)
    score = days.recovery_score(parts)
    return schemas.Recovery(score=score, parts=parts) if score is not None else None


def _strain(frame: pd.DataFrame, day: date) -> schemas.Strain | None:
    found = days.strain_days(frame).get(pd.Timestamp(day))
    return schemas.Strain(**vars(found)) if found else None


def _stress(frame: pd.DataFrame, day: date) -> schemas.Stress | None:
    parts = days.stress_parts(frame, day)
    score = days.stress_score(parts)
    return schemas.Stress(score=score, parts=parts) if score is not None else None


# Read live from Google Health


_live: dict[tuple, tuple[float, object]] = {}
_live_lock = threading.Lock()


def _cached(key: tuple, read):
    with _live_lock:
        hit = _live.get(key)
    if hit and time.monotonic() - hit[0] < LIVE_SECONDS:
        return hit[1]
    value = read()
    with _live_lock:
        _live[key] = (time.monotonic(), value)
    return value


def _health(db, user_id: uuid.UUID) -> HealthClient | None:
    """A client for the person's Google Health, or None without a working connection."""
    from app.api.google import get_google  # the Google routes import the chat, which imports this

    try:
        token = credentials_for(db, get_google().box, user_id).token
    except (ApiError, SyncError, GoogleAuthError):
        return None
    return HealthClient(lambda: token, max_retries=1)


def _local_day(day: date) -> tuple[datetime, datetime]:
    zone = ZoneInfo(settings.timezone)
    start = datetime.combine(day, datetime.min.time(), zone)
    return start, start + timedelta(days=1)


def _number(value: object) -> float | None:
    try:
        return float(str(value).removesuffix("s")) if value is not None else None
    except (TypeError, ValueError):
        return None


def _workout(point: dict) -> schemas.Workout | None:
    exercise = point.get("exercise", {})
    interval = exercise.get("interval", {})
    summary = exercise.get("metricsSummary", {})
    if not interval.get("startTime") or not interval.get("endTime"):
        return None
    millimetres = _number(summary.get("distanceMillimeters"))
    zones = summary.get("heartRateZoneDurations") or {}
    exercise_type = exercise.get("exerciseType") or "OTHER"
    return schemas.Workout(
        id=str(point.get("name", "")).rsplit("/", 1)[-1] or interval["startTime"],
        exercise_type=exercise_type,
        name=exercise.get("displayName") or exercise_type.replace("_", " ").capitalize(),
        start=interval["startTime"],
        end=interval["endTime"],
        active_seconds=round(s) if (s := _number(exercise.get("activeDuration"))) else None,
        steps=round(n) if (n := _number(summary.get("steps"))) else None,
        distance_km=round(millimetres / 1_000_000, 2) if millimetres else None,
        calories_kcal=_number(summary.get("caloriesKcal")),
        average_heart_rate=round(n)
        if (n := _number(summary.get("averageHeartRateBeatsPerMinute")))
        else None,
        active_zone_minutes=round(n) if (n := _number(summary.get("activeZoneMinutes"))) else None,
        zone_seconds={ZONES[k]: _number(v) or 0 for k, v in zones.items() if k in ZONES} or None,
        source=(point.get("dataSource", {}).get("device") or {}).get("displayName"),
    )


@router.get("/days/{day}/workouts", response_model=schemas.DayWorkouts)
def get_workouts(day: date, db: Db, user: Person) -> schemas.DayWorkouts:
    """The workouts that started on this local day, as the tracker or an app recorded them."""
    health = _health(db, user.id)
    if health is None:
        return schemas.DayWorkouts(available=False, workouts=[])

    def read() -> list[schemas.Workout]:
        start, end = _local_day(day)
        field = "exercise.interval.civil_start_time"
        query = f'{field} >= "{start:%Y-%m-%dT%H:%M:%S}" AND {field} < "{end:%Y-%m-%dT%H:%M:%S}"'
        found = [_workout(p) for p in health.list_points("exercise", filter=query)]
        return sorted((w for w in found if w), key=lambda w: w.start)

    try:
        workouts = _cached((user.id, day, "workouts"), read)
    except SyncError:
        logger.warning("Could not read the day's workouts")
        return schemas.DayWorkouts(available=False, workouts=[])
    return schemas.DayWorkouts(available=True, workouts=workouts)


@router.get("/days/{day}/hourly", response_model=schemas.HourlySteps)
def get_hourly(day: date, db: Db, user: Person) -> schemas.HourlySteps:
    """The day's steps in each local hour."""
    health = _health(db, user.id)
    if health is None:
        return schemas.HourlySteps(available=False, steps=[])

    def read() -> list[int | None]:
        start, end = _local_day(day)
        hours: list[int | None] = [None] * 24
        for point in health.rollup_windows("steps", start, end, 3600):
            moment = datetime.fromisoformat(point["startTime"].replace("Z", "+00:00"))
            hour = int((moment - start).total_seconds() // 3600)
            count = _number(point.get("steps", {}).get("countSum"))
            if 0 <= hour < 24 and count is not None:
                hours[hour] = round(count)
        return hours

    try:
        steps = _cached((user.id, day, "hourly"), read)
    except SyncError:
        logger.warning("Could not read the day's hourly steps")
        return schemas.HourlySteps(available=False, steps=[])
    return schemas.HourlySteps(available=True, steps=steps)


STAGES = {"AWAKE": "awake", "LIGHT": "light", "DEEP": "deep", "REM": "rem", "ASLEEP": "asleep"}
STAGES |= {"RESTLESS": "restless"}


def _stage(entry: dict) -> schemas.SleepStage | None:
    stage = STAGES.get(str(entry.get("type", "")).upper())
    if not stage or not entry.get("startTime") or not entry.get("endTime"):
        return None
    return schemas.SleepStage(start=entry["startTime"], end=entry["endTime"], stage=stage)


@router.get("/days/{day}/sleep", response_model=schemas.NightStages)
def get_sleep(day: date, db: Db, user: Person) -> schemas.NightStages:
    """The night that ended on this local day, stage by stage: the main sleep, the longest if
    there are two, as the daily totals choose it. Read live, like the hourly steps."""
    health = _health(db, user.id)
    if health is None:
        return schemas.NightStages(available=False)

    def read() -> schemas.NightStages:
        start, end = _local_day(day)
        field = "sleep.interval.end_time"
        query = (
            f'{field} >= "{start.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}" AND '
            f'{field} < "{end.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}"'
        )
        nights = [
            p["sleep"]
            for p in health.list_points("sleep", filter=query, page_size=25)
            if p.get("sleep", {}).get("metadata", {}).get("mainSleep")
        ]
        if not nights:
            return schemas.NightStages(available=False)
        night = max(nights, key=lambda s: _number(s.get("summary", {}).get("minutesAsleep")) or 0)
        stages = sorted(
            (s for e in night.get("stages", []) if (s := _stage(e))), key=lambda s: s.start
        )
        interval = night.get("interval", {})
        return schemas.NightStages(
            available=bool(stages),
            start=interval.get("startTime"),
            end=interval.get("endTime"),
            staged=night.get("type") == "STAGES",
            stages=stages,
        )

    try:
        return _cached((user.id, day, "sleep"), read)
    except SyncError:
        logger.warning("Could not read the night's sleep stages")
        return schemas.NightStages(available=False)


# The morning check-in


@router.get("/checkins/{day}", response_model=schemas.CheckIn | None)
def get_checkin(day: date, db: Db, user: Person) -> schemas.CheckIn | None:
    found = memory.checkins(db, user.id, day, day)
    return schemas.CheckIn(day=day, rating=found[0].rating, tags=found[0].tags) if found else None


@router.put("/checkins/{day}", response_model=schemas.CheckIn)
def put_checkin(
    day: date, body: schemas.CheckIn, db: Db, user: Person, clock: Now
) -> schemas.CheckIn:
    """Sets or changes today's check-in: how the person feels, 1 to 5, and optional tags."""
    today = clock.astimezone(ZoneInfo(settings.timezone)).date()
    try:
        saved = memory.save_checkin(db, user.id, day, body.rating, body.tags, today=today)
    except memory.MemoryRejected as exc:
        raise ApiError(422, "invalid_checkin", str(exc)) from None
    return schemas.CheckIn(day=saved.day, rating=saved.rating, tags=saved.tags)


@router.get("/metrics/{metric}", response_model=schemas.MetricSeries)
def get_metric(
    metric: str,
    data: Data,
    end: date | None = None,
    span: Annotated[int, Query(alias="days", ge=7, le=366)] = 30,
) -> schemas.MetricSeries:
    frame = data.daily.frame
    if metric not in frame.columns and metric not in days.SCORES:  # computed, not stored
        raise ApiError(404, "unknown_metric", "There is no such metric.")
    first, last = _range(data)
    end = min(end or last, last)
    if end < first:
        raise ApiError(404, "no_data", "There is no data for that day.")
    return schemas.MetricSeries(
        metric=metric,
        points=[schemas.Point(date=d, value=v) for d, v in days.series(frame, metric, end, span)],
        usual=_usual(days.usual_before(frame, metric, end)),
    )
