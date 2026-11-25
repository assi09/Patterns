"""Parts of the API that can be turned off as a whole (docs/pivot.md).

Since 2026-11-25 the app is built around teams. The individual side (Ask, findings, reminders,
smart alarms, memory, logging) stays in the code, tested, but answers like a missing endpoint
unless `FA_PERSONAL_FEATURES` is on. The app reads the same setting from the account, so the two
cannot disagree.
"""

from app.api.errors import ApiError
from app.config import settings


def personal_features() -> None:
    """FastAPI dependency: the individual side is turned off on this server."""
    if not settings.personal_features:
        raise ApiError(404, "not_found", "This part of the app is turned off.")
