"""Error reports to Sentry: off unless `FA_SENTRY_DSN` is set.

Grafana says *that* requests fail (docs/monitoring.md); Sentry says *where*: the exception type,
the stack and the release, grouped, with an email for a new kind. Health data must never leave
with it, so an event keeps only the shape of the failure:

- no exception messages (a `ValueError` can carry a value), no local variables, no log
  arguments (only the template, e.g. "Sync failed"), no breadcrumbs;
- no request body, query string, cookies or headers beyond a few harmless ones (never
  `Authorization`); no user;
- errors only: no performance tracing.

Captured: exceptions the API does not handle (a 500), and `logger.error` / `logger.exception`
records, which is how the background passes (syncs, alarms, team alerts, reminders) and the
chat report their failures.
"""

import logging
import os
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.transport import Transport

from app.config import Settings

REMOVED = "[removed]"
_SAFE_HEADERS = {"content-type", "content-length", "host", "user-agent"}


def _strip_frames(stacktrace: dict[str, Any] | None) -> None:
    for frame in (stacktrace or {}).get("frames", []):
        frame.pop("vars", None)


def scrub(event: dict[str, Any], _hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep where and what kind of failure; drop anything that could hold a person's data."""
    for exception in (event.get("exception") or {}).get("values", []):
        if exception.get("value"):
            exception["value"] = REMOVED
        _strip_frames(exception.get("stacktrace"))
    for thread in (event.get("threads") or {}).get("values", []):
        _strip_frames(thread.get("stacktrace"))

    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        logentry.pop("params", None)
        logentry.pop("formatted", None)
    if "message" in event:
        # A formatted message may hold a log record's arguments: keep only its template.
        event["message"] = (
            logentry.get("message", REMOVED) if isinstance(logentry, dict) else REMOVED
        )

    request = event.get("request")
    if isinstance(request, dict):
        for key in ("data", "query_string", "cookies", "env"):
            request.pop(key, None)
        headers = request.get("headers") or {}
        request["headers"] = {
            name: value for name, value in headers.items() if name.lower() in _SAFE_HEADERS
        }

    for key in ("user", "breadcrumbs", "extra"):
        event.pop(key, None)
    return event


def init_sentry(settings: Settings, transport: Transport | None = None) -> bool:
    """Start reporting errors if a DSN is configured; returns whether it started."""
    if settings.sentry_dsn is None:
        return False
    options: dict[str, Any] = {}
    if transport is not None:
        options["transport"] = transport
    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.sentry_environment,
        # Railway sets this for a deploy from GitHub, so each error names its commit.
        release=os.environ.get("RAILWAY_GIT_COMMIT_SHA") or None,
        # No personal data is collected by default; `scrub` removes the rest before sending.
        include_local_variables=False,
        max_request_body_size="never",
        max_breadcrumbs=0,
        integrations=[LoggingIntegration(level=None, event_level=logging.ERROR)],
        before_send=scrub,
        **options,
    )
    return True
