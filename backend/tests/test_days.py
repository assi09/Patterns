import json
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.analysis.day import MIN_USUAL_DAYS, RECENT_DAYS, USUAL_DAYS, day_summary, series, usual
from app.api.auth import now
from app.api.main import create_app
from app.api.store import analyze, get_data
from app.ingest.takeout import DailyData
from app.sync.client import HealthClient
from app.synthetic import LowWear, generate

START = date(2026, 7, 1)
LOADED_AT = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def frame_of(values: dict[str, list[float]], start: date = START) -> pd.DataFrame:
    length = len(next(iter(values.values())))
    return pd.DataFrame(values, index=pd.date_range(start, periods=length))


def only(metrics):
    """The resting heart rate, the one input of these frames (the recovery score is added too)."""
    return next(m for m in metrics if m.metric == "resting_hr")


def test_usual_is_the_middle_half_of_the_days_before_and_skips_the_day_itself():
    # 28 days of 1..28, then the day itself far outside them.
    frame = frame_of({"resting_hr": [*range(1, 29), 500.0]})
    day = START + timedelta(days=28)
    metric = only(day_summary(frame, day))
    assert metric.value == 500
    assert metric.usual.median == 14.5 and metric.usual.days == USUAL_DAYS
    assert (metric.usual.low, metric.usual.high) == (7.75, 21.25)
    assert len(metric.recent) == RECENT_DAYS and metric.recent[-1] == 500


def test_only_the_28_days_before_count_and_gaps_stay_gaps():
    values = [1000.0] * 10 + [60.0] * 28 + [np.nan]
    frame = frame_of({"resting_hr": values})
    metric = only(day_summary(frame, START + timedelta(days=38)))
    assert metric.value is None and metric.usual.median == 60
    assert metric.recent[-1] is None


def test_too_few_days_give_no_usual_range():
    frame = frame_of({"resting_hr": [60.0] * (MIN_USUAL_DAYS - 1) + [61.0]})
    metric = only(day_summary(frame, START + timedelta(days=MIN_USUAL_DAYS - 1)))
    assert metric.usual is None
    assert usual(pd.Series([1.0] * MIN_USUAL_DAYS)) is not None


def test_low_wear_days_are_left_out_of_activity_but_the_day_keeps_its_value():
    steps = [10_000.0] * 28 + [500.0]
    wear = [900.0] * 20 + [100.0] * 8 + [100.0]  # the last 8 usual days barely worn
    frame = frame_of({"steps": steps, "wear_minutes": wear, "resting_hr": [60.0] * 29})
    metrics = {m.metric: m for m in day_summary(frame, START + timedelta(days=28))}
    assert metrics["steps"].value == 500  # shown as it is; the API flags the day
    assert metrics["steps"].usual.days == 20  # only the well-worn days
    assert metrics["steps"].recent[-1] is None  # the trend line skips a low-wear day
    assert metrics["resting_hr"].usual.days == 28  # heart rate does not depend on wear


def test_series_covers_the_span_ending_on_the_day():
    frame = frame_of({"resting_hr": [60.0, np.nan, 62.0]})
    points = series(frame, "resting_hr", START + timedelta(days=2), 7)
    assert len(points) == 7 and points[-1] == (START + timedelta(days=2), 62.0)
    assert points[-2][1] is None and points[0][1] is None  # before the data: gaps


def client_for(frame: pd.DataFrame, today: datetime | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_data] = lambda: analyze(DailyData(frame=frame), LOADED_AT)
    if today:
        app.dependency_overrides[now] = lambda: today
    return TestClient(app)


@pytest.fixture
def synthetic() -> pd.DataFrame:
    effects = (LowWear(START + timedelta(days=40), START + timedelta(days=40)),)
    return generate(START, 45, effects).frame


