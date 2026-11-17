"""`GET /metrics` in Prometheus' text format, for Grafana Cloud or a local Prometheus to scrape.

Two kinds of numbers. Requests are counted as they happen, by route pattern (`/days/{day}`, never
a real date or id) and status, with their durations. Everything about the agent and the pilot is
read from the database at scrape time, so it survives redeploys: answers by outcome and question
type, answer latency, verifier rejections, tool errors, thumbs, every dollar spent against the
caps, Google syncs, accounts and the daily questions. No label ever holds a person, an email or
anything they wrote.

The endpoint exists only when `FA_METRICS_TOKEN` is set, and answers only with that token as a
bearer token, so the numbers are not public.
"""

import hmac
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, Request, Response
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import func, select

from app.config import settings
from app.db.models import (
    AnswerTrace,
    ChatMessage,
    CheckIn,
    GoogleConnection,
    Pulse,
    Spend,
    SyncRun,
    User,
)
from app.db.session import session_scope

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
WINDOW = timedelta(hours=24)  # the period the latency quantiles describe
CACHE_SECONDS = 30  # one database read serves scrapes this close together

registry = CollectorRegistry()
REQUESTS = Counter(
    "patterns_http_requests",
    "API requests by method, route pattern and status.",
    ["method", "route", "status"],
    registry=registry,
)
DURATION = Histogram(
    "patterns_http_request_seconds",
    "API request duration by route pattern.",
    ["method", "route"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
    registry=registry,
)


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))] if ordered else 0.0


def _families(db, now: datetime) -> list:
    """Every database-backed metric, from aggregate queries only."""
    answers = CounterMetricFamily(
        "patterns_answers",
        "Agent answers by outcome and question type.",
        labels=["outcome", "type"],
    )
    for outcome, kind, count in db.execute(
        select(AnswerTrace.outcome, AnswerTrace.question_type, func.count()).group_by(
            AnswerTrace.outcome, AnswerTrace.question_type
        )
    ):
        answers.add_metric([outcome, kind or "unknown"], count)

    totals = db.execute(
        select(
            func.coalesce(func.sum(AnswerTrace.rejected_claims), 0),
            func.count().filter(AnswerTrace.tool_errors > 0),
            func.count().filter(AnswerTrace.repair_rounds > 0),
            func.coalesce(func.sum(AnswerTrace.model_calls), 0),
            func.coalesce(func.sum(AnswerTrace.tool_calls), 0),
        )
    ).one()
    simple = [
        ("patterns_rejected_claims", "Claims the verifier stopped.", totals[0]),
        ("patterns_answers_with_tool_errors", "Answers in which a tool failed.", totals[1]),
        ("patterns_answers_with_repairs", "Answers the agent had to repair.", totals[2]),
        ("patterns_model_calls", "Model calls made for answers.", totals[3]),
        ("patterns_tool_calls", "Tool calls made for answers.", totals[4]),
    ]
    families = [answers]
    for name, text, value in simple:
        family = CounterMetricFamily(name, text)
        family.add_metric([], value)
        families.append(family)

    recent = [
        ms / 1000
        for (ms,) in db.execute(
            select(AnswerTrace.latency_ms).where(AnswerTrace.created_at >= now - WINDOW)
        )
    ]
    latency = GaugeMetricFamily(
        "patterns_answer_latency_seconds",
        "Answer time over the last 24 hours, by quantile.",
        labels=["quantile"],
    )
    for q in (0.5, 0.9, 0.99):
        latency.add_metric([str(q)], _quantile(recent, q))
    recent_count = GaugeMetricFamily("patterns_answers_last_24h", "Answers in the last 24 hours.")
    recent_count.add_metric([], len(recent))
    families += [latency, recent_count]

    thumbs = CounterMetricFamily("patterns_thumbs", "Thumbs on answers.", labels=["rating"])
    for rating, count in db.execute(
        select(ChatMessage.rating, func.count())
        .where(ChatMessage.rating.is_not(None))
        .group_by(ChatMessage.rating)
    ):
        thumbs.add_metric([rating], count)
    families.append(thumbs)

    spend = CounterMetricFamily(
        "patterns_llm_spend_usd", "Model spending by kind.", labels=["kind"]
    )
    for kind, usd in db.execute(select(Spend.kind, func.sum(Spend.cost_usd)).group_by(Spend.kind)):
        spend.add_metric([kind], float(usd or 0))
    today = datetime(now.year, now.month, now.day, tzinfo=UTC)
    per_person = [
        float(v or 0)
        for (v,) in db.execute(
            select(func.sum(Spend.cost_usd)).where(Spend.at >= today).group_by(Spend.user_id)
        )
    ]
    caps = GaugeMetricFamily("patterns_spend_cap_usd", "The spending caps.", labels=["cap"])
    caps.add_metric(["daily_total"], settings.chat_daily_cap_total_usd)
    caps.add_metric(["daily_person"], settings.chat_daily_cap_per_user_usd)
    caps.add_metric(["all_time"], settings.llm_spend_cap_usd)
    spent_today = GaugeMetricFamily(
        "patterns_spend_today_usd",
        "Spent today (UTC): everyone, and the heaviest person.",
        labels=["who"],
    )
    spent_today.add_metric(["everyone"], sum(per_person))
    spent_today.add_metric(["heaviest_person"], max(per_person, default=0.0))
    at_cap = GaugeMetricFamily(
        "patterns_people_at_daily_cap", "People who reached their daily cap today."
    )
    at_cap.add_metric([], sum(1 for v in per_person if v >= settings.chat_daily_cap_per_user_usd))
    families += [spend, caps, spent_today, at_cap]

    syncs = CounterMetricFamily("patterns_sync_runs", "Google syncs by status.", labels=["status"])
    for status, count in db.execute(select(SyncRun.status, func.count()).group_by(SyncRun.status)):
        syncs.add_metric([status], count)
    durations = [
        (finished - started).total_seconds()
        for started, finished in db.execute(
            select(SyncRun.started_at, SyncRun.finished_at).where(
                SyncRun.started_at >= now - WINDOW,
                SyncRun.status == "succeeded",
                SyncRun.finished_at.is_not(None),
            )
        )
    ]
    sync_time = GaugeMetricFamily(
        "patterns_sync_seconds", "Successful sync time over the last 24 hours.", labels=["quantile"]
    )
    for q in (0.5, 0.9):
        sync_time.add_metric([str(q)], _quantile(durations, q))
    families += [syncs, sync_time]

    for name, text, column in (
        ("patterns_accounts", "Accounts by status.", User.status),
        ("patterns_google_connections", "Google connections by status.", GoogleConnection.status),
    ):
        family = GaugeMetricFamily(name, text, labels=["status"])
        for status, count in db.execute(select(column, func.count()).group_by(column)):
            family.add_metric([status], count)
        families.append(family)

    for name, text, model in (
        ("patterns_check_ins", "Morning check-ins answered.", CheckIn),
        ("patterns_evening_answers", "Evening team questions answered.", Pulse),
    ):
        family = CounterMetricFamily(name, text)
        family.add_metric([], db.scalar(select(func.count()).select_from(model)) or 0)
        families.append(family)
    return families


