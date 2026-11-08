"""The agent's reminder tools: it may prepare a reminder and read the person's reminders, no more.

`propose_reminder` stores a `proposed` reminder, never an active one: the person turns it on with
one tap on the card in the chat (decision 10), even when they asked for it. The agent cannot change,
pause or delete a reminder; it reads them with `list_reminders` and points to the Reminders tab.
"""

import json
import re
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import datetime

from sqlalchemy.orm import Session

from app.agent.agent import ExtraTool
from app.agent.verifier import MEDICAL
from app.api.errors import ApiError
from app.db.models import User
from app.reminders import store
from app.reminders.schedule import describe

PROPOSE = "propose_reminder"
SAID_WHEN = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\b\d{1,2}:\d{2}\b|\bat \d{1,2}\b|\bin (?:an?|\d+) |"
    r"\b(?:morning|noon|afternoon|evening|night|tonight|tomorrow|midnight|bedtime)\b",
    re.IGNORECASE,
)
LIST = "list_reminders"
MAX_PROPOSALS = 3  # per answer
# Reminders are for everyday habits; medication is a medical matter, refused like advice.
MEDICINE = re.compile(r"\b(pills?|tablets?|medicines?|meds|dose|dosage|insulin|inhaler)\b", re.I)
REMINDER_NOTE = "Here's the reminder. Tap Set on the card to turn it on."
# A reply may not say the reminder is already on: it waits for the person's tap.
CLAIMS_SET = re.compile(
    r"\b(?:i've|i have|has been|is now|is|are)\s+(?:set|scheduled|created|added)\b"
    r"|\ball set\b|\bdone\b",
    re.IGNORECASE,
)
WAITS = re.compile(r"\b(?:tap|card|turn it on|confirm|approve)", re.IGNORECASE)

REMINDER_PROMPT = (
    "\nYou can prepare reminders the person asks for with propose_reminder: a short title, the "
    "message they will see, and a schedule in their local time, either kind 'once' with a date and "
    "a time, or kind 'weekly' with a time and weekdays (0 is Monday; every day is all seven, "
    "weeknights are 0-4). Work out 'tonight', 'tomorrow at 7' or 'weeknights' from the current "
    "local time at the top of the task. Send in the app and by email unless they say otherwise. If "
    "the time is missing, ask for it instead of guessing. A prepared reminder is not on yet: the "
    "person turns it on with one tap on its card, so never say it is set. To see, change or stop "
    "their reminders, call list_reminders and tell them to use the switch or the reminder's page "
    "in Reminders; you cannot change or stop one. Apps cannot set alarms on the Fitbit itself; if "
    "asked, say so and offer a reminder. Reminders are for everyday habits (bedtime, water, "
    "stretching, training, logging); never schedule medication or anything medical. For a "
    "reminder request, do not run statistical investigations. After proposing, call "
    "submit_findings with a short summary that has no times or numbers (the card shows them), says "
    "to tap Set on the card, and has claims=[] and no hypotheses. If you need a detail, call "
    "submit_findings with the question as the summary and claims=[]."
)


def _schedule_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["once", "weekly"]},
            "date": {"type": "string", "description": "YYYY-MM-DD, for once"},
            "time": {"type": "string", "description": "HH:MM, 24-hour local time"},
            "weekdays": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0, "maximum": 6},
                "description": "for weekly; 0 is Monday",
            },
        },
        "required": ["kind", "time"],
    }


def reminder_tools(
    sessions: Callable[[], AbstractContextManager[Session]],
    user_id: uuid.UUID,
    now: datetime,
    prepared: list[str],
    said: Sequence[str] = (),
) -> list[ExtraTool]:
    """The two tools for one answer; ids of proposed reminders are appended to `prepared`."""

    def propose(arguments: dict | None) -> tuple[str, dict]:
        arguments = arguments or {}
        if len(prepared) >= MAX_PROPOSALS:
            message = "You already prepared enough reminders in this answer."
            return json.dumps({"error": message}), {"error": "too_many"}
        title = str(arguments.get("title", ""))
        message = str(arguments.get("message", ""))
        if MEDICAL.search(f"{title} {message}") or MEDICINE.search(f"{title} {message}"):
            refusal = "Reminders here are for everyday habits, not medication or treatment."
            return json.dumps({"error": refusal}), {"error": "medical"}
        if said and not SAID_WHEN.search(" ".join(said)):
            return json.dumps({"error": "They did not say when. Ask them; never pick a time."}), {
                "error": "no_time"
            }
        schedule = arguments.get("schedule") or {}
        if schedule.get("kind") == "once":
            schedule = {k: schedule.get(k) for k in ("kind", "date", "time")}
        else:
            schedule = {k: schedule.get(k) for k in ("kind", "time", "weekdays")}
        try:
            with sessions() as db:
                row = store.create(
                    db,
                    db.get(User, user_id),
                    title=title,
                    message=message,
                    schedule=schedule,
                    channels=list(arguments.get("channels") or ["in_app", "email"]),
                    now=now,
                    source="agent",
                    reason=arguments.get("reason"),
                )
                content = {
                    "reminder_id": str(row.id),
                    "status": row.status,
                    "schedule": describe(store.schedule_of(row)),
                    "note": "Proposed only: the person turns it on with one tap on the card.",
                }
        except ApiError as error:
            # The store's messages are written for people and safe to pass back.
            return json.dumps({"error": error.message}), {"error": error.code}
        prepared.append(content["reminder_id"])
        return json.dumps(content), {"reminder_id": content["reminder_id"]}

    def listing(arguments: dict | None) -> tuple[str, dict]:
        with sessions() as db:
            rows = [
                {
                    "title": row.title,
                    "schedule": describe(store.schedule_of(row)),
                    "status": row.status,
                    "channels": row.channels,
                }
                for row in store.listing(db, user_id)
                if row.status in ("proposed", "active", "paused")
            ]
        return json.dumps({"reminders": rows}), {"count": len(rows)}

    return [
        ExtraTool(
            PROPOSE,
            "Prepare one reminder the person asked for. It stays off until they tap Set on its "
            "card; this tool cannot turn it on, change or stop a reminder.",
            {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "maxLength": 80},
                    "message": {"type": "string", "maxLength": 280},
                    "schedule": _schedule_schema(),
                    "channels": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["in_app", "email"]},
                    },
                    "reason": {
                        "type": "string",
                        "maxLength": 280,
                        "description": "only when you suggest it from a pattern in their data",
                    },
                },
                "required": ["title", "message", "schedule"],
            },
            propose,
        ),
        ExtraTool(
            LIST,
            "The person's reminders: title, schedule, status (proposed, active, paused), channels.",
            {"type": "object", "properties": {}},
            listing,
        ),
    ]


def reminder_reply(summary: str) -> str:
    """The agent's reply after preparing a reminder when it is safe; the fixed note if not."""
    text = summary.strip()
    if not text or CLAIMS_SET.search(text) or not WAITS.search(text) or MEDICAL.search(text):
        return REMINDER_NOTE
    return text
