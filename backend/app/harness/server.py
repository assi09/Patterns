"""The MCP server at /mcp (docs/mcp.md), for Claude Code, Codex and other harnesses.

A bearer token made in the app identifies the person; every tool then checks their current role
and returns only what the app would show them (`app.harness.tools`). Check-in alerts have no tool.
"""

import threading
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from sqlalchemy.orm import Session

from app.db.models import User
from app.harness import tokens, tools
from app.harness.tools import CalendarDayIn, HarnessError, TeamEventIn

Sessions = Callable[[], AbstractContextManager[Session]]

INSTRUCTIONS = (
    "Patterns describes a team's or a person's own Fitbit and calendar patterns, from computed "
    "figures only. Call who_am_i first. Supervisors read their own teams' figures, built from at "
    "least 5 people, and may send team events. Members read their own days and may send their "
    "own calendar days. Anything sent is held until the person approves it in the app. There is "
    "no way to read another person's data or any check-in alert."
)


class TokenCheck:
    """Resolves a personal access token to its account, on every request."""

    def __init__(self, sessions: Sessions):
        self.sessions = sessions

    async def verify_token(self, token: str) -> AccessToken | None:
        with self.sessions() as db:
            found = tokens.holder(db, token, datetime.now(UTC))
            if found is None:
                return None
            user, row = found
            return AccessToken(
                token="",  # never kept or logged
                client_id="patterns-personal-token",
                scopes=[],
                subject=str(user.id),
                claims={"token_id": str(row.id)},
            )


class RateLimit:
    """At most `per_minute` tool calls per token, so a harness in a loop cannot load a team's data
    hundreds of times a minute. In memory: one API process, as deployed."""

    def __init__(self, per_minute: int = 60):
        self.per_minute = per_minute
        self._calls: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            calls = self._calls[key]
            while calls and now - calls[0] >= 60:
                calls.popleft()
            if len(calls) >= self.per_minute:
                return False
            calls.append(now)
            return True


limits = RateLimit()


def _caller(db: Session) -> tuple[User, uuid.UUID | None]:
    access = get_access_token()
    if access is None or access.subject is None:
        raise HarnessError("Sign in with a Patterns token.")
    key = (access.claims or {}).get("token_id") or access.subject
    if not limits.allow(key):
        raise HarnessError(
            f"Too many calls: at most {limits.per_minute} a minute per token. Try again shortly."
        )
    user = db.get(User, uuid.UUID(access.subject))
    if user is None or user.status != "approved":
        raise HarnessError("This token's account is not active.")
    token_id = (access.claims or {}).get("token_id")
    return user, uuid.UUID(token_id) if token_id else None


def _today(user: User, fallback: str) -> date:
    try:
        return datetime.now(ZoneInfo(user.timezone or fallback)).date()
    except (ValueError, KeyError):
        return datetime.now(UTC).date()


def build(sessions: Sessions, public_url: str, timezone: str = "UTC") -> MCPServer:
    """The server with its tools; `asgi_app` serves it."""
    base = public_url.rstrip("/")
    server = MCPServer(
        name="Patterns",
        instructions=INSTRUCTIONS,
        token_verifier=TokenCheck(sessions),
        auth=AuthSettings(
            issuer_url=base,
            resource_server_url=f"{base}/mcp",
            # Personal tokens are opaque and only ever issued by this server for itself, so the
            # verifier's own lookup is the audience check.
            validate_token_resource=False,
        ),
    )

    @server.tool(description="Who the token belongs to, their role and what they may do.")
    def who_am_i() -> dict:
        with sessions() as db:
            user, _ = _caller(db)
            return tools.who_am_i(db, user)

    @server.tool(
        description="A supervisor's team as on its Team tab: observed readings, the latest weekly "
        "report's team figures and open team alerts. Aggregates from at least 5 people."
    )
    def team_overview(team_id: str) -> dict:
        with sessions() as db:
            user, _ = _caller(db)
            return tools.team_overview(db, user, team_id, _today(user, timezone))

    @server.tool(
        description="A supervisor's team meeting load for the last full week, per person against "
        "each member's usual week, from at least 5 people."
    )
    def team_meeting_load(team_id: str) -> dict:
        with sessions() as db:
            user, _ = _caller(db)
            return tools.team_meeting_load(db, user, team_id, _today(user, timezone))

    @server.tool(description="Your own last days (1-28): sleep, steps, resting heart rate, HRV.")
    def my_recent_days(days: int = 7) -> list[dict]:
        with sessions() as db:
            user, _ = _caller(db)
            return tools.my_recent_days(db, user, _today(user, timezone), days)

    @server.tool(description="Your own daily calendar counts (1-60 days), as Patterns has them.")
    def my_calendar_days(days: int = 14) -> list[dict]:
        with sessions() as db:
            user, _ = _caller(db)
            return tools.my_calendar_days(db, user, _today(user, timezone), days)

    @server.tool(
        description="Send your own calendar days, counted from your calendar: meeting minutes, "
        "meetings, minutes after hours, back-to-back meetings, focus minutes. Held until you "
        "approve them in the Patterns app."
    )
    def send_calendar_days(days: list[CalendarDayIn]) -> dict:
        with sessions() as db:
            user, token_id = _caller(db)
            return tools.send_calendar_days(db, user, days, token_id, datetime.now(UTC))

    @server.tool(
        description="Send a team event (a launch, a deadline) for your team's notes: a short "
        "title and dates. Held until you approve it in the Patterns app."
    )
    def send_team_event(team_id: str, event: TeamEventIn) -> dict:
        with sessions() as db:
            user, token_id = _caller(db)
            return tools.send_team_event(db, user, team_id, event, token_id, datetime.now(UTC))

    return server


def asgi_app(server: MCPServer, public_url: str):
    """The Starlette app to mount at /mcp, with DNS-rebinding protection on for our own host and
    local development only."""
    from urllib.parse import urlparse

    from mcp.server.transport_security import TransportSecuritySettings

    host = urlparse(public_url).netloc
    allowed = ["127.0.0.1:*", "localhost:*", "[::1]:*", "testserver"]
    if host:
        allowed += [host, f"{host}:*"]
    return server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,  # each call stands alone: nothing about a person is kept between
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=allowed
        ),
    )