def test_day_endpoint_uses_the_app_contract(synthetic):
    last = START + timedelta(days=44)
    client = client_for(synthetic, today=datetime(2026, 8, 14, 9, tzinfo=UTC))
    body = client.get(f"/days/{last.isoformat()}").json()
    assert set(body) == {
        "date",
        "partial",
        "lowWear",
        "first",
        "last",
        "metrics",
        "recovery",
        "strain",
        "stress",
    }
    assert set(body["recovery"]) == {"score", "parts"} and 0 <= body["recovery"]["score"] <= 100
    assert "recovery_score" in {m["metric"] for m in body["metrics"]}
    assert body["partial"] is True and body["lowWear"] is False  # Aug 14 is today, Beirut
    assert (body["first"], body["last"]) == (START.isoformat(), last.isoformat())
    steps = next(m for m in body["metrics"] if m["metric"] == "steps")
    assert set(steps) == {"metric", "value", "usual", "recent"}
    assert set(steps["usual"]) == {"median", "low", "high", "days"}
    assert len(steps["recent"]) == RECENT_DAYS
    assert client.get("/days/latest").json()["date"] == last.isoformat()
    worn_little = client.get(f"/days/{(START + timedelta(days=40)).isoformat()}").json()
    assert worn_little["lowWear"] is True and worn_little["partial"] is False


def test_days_outside_the_data_and_unknown_metrics_are_404(synthetic):
    client = client_for(synthetic)
    assert client.get("/days/2026-01-01").json()["error"]["code"] == "no_data"
    assert client.get("/days/not-a-date").status_code == 422
    assert client.get("/metrics/made_up").json()["error"]["code"] == "unknown_metric"


def test_metric_endpoint_gives_the_span_and_the_usual_range(synthetic):
    client = client_for(synthetic)
    body = client.get("/metrics/resting_hr").json()
    assert len(body["points"]) == 30 and body["points"][-1]["date"] == "2026-08-14"
    assert body["usual"]["days"] == USUAL_DAYS
    shorter = client.get("/metrics/resting_hr", params={"days": 7, "end": "2026-07-20"}).json()
    assert [p["date"] for p in shorter["points"]][-1] == "2026-07-20" and len(
        shorter["points"]
    ) == 7
    # A future end is clamped to the last day; spans are bounded.
    assert (
        client.get("/metrics/resting_hr", params={"end": "2030-01-01"}).json()["points"][-1]["date"]
        == "2026-08-14"
    )
    assert client.get("/metrics/resting_hr", params={"days": 2}).status_code == 422
    recovery = client.get("/metrics/recovery_score").json()
    assert len(recovery["points"]) == 30 and recovery["points"][-1]["value"] is not None


def test_days_need_an_approved_sign_in(synthetic):
    app = create_app()
    assert TestClient(app).get("/days/2026-07-10").status_code == 401


def test_recovery_scores_where_last_night_sits_among_the_weeks_before():
    from app.analysis.day import recovery_parts, recovery_score, with_scores

    days = 30
    frame = frame_of(
        {
            "hrv_ms": [50.0] * (days - 1) + [70.0],  # above every usual day: 100
            "resting_hr": [60.0] * (days - 1) + [60.0],  # equal to all: half, so 50
            "sleep_minutes": [float(400 + i) for i in range(days - 1)] + [380.0],  # below all: 0
        }
    )
    last = START + timedelta(days=days - 1)
    assert recovery_parts(frame, last) == {
        "hrv_ms": 100.0,
        "resting_hr": 50.0,
        "sleep_minutes": 0.0,
    }
    assert recovery_score(recovery_parts(frame, last)) == 50
    assert recovery_score({"hrv_ms": 80.0}) is None  # one input is not enough
    scores = with_scores(frame)["recovery_score"]
    assert scores.iloc[:MIN_USUAL_DAYS].isna().all() and scores.iloc[-1] == 50
    # A higher resting heart rate counts down.
    higher = frame.assign(resting_hr=[60.0] * (days - 1) + [70.0])
    assert recovery_parts(higher, last)["resting_hr"] == 0.0


# Read live from Google Health, and the check-in


def fake_google(handler) -> HealthClient:
    import httpx2

    http = httpx2.Client(transport=httpx2.MockTransport(handler))
    return HealthClient(lambda: "token", http=http, max_retries=0)


def signed_in_client(tmp_path, frame, today=None):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, select

    from app.api import auth
    from app.db.models import User
    from app.db.session import session_scope

    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    client = client_for(frame, today)

    def db():
        with session_scope(engine) as session:
            yield session

    client.app.dependency_overrides[auth.get_db] = db
    token = client.post(
        "/auth/signup", json={"email": "p@example.com", "password": "correct horse battery"}
    ).json()["token"]
    with session_scope(engine) as session:
        session.scalar(select(User)).status = "approved"
    return client, {"Authorization": f"Bearer {token}"}


