"""Agent proposal tools: server-bound owner and request key, and no execution capability."""

import json
import re
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import date, datetime

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.actions import exercises, store
from app.actions.measure import Measurer, with_measurement
from app.actions.schemas import FoodLog, WorkoutLog
from app.actions.stated import lacks_a_duration, latest_past, mismatch, with_stated_interval
from app.agent.agent import ExtraTool
from app.api.errors import ApiError


def _when(moment: datetime, local_now: datetime) -> str:
    local = moment.astimezone(local_now.tzinfo)
    days = (local_now.date() - local.date()).days
    day = "today" if days == 0 else "yesterday" if days == 1 else f"{local:%a %-d %b}"
    return f"{day} at {local:%H:%M}"


def draft_sentence(payload: dict, local_now: datetime) -> str:
    """The draft in a friendly line, from its stored values: code writes it, so it cannot differ
    from the card."""
    check = "Have a look at the card and confirm it if it's right."
    if payload["kind"] == "workout":
        minutes = round(payload["activeSeconds"] / 60)
        length = f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"
        start = datetime.fromisoformat(payload["startTime"])
        name = exercises.in_sentence(payload["exerciseType"])
        return f"Ready to log: {name}, {_when(start, local_now)} for {length}. {check}"
    when = _when(datetime.fromisoformat(payload["consumedAt"]), local_now)
    estimate = (
        " The values are an estimate, so check they look right."
        if (payload.get("provenance") == "estimated")
        else ""
    )
    return f"Ready to log: {payload['foodName']}, {when}.{estimate} {check}"


# Values the person gave are theirs, even if the model also looked the food up.
STATED_VALUES = re.compile(r"\d\s*(?:kcal|cal(?:ories)?|g|grams?)\b", re.IGNORECASE)
NO_VALUES = "Supply at least one energy or macronutrient value"
LOOK_IT_UP = (
    "The food has no values yet. Call food_lookup with this food (and the grams if they said "
    "them), then call propose_food_log again with the values it returns. Do not ask the person."
)
ALREADY_THERE = (
    "This entry is already drafted or logged. Tell the person, in a sentence, that it is already "
    "there and they can check it on its card or under Logged food and workouts in Settings. Do "
    "not prepare it again or ask for details."
)
REFUSED_NOTE = (
    "Tell the person plainly what the problem is and what would fix it, in everyday words. Never "
    "change a time, date or duration they gave to get past it, and never ask for their time zone: "
    "the time at the top of the task is already theirs. A clock time with no day that has not "
    "come yet today means yesterday: prepare it for yesterday rather than refusing. Something they "
    "said is later today ('this evening', 'tonight') has not happened: say it can be logged once "
    "it is done."
)


