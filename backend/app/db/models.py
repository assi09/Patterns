"""Database tables. Only what is settled lives here; later features add tables by migration.

Every table that holds a person's data has a `user_id`, and every query filters on it.
Types are portable so the tests can run on SQLite while development and deployment use Postgres.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.agent.facts import FACT_KINDS

# Where a day's numbers came from. A history is read from one source only: the legacy export's
# sleep comes from an older algorithm than the API's, so mixing them would fake a change.
SOURCES = ("google_health", "takeout")
SYNC_STATUSES = ("running", "succeeded", "failed")
CHAT_ROLES = ("user", "assistant")
# A sign-up waits for the owner's approval: the Google Health app is in Testing mode, so each
# person must also be added as a test user by hand before they can connect their data.
USER_STATUSES = ("pending", "approved", "rejected")
# A supervisor can create teams and read their weekly team reports (docs/teams.md); the owner
# grants the role. Everyone else is a member, who may join teams.
USER_ROLES = ("member", "supervisor")
TEAM_EVENTS = (
    "created",
    "code_rotated",
    "joined",
    "left",
    "levels_shared",
    "levels_unshared",
    "levels_viewed",  # the supervisor opened a report's named levels
)
REMINDER_STATUSES = ("proposed", "active", "paused", "declined", "cancelled", "done")
REMINDER_SOURCES = ("person", "agent")
DELIVERY_CHANNELS = ("email", "in_app")
# skipped_late: the server was down at the time, and a reminder hours late helps nobody.
DELIVERY_STATUSES = (
    "sent",
    "failed",
    "skipped_quiet",
    "skipped_cap",
    "skipped_late",
    "skipped_off",
)
ALARM_STATUSES = ("pending", "sent", "suppressed", "expired")
TEAM_REPORT_STATUSES = ("ready", "withheld")  # withheld: fewer active members than the minimum


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in USER_STATUSES)})", name="ck_users_status"
        ),
        CheckConstraint(
            f"role IN ({', '.join(repr(r) for r in USER_ROLES)})", name="ck_users_role"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # scrypt hash; None for the local owner created by `python -m app.sync pull`.
    password_hash: Mapped[str | None] = mapped_column(String(256), default=None)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    role: Mapped[str] = mapped_column(String(16), default="member", server_default="member")
    # The device's IANA time zone, sent by the app; reminders are due in it. None: FA_TIMEZONE.
    timezone: Mapped[str | None] = mapped_column(String(64), default=None)


class AuthSession(Base):
    """A signed-in device. Only the token's hash is stored: a database leak signs no one in."""

    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GoogleConnection(Base):
    """A user's Google Health sign-in. The token is stored encrypted, never in plain text."""

    __tablename__ = "google_connections"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    encrypted_token: Mapped[bytes] = mapped_column(LargeBinary)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    # "active", or "reconnect_needed" once Google rejects the refresh token (7 days in Testing).
    status: Mapped[str] = mapped_column(String(32), default="active")
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class DailyMetric(Base):
    """One metric on one local day, for one user and source (the columns in docs/metrics.md)."""

    __tablename__ = "daily_metrics"
    __table_args__ = (
        CheckConstraint(f"source IN {SOURCES}", name="ck_daily_metrics_source"),
        Index("ix_daily_metrics_user_metric_day", "user_id", "metric", "day"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    metric: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[float] = mapped_column(Float)


class SyncRun(Base):
    """One attempt to pull data, kept for the Data tab and for operational metrics."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint(f"source IN {SOURCES}", name="ck_sync_runs_source"),
        CheckConstraint(f"status IN {SYNC_STATUSES}", name="ck_sync_runs_status"),
        Index("ix_sync_runs_user_started", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="running")
    range_start: Mapped[date] = mapped_column(Date)
    range_end: Mapped[date] = mapped_column(Date)  # exclusive
    days_written: Mapped[int | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)  # safe to show the user
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Conversation(Base):
    """One of a person's chats. Long-term memory is the person's; its summary stays in the chat."""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(120), default="New chat")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # first
    # This chat's short-term memory (`app.agent.summary`), and the last answer it reaches.
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    summary_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ChatMessage(Base):
    """One turn of a person's conversation with the agent (one thread per person).

    Assistant turns keep their verified claims, so older turns can be condensed to what was asked
    and what was verified, and the ids of the evidence they cite, so a follow-up can cite it too.
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(f"role IN {CHAT_ROLES}", name="ck_chat_messages_role"),
        Index("ix_chat_messages_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))
    # Null only for messages from before conversations existed, until the migration files them.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE", name="fk_chat_messages_conversation"),
        index=True,
        default=None,
    )
    action_ids: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    # Reminders the agent prepared in this answer, each waiting for the person's tap on its card.
    reminder_ids: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    # An unfinished clarification, usable only by the next reply within 24 hours.
    pending_log_expert: Mapped[str | None] = mapped_column(String(16), default=None)
    text: Mapped[str] = mapped_column(Text)
    # What a user turn asked about: {"kind": "finding", "id": ...} or {"kind": "metric", ...}.
    attachment: Mapped[dict | None] = mapped_column(JSON, default=None)
    # Assistant turns only.
    claims: Mapped[list[dict]] = mapped_column(JSON, default=list)  # verified claims
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    answered_by: Mapped[str | None] = mapped_column(String(32), default=None)  # expert, general
    routed: Mapped[bool | None] = mapped_column(Boolean, default=None)
    consulted: Mapped[list[str]] = mapped_column(JSON, default=list)
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    run_id: Mapped[str | None] = mapped_column(String(32), default=None)  # links to the trace
    # What the answer's model calls cost, in US dollars, for the daily spending caps.
    cost_usd: Mapped[float | None] = mapped_column(Float, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EvidenceRecord(Base):
    """An `Evidence` a verified claim cited, kept so the app can show it and follow-ups cite it.

    Only cited evidence is kept: everything else a run computed can be recomputed from the data.
    """

    __tablename__ = "evidence"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(32), default=None)
    tool: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)  # the whole Evidence, as JSON
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


# Fixed menus: the person chooses, nobody types, so nothing free-form enters memory from here.
CHECKIN_TAGS = ("hard_training", "alcohol", "late_meal", "stress", "travel", "feeling_sick")
CONTEXT_OPTIONS = (
    "travel",
    "work_or_exam_schedule",
    "more_training",
    "less_training",
    "illness",
    "new_device",
    "other",
    "rather_not_say",
)
QUESTION_STATUSES = ("asked", "answered", "dismissed")
FACT_STATUSES = ("proposed", "approved", "declined")


class Finding(Base):
    """A verified change or association from an investigation run (episodic memory).

    A newer finding on the same metric supersedes the older one; findings are kept 90 days.
    """

    __tablename__ = "findings"
    __table_args__ = (Index("ix_findings_user_metric_created", "user_id", "metric", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(String(32))
    metric: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # change or association
    direction: Mapped[str | None] = mapped_column(String(8), default=None)
    text: Mapped[str] = mapped_column(Text)  # the verified claim, as shown
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    window_start: Mapped[date] = mapped_column(Date)  # the dates the evidence covers
    window_end: Mapped[date] = mapped_column(Date)
    effect: Mapped[float | None] = mapped_column(Float, default=None)  # |Cliff's delta| or |rho|
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ContextQuestion(Base):
    """A question the agent asked about an unexplained change, and the person's answer.

    The prompt comes from a template and the options from a fixed menu; answers are kept 180 days.
    """

    __tablename__ = "context_questions"
    __table_args__ = (
        CheckConstraint(f"status IN {QUESTION_STATUSES}", name="ck_context_questions_status"),
        Index("ix_context_questions_user_asked", "user_id", "asked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    run_id: Mapped[str | None] = mapped_column(String(32), default=None)
    metric: Mapped[str] = mapped_column(String(64))
    prompt: Mapped[str] = mapped_column(Text)
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    options: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="asked")
    answer: Mapped[str | None] = mapped_column(String(32), default=None)
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class CheckIn(Base):
    """The morning "how do you feel today?" rating (1 to 5) with fixed tags; kept 365 days."""

    __tablename__ = "checkins"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="ck_checkins_rating"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    rating: Mapped[int]
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class MemoryFact(Base):
    """A short fact or preference (semantic memory), proposed by the agent and kept only once the
    person approves it. Not retrieved after 60 days unused."""

    __tablename__ = "memory_facts"
    __table_args__ = (
        CheckConstraint(f"kind IN {FACT_KINDS}", name="ck_memory_facts_kind"),
        CheckConstraint(f"status IN {FACT_STATUSES}", name="ck_memory_facts_status"),
        Index("ix_memory_facts_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(String(120))
    metrics: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    source_run_id: Mapped[str | None] = mapped_column(String(32), default=None)  # provenance
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    uses: Mapped[int] = mapped_column(default=0)


ACTION_STATUSES = (
    "draft",
    "executing",
    "succeeded",
    "failed",
    "unknown",
    "cancelled",
    "undoing",
    "undone",
)


class HealthAction(Base):
    """The exact reviewed payload and durable execution claim for a health-record write."""

    __tablename__ = "health_actions"
    __table_args__ = (
        UniqueConstraint("user_id", "request_key", name="uq_health_actions_request"),
        Index(
            "uq_health_actions_active_payload",
            "user_id",
            "fingerprint",
            unique=True,
            sqlite_where=text("status NOT IN ('cancelled', 'undone')"),
            postgresql_where=text("status NOT IN ('cancelled', 'undone')"),
        ),
        CheckConstraint("kind IN ('food', 'workout')", name="ck_health_actions_kind"),
        CheckConstraint("version > 0", name="ck_health_actions_version"),
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in ACTION_STATUSES)})",
            name="ck_health_actions_status",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    request_key: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    provider_name: Mapped[str | None] = mapped_column(String(512), default=None)
    operation_name: Mapped[str | None] = mapped_column(String(512), default=None)
    pending_operation: Mapped[str | None] = mapped_column(String(16), default=None)
    error: Mapped[str | None] = mapped_column(String(160), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class HealthActionEvent(Base):
    """Append-only snapshots: revision, confirmation and outcome, never model authorization."""

    __tablename__ = "health_action_events"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    action_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("health_actions.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column()
    event: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Team(Base):
    """A supervisor's group of people. The supervisor sees aggregates, never a member's data."""

    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    supervisor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    invite_code: Mapped[str] = mapped_column(String(16), unique=True)
    report_email: Mapped[str | None] = mapped_column(String(320), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TeamMembership(Base):
    """One person in one team, kept after they leave as a record of what they agreed to.

    Joining shares only team aggregates. Showing one's own named weekly levels is a second,
    separate consent, off until the person turns it on.
    """

    __tablename__ = "team_memberships"
    __table_args__ = (
        Index(
            "uq_team_memberships_active",
            "team_id",
            "user_id",
            unique=True,
            sqlite_where=text("left_at IS NULL"),
            postgresql_where=text("left_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    consent_version: Mapped[str] = mapped_column(String(32))
    share_levels: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    levels_consent_version: Mapped[str | None] = mapped_column(String(32), default=None)
    levels_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )


class TeamEvent(Base):
    """Append-only record of who joined, left, shared or changed a team's code, and when."""

    __tablename__ = "team_events"
    __table_args__ = (
        CheckConstraint(
            f"event IN ({', '.join(repr(e) for e in TEAM_EVENTS)})", name="ck_team_events_event"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    event: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TeamReport(Base):
    """One team's week: aggregates and text only. Named levels are read fresh when the report is
    opened, never stored, so a member who stops sharing disappears from past weeks too."""

    __tablename__ = "team_reports"
    __table_args__ = (
        UniqueConstraint("team_id", "week_start", name="uq_team_reports_week"),
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in TEAM_REPORT_STATUSES)})",
            name="ck_team_reports_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    week_start: Mapped[date] = mapped_column(Date)  # a Monday
    status: Mapped[str] = mapped_column(String(16))
    members_total: Mapped[int] = mapped_column()  # active members when it was made
    members_included: Mapped[int] = mapped_column()  # those with data that week
    headline: Mapped[str] = mapped_column(Text)
    body: Mapped[dict] = mapped_column(JSON)  # sections, each citing an evidence id
    evidence: Mapped[dict] = mapped_column(JSON)  # id -> the aggregate evidence it cites
    generated_by: Mapped[str] = mapped_column(String(16), default="template")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Reminder(Base):
    """A time-based reminder the person set, or one the agent proposed for them to approve.

    `schedule` is a validated `app.reminders.schedule` value; `next_due_at` is when it is next sent
    (UTC), kept so delivery reads due rows without recomputing every schedule.
    """

    __tablename__ = "reminders"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in REMINDER_STATUSES)})",
            name="ck_reminders_status",
        ),
        CheckConstraint(
            f"source IN ({', '.join(repr(s) for s in REMINDER_SOURCES)})",
            name="ck_reminders_source",
        ),
        CheckConstraint("version > 0", name="ck_reminders_version"),
        Index("ix_reminders_due", "status", "next_due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(String(280))
    schedule: Mapped[dict] = mapped_column(JSON)
    timezone: Mapped[str] = mapped_column(String(64))
    channels: Mapped[list] = mapped_column(JSON)  # "email", "in_app"
    status: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(280), default=None)  # why the agent asked
    evidence_id: Mapped[str | None] = mapped_column(String(32), default=None)
    next_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class NotificationSetting(Base):
    """How much the person wants to hear from Patterns; the defaults apply until they change it."""

    __tablename__ = "notification_settings"
    __table_args__ = (
        CheckConstraint("max_per_day BETWEEN 1 AND 10", name="ck_notification_settings_cap"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Local "HH:MM"; both None when quiet hours are off. The defaults live in the store.
    quiet_start: Mapped[str | None] = mapped_column(String(5))
    quiet_end: Mapped[str | None] = mapped_column(String(5))
    max_per_day: Mapped[int] = mapped_column(default=3)  # applies to suggestions, not your own
    email: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ReminderDelivery(Base):
    """One send of a reminder on one channel. Unique per due time, so it happens once even when
    two copies of the API overlap during a deploy."""

    __tablename__ = "reminder_deliveries"
    __table_args__ = (
        UniqueConstraint("reminder_id", "due_at", "channel", name="uq_reminder_deliveries_once"),
        CheckConstraint(
            f"channel IN ({', '.join(repr(c) for c in DELIVERY_CHANNELS)})",
            name="ck_reminder_deliveries_channel",
        ),
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in DELIVERY_STATUSES)})",
            name="ck_reminder_deliveries_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reminder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reminders.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    channel: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(String(200), default=None)  # safe to show
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Notification(Base):
    """What the app's inbox shows: a reminder that came due, later the smart alarms."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # reminder
    title: Mapped[str] = mapped_column(String(80))
    body: Mapped[str] = mapped_column(String(400))
    link: Mapped[str | None] = mapped_column(String(200), default=None)  # an app path
    reminder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reminders.id", ondelete="SET NULL"), default=None
    )
    # The smart alarm it carries, so the inbox can ask whether it was useful.
    alarm_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("alarms.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Alarm(Base):
    """A smart alarm: something in the person's data worth knowing, found by a detector.

    `pending` until it can be sent (outside quiet hours, under the daily cap); `suppressed` with a
    reason when it is not sent at all, kept for the evaluation; `expired` when it waited too long.
    """

    __tablename__ = "alarms"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in ALARM_STATUSES)})", name="ck_alarms_status"
        ),
        CheckConstraint(
            "feedback IS NULL OR feedback IN ('useful', 'not_useful')", name="ck_alarms_feedback"
        ),
        Index("ix_alarms_user_key", "user_id", "key", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # day, streak, finding, data
    metric: Mapped[str | None] = mapped_column(String(64), default=None)
    key: Mapped[str] = mapped_column(String(96))  # what the cooldown is kept by
    day: Mapped[date] = mapped_column(Date)
    severity: Mapped[float] = mapped_column(Float)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(600))
    written_by: Mapped[str] = mapped_column(String(16), default="template")  # or an expert
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)  # the explanation's model cost
    status: Mapped[str] = mapped_column(String(16), default="pending")
    reason: Mapped[str | None] = mapped_column(String(32), default=None)  # why not sent
    feedback: Mapped[str | None] = mapped_column(String(16), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class AlarmSetting(Base):
    """Which smart alarms the person wants; the defaults apply until they change something."""

    __tablename__ = "alarm_settings"
    __table_args__ = (
        CheckConstraint(
            "sensitivity IN ('fewer', 'normal', 'more')", name="ck_alarm_settings_sensitivity"
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(default=True)
    muted_kinds: Mapped[list[str]] = mapped_column(JSON, default=list)
    sensitivity: Mapped[str] = mapped_column(String(8), default="normal")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