def test_the_days_workouts_come_from_google_with_their_summary(tmp_path, synthetic, monkeypatch):
    import httpx2

    from app.api import days as api

    asked = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(request)
        exercise = {
            "name": "users/1/dataTypes/exercise/dataPoints/abc",
            "dataSource": {"device": {"displayName": "Fitbit Air"}},
            "exercise": {
                "exerciseType": "TENNIS",
                "displayName": "Tennis",
                "interval": {
                    "startTime": "2026-08-10T15:00:00Z",
                    "endTime": "2026-08-10T16:00:00Z",
                },
                "activeDuration": "3500s",
                "metricsSummary": {
                    "steps": "2400",
                    "distanceMillimeters": 1800000,
                    "caloriesKcal": 410,
                    "averageHeartRateBeatsPerMinute": "131",
                    "activeZoneMinutes": "38",
                    "heartRateZoneDurations": {"lightTime": "600s", "moderateTime": "1200s"},
                },
            },
        }
        return httpx2.Response(200, json={"dataPoints": [exercise]})

    monkeypatch.setattr(api, "_live", {})
    monkeypatch.setattr(api, "_health", lambda db, user_id: fake_google(handler))
    client, headers = signed_in_client(tmp_path, synthetic)
    body = client.get("/days/2026-08-10/workouts", headers=headers).json()
    assert body["available"] is True
    (workout,) = body["workouts"]
    assert workout["exerciseType"] == "TENNIS" and workout["id"] == "abc"
    assert workout["steps"] == 2400 and workout["distanceKm"] == 1.8
    assert workout["averageHeartRate"] == 131 and workout["activeZoneMinutes"] == 38
    assert workout["zoneSeconds"] == {"light": 600, "moderate": 1200}
    assert workout["activeSeconds"] == 3500 and workout["source"] == "Fitbit Air"
    assert "civil_start_time" in asked[0].url.params["filter"]
    client.get("/days/2026-08-10/workouts", headers=headers)
    assert len(asked) == 1  # kept for a few minutes


def test_steps_by_hour_and_no_google(tmp_path, synthetic, monkeypatch):
    import httpx2

    from app.api import days as api

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        assert body["windowSize"] == "3600s"
        start = datetime.fromisoformat(body["range"]["startTime"].replace("Z", "+00:00"))
        points = [
            {
                "startTime": (start + timedelta(hours=h)).isoformat(),
                "steps": {"countSum": str(h * 10)},
            }
            for h in (7, 8)
        ]
        return httpx2.Response(200, json={"rollupDataPoints": points})

    monkeypatch.setattr(api, "_live", {})
    monkeypatch.setattr(api, "_health", lambda db, user_id: fake_google(handler))
    client, headers = signed_in_client(tmp_path, synthetic)
    steps = client.get("/days/2026-08-10/hourly", headers=headers).json()["steps"]
    assert len(steps) == 24 and steps[7] == 70 and steps[8] == 80 and steps[0] is None
    monkeypatch.setattr(api, "_health", lambda db, user_id: None)
    assert client.get("/days/2026-08-11/hourly", headers=headers).json() == {
        "available": False,
        "steps": [],
    }
    assert client.get("/days/2026-08-11/workouts", headers=headers).json()["available"] is False


def test_only_todays_check_in_can_be_set(tmp_path, synthetic):
    today = datetime(2026, 8, 14, 6, tzinfo=UTC)
    client, headers = signed_in_client(tmp_path, synthetic, today)
    assert client.get("/checkins/2026-08-14", headers=headers).json() is None
    saved = client.put(
        "/checkins/2026-08-14",
        json={"day": "2026-08-14", "rating": 4, "tags": ["stress"]},
        headers=headers,
    )
    assert saved.json() == {"day": "2026-08-14", "rating": 4, "tags": ["stress"]}
    assert client.get("/checkins/2026-08-14", headers=headers).json()["rating"] == 4
    past = client.put(
        "/checkins/2026-08-10", json={"day": "2026-08-10", "rating": 3}, headers=headers
    )
    assert past.json()["error"]["code"] == "invalid_checkin"
    bad = client.put(
        "/checkins/2026-08-14", json={"day": "2026-08-14", "rating": 9}, headers=headers
    )
    assert bad.status_code == 422
    unknown = client.put(
        "/checkins/2026-08-14",
        json={"day": "2026-08-14", "rating": 3, "tags": ["nope"]},
        headers=headers,
    )
    assert unknown.json()["error"]["code"] == "invalid_checkin"