def _untouched_changed(log: WorkoutLog, prior: dict) -> str | None:
    """Which duration a replacement changed that the correction did not: active or elapsed."""
    start = datetime.fromisoformat(prior["startTime"])
    elapsed = (datetime.fromisoformat(prior["endTime"]) - start).total_seconds()
    if abs(log.active_seconds - prior["activeSeconds"]) > 1:
        return "active time"
    if abs((log.end_time - log.start_time).total_seconds() - elapsed) > 1:
        return "elapsed time"
    return None


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
    described: list[str] | None = None,
    required_seconds: tuple[float, float] | None = None,
    required_day: date | None = None,
    prior_draft: dict | None = None,
    required_exercise: str | None = None,
) -> dict[str, list[ExtraTool]]:
    """`estimates` holds what food lookups found in this answer: a food draft made after one is
    labelled as an estimate by code, whatever the model says. `said` is the person's own words in
    this request and `local_now` their local time: a draft that contradicts them is refused.

    The request reader's validated facts bind the draft: `required_seconds` (active, elapsed) a
    correction's durations as code worked them out from the card, `required_day` the day it
    read, and `required_exercise` the activity it typed. A second recognizer of the same words
    must not overrule them: "Oct31" passed the reader and failed the day pattern, which then
    refused the draft as more than a day old (the 689fa7c audit)."""

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
                if model is FoodLog and estimates and not STATED_VALUES.search(" ".join(said)):
                    given |= {"provenance": "estimated", "estimateSource": estimates[-1]}
                checked_said = list(said)
                expected_day = required_day
                if prior_draft and local_now:
                    # An owned, already validated card supplies unchanged facts. A date-only
                    # correction must not have to restate its duration to replace the card.
                    when_key = "startTime" if prior_draft["kind"] == "workout" else "consumedAt"
                    prior_start = datetime.fromisoformat(prior_draft[when_key])
                    old_day = prior_start.astimezone(local_now.tzinfo).date()
                    expected_day = expected_day or old_day
                    previous = f"Previously stated day: {old_day}."
                    if prior_draft["kind"] == "workout":
                        elapsed = (
                            datetime.fromisoformat(prior_draft["endTime"]) - prior_start
                        ).total_seconds()
                        previous += f" Previously stated duration: {elapsed / 60:g} minutes."
                    checked_said.insert(0, previous)
                if required_seconds is not None:
                    active, elapsed = required_seconds
                    checked_said.append(
                        f"Correction: {active / 60:g} minutes active, {elapsed / 60:g} minutes "
                        "elapsed"
                    )
                if (
                    model is WorkoutLog
                    and required_exercise
                    and given.get("exerciseType") != required_exercise
                ):
                    given["exerciseType"] = required_exercise
                if (
                    model is WorkoutLog
                    and prior_draft is None
                    and (named := exercises.named_type("\n".join(said)))
                ):
                    given["exerciseType"] = named  # their own word, over the model's choice
                if model is WorkoutLog and checked_said and lacks_a_duration(checked_said):
                    problem = "The person did not say how long it lasted. Ask them, kindly."
                    content = {"error": "This draft was not prepared.", "problems": [problem]}
                    return json.dumps(content | {"note": REFUSED_NOTE}), {"error": "not_as_said"}
                day_known = expected_day is not None
                if said and local_now:
                    given = latest_past(given, checked_said, local_now, day_known=day_known)
                log = model.model_validate(given)
                # Editing a card with no new duration keeps the card's interval: its words name no
                # pause, so rebuilding the end from them turned a 12-minute pause into active
                # time (the a196 audit).
                keeps_card = prior_draft is not None and required_seconds is None
                # A correction's interval is code's, from the card (`required_seconds`): rebuilt
                # from the words, "33 active, the same twelve stopped" lost its pause again.
                if (
                    isinstance(log, WorkoutLog)
                    and checked_said
                    and not keeps_card
                    and required_seconds is None
                ):
                    log = with_stated_interval(log, checked_said)
                if (
                    isinstance(log, WorkoutLog)
                    and keeps_card
                    and prior_draft["kind"] == "workout"
                    and (changed := _untouched_changed(log, prior_draft))
                ):
                    return json.dumps(
                        {
                            "error": f"Keep the card's {changed}: the person did not change it. "
                            "Change only what they said."
                        }
                    ), {"error": "untouched_field", "field": changed}
                if isinstance(log, WorkoutLog) and required_seconds is not None:
                    active, elapsed = required_seconds
                    seconds = (log.end_time - log.start_time).total_seconds()
                    if abs(seconds - elapsed) > 1 or abs(log.active_seconds - active) > 1:
                        return json.dumps(
                            {
                                "error": f"Use {active / 60:g} minutes of active time and "
                                f"{elapsed / 60:g} minutes from start to end (the pause kept), "
                                "preserving the other draft fields."
                            }
                        ), {"error": "stale_duration"}
                if expected_day is not None and local_now is not None:
                    moment = log.start_time if isinstance(log, WorkoutLog) else log.consumed_at
                    if moment.astimezone(local_now.tzinfo).date() != expected_day:
                        return json.dumps(
                            {
                                "error": "Use the day the person named. Future entries "
                                "can be logged after they happen; do not move them."
                            }
                        ), {"error": "wrong_day"}
                if (
                    checked_said
                    and local_now
                    and (problem := mismatch(log, checked_said, local_now, day_known=day_known))
                ):
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
                # A food named with no values: look it up, then propose again. Told only "supply
                # a value", the model asked the person or gave up half the time (2026-11-16).
                if estimates is not None and any(NO_VALUES in p for p in problems):
                    content["note"] = LOOK_IT_UP
                # Field names and our own rules' messages hold no values: safe to keep in the trace.
                return json.dumps(content), {
                    "error": "invalid_log",
                    "fields": fields,
                    "problems": problems,
                }
            except ApiError as exc:
                # Our own messages hold no values ("This entry already has a draft or a logged
                # record."). Told only "could not be prepared", the model asked the person for
                # details they had given (2026-11-16).
                content = {
                    "error": "This draft was not prepared.",
                    "problems": [exc.message],
                    "note": ALREADY_THERE if exc.code == "duplicate_log" else REFUSED_NOTE,
                }
                return json.dumps(content), {"error": exc.code}
            except Exception:
                # SQL/transport exceptions may contain the log payload; never send or log them.
                return json.dumps(
                    {"error": "Could not save the draft. Check saved entries before retrying."}
                ), {"error": "draft_storage"}
            if content["draft_id"] not in prepared:
                prepared.append(content["draft_id"])
                if described is not None and local_now is not None:
                    described.append(draft_sentence(row.payload, local_now))
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