class DatabaseCollector(Collector):
    """Reads the database once per scrape (or reuses a read from the last 30 seconds)."""

    def __init__(self, sessions=session_scope) -> None:
        self.sessions = sessions
        self._last: tuple[float, list] | None = None

    def collect(self) -> Iterator:
        if self._last and time.monotonic() - self._last[0] < CACHE_SECONDS:
            yield from self._last[1]
            return
        up = GaugeMetricFamily("patterns_database_up", "Whether the database could be read.")
        try:
            with self.sessions() as db:
                families = _families(db, datetime.now(UTC))
            up.add_metric([], 1)
        except Exception:  # a scrape must not fail because the database is down: report it
            families = []
            up.add_metric([], 0)
        families.append(up)
        self._last = (time.monotonic(), families)
        yield from families


_collector: DatabaseCollector | None = None


def _route(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"  # a pattern, never the real path


def install(app: FastAPI, sessions=session_scope) -> None:
    """Counts every request, and serves /metrics when a token is configured."""
    global _collector
    if _collector is not None:  # the app is built again (tests do): replace, never duplicate
        registry.unregister(_collector)
    _collector = DatabaseCollector(sessions)
    registry.register(_collector)

    @app.middleware("http")
    async def count_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        route = _route(request)
        if route != "/metrics":
            REQUESTS.labels(request.method, route, str(response.status_code)).inc()
            DURATION.labels(request.method, route).observe(time.perf_counter() - started)
        return response

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> Response:
        token = settings.metrics_token.get_secret_value() if settings.metrics_token else ""
        given = request.headers.get("authorization", "")
        if not token:
            return Response(status_code=404)
        if not hmac.compare_digest(given, f"Bearer {token}"):
            return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        return Response(generate_latest(registry), media_type=CONTENT_TYPE)