def test_the_nights_stages_from_google(tmp_path, synthetic, monkeypatch):
    import httpx2

    from app.api import days as api

    asked = []

    def stage(start: str, end: str, kind: str) -> dict:
        return {"startTime": start, "endTime": end, "type": kind}

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(request)
        nap = {
            "sleep": {
                "type": "STAGES",
                "interval": {
                    "startTime": "2026-08-10T13:00:00Z",
                    "endTime": "2026-08-10T13:40:00Z",
                },
                "summary": {"minutesAsleep": "35"},
                "stages": [stage("2026-08-10T13:00:00Z", "2026-08-10T13:40:00Z", "LIGHT")],
            }
        }
        night = {
            "sleep": {
                "type": "STAGES",
                "metadata": {"mainSleep": True},
                "interval": {
                    "startTime": "2026-08-09T23:30:00Z",
                    "endTime": "2026-08-10T07:00:00Z",
                },
                "summary": {"minutesAsleep": "420"},
                "stages": [  # out of order, as a list may come
                    stage("2026-08-10T01:00:00Z", "2026-08-10T02:00:00Z", "DEEP"),
                    stage("2026-08-09T23:30:00Z", "2026-08-10T01:00:00Z", "LIGHT"),
                    stage("2026-08-10T02:00:00Z", "2026-08-10T06:50:00Z", "REM"),
                    stage("2026-08-10T06:50:00Z", "2026-08-10T07:00:00Z", "AWAKE"),
                    stage("2026-08-10T03:00:00Z", "2026-08-10T03:05:00Z", "UNKNOWN_KIND"),
                ],
            }
        }
        return httpx2.Response(200, json={"dataPoints": [nap, night]})

    monkeypatch.setattr(api, "_live", {})
    monkeypatch.setattr(api, "_health", lambda db, user_id: fake_google(handler))
    client, headers = signed_in_client(tmp_path, synthetic)
    body = client.get("/days/2026-08-10/sleep", headers=headers).json()
    assert body["available"] is True and body["staged"] is True
    assert [s["stage"] for s in body["stages"]] == ["light", "deep", "rem", "awake"]
    assert body["start"].startswith("2026-08-09T23:30") and body["end"].startswith("2026-08-10T07")
    assert "sleep.interval.end_time" in asked[0].url.params["filter"]
    client.get("/days/2026-08-10/sleep", headers=headers)
    assert len(asked) == 1  # kept for a few minutes


def test_no_night_a_classic_night_and_no_google(tmp_path, synthetic, monkeypatch):
    import httpx2

    from app.api import days as api

    points: list[dict] = []
    monkeypatch.setattr(api, "_live", {})
    monkeypatch.setattr(
        api,
        "_health",
        lambda db, user_id: fake_google(
            lambda request: httpx2.Response(200, json={"dataPoints": points})
        ),
    )
    client, headers = signed_in_client(tmp_path, synthetic)
    assert client.get("/days/2026-08-10/sleep", headers=headers).json()["available"] is False
    points.append(
        {
            "sleep": {
                "type": "CLASSIC",
                "metadata": {"mainSleep": True},
                "interval": {
                    "startTime": "2026-08-10T23:00:00Z",
                    "endTime": "2026-08-11T06:00:00Z",
                },
                "summary": {"minutesAsleep": "400"},
                "stages": [
                    {
                        "startTime": "2026-08-10T23:00:00Z",
                        "endTime": "2026-08-11T06:00:00Z",
                        "type": "ASLEEP",
                    }
                ],
            }
        }
    )
    body = client.get("/days/2026-08-11/sleep", headers=headers).json()
    assert body["available"] is True and body["staged"] is False
    assert body["stages"][0]["stage"] == "asleep"
    monkeypatch.setattr(api, "_health", lambda db, user_id: None)
    assert client.get("/days/2026-08-12/sleep", headers=headers).json()["available"] is False
