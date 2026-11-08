"""Agent proposal tools: server-bound owner and request key, and no execution capability."""

import json
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.actions import store
from app.actions.measure import Measurer, with_measurement
from app.actions.schemas import FoodLog, WorkoutLog
from app.actions.stated import mismatch
from app.agent.agent import ExtraTool
from app.api.errors import ApiError

REFUSED_NOTE = (
    "Tell the person plainly what the problem is and what would fix it, in everyday words. Never "
    "change a time, date or duration they gave to get past it, and never ask for their time zone: "
    "the time at the top of the task is already theirs."
)


def proposal_tools(
    sessions: Callable[[], AbstractContextManager[Session]],
    user_id: uuid.UUID,
    question_id: uuid.UUID,
    now: datetime,
    prepared: list[str],
    measurer: Measurer | None = None,
    estimates: list[str] | None = None,
    said: Sequence[str] = (),
    local_now: datetime | None = None,
) -> dict[str, list[ExtraTool]]:
    """`estimates` holds what food lookups found in this answer: a food draft made after one is
    labelled as an estimate by code, whatever the model says. `said` is the person's own words in
    this request and `local_now` their local time: a draft that contradicts them is refused."""

    def tool(model: type[FoodLog] | type[WorkoutLog], expert: str) -> ExtraTool:
        schema = model.model_json_schema(by_alias=True)
        schema.pop("title", None)
        # The tracker's reading is the server's to add, so the model is not offered the field.
        for owned in ("measured", "provenance", "estimateSource"):
            schema.get("properties", {}).pop(owned, None)
        for name in ("Measured", "Overlap", "ZoneSeconds"):
            schema.get("$defs", {}).pop(name, None)
        if not schema.get("$defs"):
            schema.pop("$defs", None)

        def run(arguments: dict | None) -> tuple[str, dict]:
            try:
                owned = ("measured", "provenance", "estimateSource")
                given = {k: v for k, v in (arguments or {}).items() if k not in owned}
                if model is FoodLog and estimates:
                    given |= {"provenance": "estimated", "estimateSource": estimates[-1]}
                log = model.model_validate(given)
                if said and local_now and (problem := mismatch(log, said, local_now)):
                    content = {"error": "This draft was not prepared.", "problems": [problem]}
                    return json.dumps(content | {"note": REFUSED_NOTE}), {"error": "not_as_said"}
                payload = with_measurement(
                    log.model_dump(mode="json", by_alias=True, exclude_none=True), measurer
                )
                # Repeated identical calls in this question prepare one draft, across restarts.
                key = uuid.uuid5(question_id, payload["kind"])
                with sessions() as db:
                    row = store.propose(db, user_id, key, payload, now)
                    content = {
                        "draft_id": str(row.id),
                        "version": row.version,
                        "status": row.status,
                        "log": row.payload,
                        "note": "Draft only; review and confirm before sending to Google.",
                    }
            except ValidationError as exc:
                # Field names are safe, unlike Pydantic's input-bearing error strings.
                fields = sorted(
                    {str(e["loc"][0]) for e in exc.errors(include_input=False) if e["loc"]}
                )
                # Our own rules' messages name no values, and say what is wrong; without them
                # the model can only guess, and asks the person for things it already knows.
                problems = [
                    e["msg"].removeprefix("Value error, ")
                    for e in exc.errors(include_input=False)
                    if e["type"] == "value_error"
                ]
                content = {
                    "error": "This draft was not prepared.",
                    "fields": fields,
                    "problems": problems,
                    "note": REFUSED_NOTE,
                }
                return json.dumps(content), {"error": "invalid_log"}
            except ApiError:
                return json.dumps({"error": "The draft could not be prepared."}), {
                    "error": "invalid_log"
                }
            except Exception:
                # SQL/transport exceptions may contain the log payload; never send or log them.
                return json.dumps(
                    {"error": "Could not save the draft. Check saved entries before retrying."}
                ), {"error": "draft_storage"}
            if content["draft_id"] not in prepared:
                prepared.append(content["draft_id"])
            return json.dumps(content), {k: content[k] for k in ("draft_id", "version", "status")}

        return ExtraTool(
            f"propose_{'food' if expert == 'nutrition' else 'workout'}_log",
            "Prepare one draft per message, using supplied values. Write times with the UTC "
            "offset given at the top of the task: 'just now' is the current local time there, "
            "and 'this morning' or 'yesterday at lunch' are worked out from it. Ask only for "
            "details that are truly missing. Never estimate nutrients yourself: with no values "
            "given, use food_lookup if you have it, and ask otherwise. Never invent measurements "
            "or claim it was logged. For a workout, pick the exerciseType closest to what they did "
            "(tennis is TENNIS, kickboxing KICKBOXING; OTHER only if nothing fits); the server "
            "adds what the tracker recorded during it (calories, heart rate and zones, plus "
            "steps, distance or swim lengths where Fitbit records them) and any exercise already "
            "recorded then. The review card shows those, so do not repeat them as findings. This "
            "tool cannot confirm, execute or delete a Google record.",
            schema,
            run,
        )

    return {"nutrition": [tool(FoodLog, "nutrition")], "activity": [tool(WorkoutLog, "activity")]}
