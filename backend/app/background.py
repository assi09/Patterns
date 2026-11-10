"""Work the API does on its own while it runs: one thread, started and stopped with the app.

- every minute: send due reminders (`app.reminders.loop.run_once`);
- every 15 minutes: start a sync for each connected person whose last attempt is over
  `SYNC_EVERY` old, so data stays fresh when nobody opens the app; then check everyone for smart
  alarms and send what may go now (`app.alarms.run.run_all`). A sync started here finishes on its
  own thread; the next pass picks up what it brought. Then memory is kept up: idle chats become
  episodes and what has outlived its lifetime goes (`app.db.memory.maintain_all`).

Two copies of the API overlapping during a deploy are safe: reminder sends are claimed by a unique
key, alarms by their cooldown, and a person's sync runs once at a time. Logs carry counts only.
"""

import logging
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.alarms.run import run_all
from app.config import settings
from app.db.memory import maintain_all
from app.db.models import GoogleConnection, SyncRun
from app.db.session import session_scope
from app.reminders.loop import _mailer, run_once
from app.teams.alerts import run_due as run_team_alerts

logger = logging.getLogger(__name__)

TICK_S = 60
ALARM_TICKS = 15  # alarms and background syncs every 15 minutes
SYNC_EVERY = timedelta(hours=3)


def start_due_syncs(now: datetime) -> int:
    """Starts a sync for each connected person whose last attempt is older than `SYNC_EVERY`."""
    from app.api import google  # the API's Google wiring and its one-sync-per-person registry
    from app.api.errors import ApiError
    from app.sync import connections

    try:
        parts = google.get_google()
    except ApiError:
        return 0  # Google is not set up on this server
    started = 0
    with session_scope() as db:
        people = list(
            db.scalars(select(GoogleConnection.user_id).where(GoogleConnection.status == "active"))
        )
        last = dict(
            db.execute(
                select(SyncRun.user_id, func.max(SyncRun.started_at))
                .where(SyncRun.source == connections.SOURCE)
                .group_by(SyncRun.user_id)
            ).all()
        )
    for user_id in people:
        attempted = last.get(user_id)
        if attempted is not None and attempted.tzinfo is None:
            attempted = attempted.replace(tzinfo=UTC)
        if attempted is not None and now - attempted < SYNC_EVERY:
            continue
        work = lambda uid=user_id: connections.sync(  # noqa: E731
            session_scope, parts.box, uid, parts.health_for, now.date()
        )
        started += google.syncs.start(user_id, work)
    return started


def _explainers():
    """The model and the advice guard for alarm explanations; none when not set up or turned off."""
    if not settings.alarm_explanations:
        return None, None
    from app.agent.ask import default_guard
    from app.agent.llm import LLMError, OpenAILLM

    try:
        return OpenAILLM.from_settings(settings), default_guard(settings)
    except LLMError:
        return None, None


class Background:
    def __init__(self, tick_s: float = TICK_S):
        self.tick_s = tick_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="background", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        tick = 0
        while not self._stop.wait(self.tick_s):
            run_once()
            tick += 1
            if tick % ALARM_TICKS == 1:  # the first pass a minute after start, then every 15
                self._alarms()
                self._memory()

    @staticmethod
    def _memory() -> None:
        try:
            counts = maintain_all(session_scope, datetime.now(UTC))
        except Exception:
            logger.exception("The memory pass failed")
            return
        if any(counts.values()):
            logger.info("Memory kept up: %s", counts)

    @staticmethod
    def _alarms() -> None:
        now = datetime.now(UTC)
        try:
            synced = start_due_syncs(now)
            llm, guard = _explainers()
            counts = run_all(session_scope, now, _mailer(), settings.app_url, llm, guard)
        except Exception:
            logger.exception("The alarm pass failed")
            return
        if synced or counts:
            logger.info("Background syncs started: %d; alarms: %s", synced, dict(counts))
        try:
            team_counts = run_team_alerts(session_scope, now, _mailer(), settings.app_url)
        except Exception:
            logger.exception("The team alert pass failed")
            return
        if team_counts:
            logger.info("Team alerts: %s", dict(team_counts))
