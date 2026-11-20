"""The Ask screen's conversation: `GET /chat` and `POST /chat`.

A question is answered by `ask()` with the person's own data, conversation and memory. The request
waits for the answer up to `settings.chat_wait_s`; a slower answer keeps running and is stored when
it is done, so the app finds it when it reloads the chat. One question at a time per person.

Spending: every answer's cost is stored, and a question is refused before any model runs once the
person, or the whole app, has reached its daily cap. The caps count local days.
"""

import json
import logging
import re
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as WaitTimeout
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from time import monotonic
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.actions import store as health_store
from app.actions.schemas import Measured
from app.actions.tools import proposal_tools
from app.agent.agent import NO_ANSWER
from app.agent.ask import (
    CORRECTS,
    NOTED,
    NOTHING_WAITING,
    REMINDERS,
    ask,
    claims_false_success,
    default_guard,
    default_router,
    urgent_free,
)
from app.agent.context import Attachment, ChatState, turns_from
from app.agent.conversation import DRAFT_NOTE
from app.agent.experts import EXPERTS, Depth, available
from app.agent.guard import Guard
from app.agent.intent import Intent
from app.agent.listener import (
    MAX_KNOWN,
    fit_to_keep,
    is_explicit,
    listen,
    which_kept,
    worth_listening,
)
from app.agent.llm import LLM, Budget, LLMError, OpenAILLM
from app.agent.requests import Request, interpret
from app.agent.router import Router
from app.agent.strategy_types import certain_talk, is_statement
from app.agent.summary import FOLD_AT, fold, to_fold
from app.agent.trace import failed_trace, personal_trace
from app.agent.world import food_tool
from app.analysis.day import with_scores
from app.analysis.habits import with_checkins
from app.api import schemas
from app.api.auth import Db, approved_user
from app.api.errors import ApiError
from app.api.store import LoadedData, get_data
from app.config import settings
from app.db import chat as store
from app.db import memory
from app.db.models import (
    CHECKIN_TAGS,
    AnswerTrace,
    ChatMessage,
    CheckIn,
    Conversation,
    HealthAction,
    MemoryEpisode,
    Reminder,
    Spend,
    User,
)
from app.db.session import session_scope
from app.outside import FoodData, Outside, model_choice
from app.reminders.schedule import describe
from app.reminders.store import SCHEDULE, timezone_of
from app.reminders.tools import ALARM, listing_reply, reminder_reply, reminder_tools

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

HISTORY_SHOWN = 100  # messages the app gets back
HISTORY_USED = 20  # messages the agent sees as context; the context builder trims further
HISTORY_FOLDED = 40  # messages looked at for the running summary
DRAFT_WITHOUT_ONE = re.compile(r"\bdraft\b", re.IGNORECASE)
NO_DRAFT_REPLY = "I couldn't get that entry ready. Could you send it once more?"
# Prose saying a card exists: "I've got that walk drafted", "the draft is ready below". True only
# when the store has one; "Okay, submit that one" was told a walk was drafted that never was.
CLAIMS_A_DRAFT = re.compile(
    r"\bdrafted\b|\b(?:draft|card) (?:is |'s )?(?:now )?(?:ready|waiting|below|above|prepared|"
    r"set up)\b|\b(?:put|added|placed) (?:it|that|this|them) on (?:a|the) card\b|"
    r"\bready to log\b",
    re.IGNORECASE,
)
# Fixed replies from code, which already say what the store holds.
FROM_CODE = ("requested", "limits", "refused", "urgent", "noted", "looked_up")
STILL_WAITING = "Until then, the earlier draft is still waiting on its card, unchanged."
CORRECTION_FAILED = (
    "I couldn't change the card, so the earlier draft is still waiting as it was: nothing was "
    "replaced or sent. You can tap Edit on it to change it yourself."
)
WAITING_ANSWERS = 4  # recent answers whose waiting drafts a "log it" or a correction refers to
MAX_THREAD = 6  # the person's messages kept from one logging request still being asked about
QUIET_INTENTS = (Intent.LOG, Intent.REMIND)  # one-off requests: nothing to listen for
FAILED = "I couldn't finish answering this time. Please try again in a moment."

Sessions = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class AgentParts:
    llm: LLM
    router: Router
    guard: Guard | None
    background: bool = False  # the summary and the listener: small model calls after an answer


@lru_cache(maxsize=1)
def _agent() -> AgentParts:
    try:
        llm = OpenAILLM.from_settings(settings)
    except LLMError as exc:
        logger.warning("The agent is not available: %s", exc)
        raise ApiError(503, "agent_unavailable", "Answering questions is not set up yet.") from exc
    return AgentParts(llm, default_router(settings), default_guard(settings), background=True)


@lru_cache(maxsize=1)
def food_data() -> FoodData | None:
    return FoodData.from_settings(settings)


def food_data_for(llm: LLM) -> FoodData | None:
    """USDA's matches ranked by meaning, then the food described chosen by the model: right first
    for 22 of 25 held-out foods, against 14 in USDA's own order (eval/food_rank_eval.py)."""
    found = food_data()
    if found is None:
        return None
    return replace(found, embed=lambda texts: llm.embed(texts).vectors, choose=model_choice(llm))


def get_agent() -> AgentParts:
    """FastAPI dependency; tests override it with a scripted model."""
    return _agent()


def get_sessions() -> Sessions:
    """FastAPI dependency: how the answering thread opens its own sessions. Tests override it."""
    return session_scope


# Answers run on their own threads so a request can stop waiting without stopping the answer.
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chat")
_busy: set[object] = set()
_busy_lock = threading.Lock()


class AttachmentIn(schemas.ApiModel):
    kind: Literal["finding", "metric"]
    id: str | None = Field(default=None, max_length=100)
    metric: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _complete(self):
        if (self.kind == "finding" and not self.id) or (self.kind == "metric" and not self.metric):
            raise ValueError("an attachment needs its id or metric")
        return self


class Question(schemas.ApiModel):
    text: str = Field(min_length=1, max_length=2000)
    expert: Literal["auto", "sleep", "recovery", "activity", "nutrition"] = "auto"
    depth: Literal["quick", "deep"] = "quick"
    attachment: AttachmentIn | None = None
    conversation_id: uuid.UUID | None = None  # the latest conversation, or a new one, if absent
    # Editing or retrying: this question and everything after it are replaced by the new one.
    replaces: uuid.UUID | None = None


def _message(row: ChatMessage) -> schemas.ChatMessage:
    return schemas.ChatMessage(
        id=str(row.id),
        role=row.role,
        text=row.text,
        sources=[schemas.SourceLink(**link) for link in row.sources or []] or None,
        evidence_ids=list(row.evidence_ids or []),
        action_ids=list(row.action_ids or []) or None,
        reminder_ids=list(row.reminder_ids or []) or None,
        attachment=row.attachment,
        answered_by=row.answered_by if row.role == "assistant" else None,
        routed=row.routed if row.role == "assistant" else None,
        consulted=list(row.consulted or []) or None,
        refused=row.refused or None,
        conversation_id=str(row.conversation_id) if row.conversation_id else None,
        rating=row.rating if row.role == "assistant" else None,
        created_at=_aware(row.created_at),
    )


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _conversation(row: Conversation, messages: int) -> schemas.Conversation:
    return schemas.Conversation(
        id=str(row.id),
        title=row.title,
        pinned=bool(row.pinned),
        messages=messages,
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
    )


def _owned(db: Session, user: User, conversation_id: uuid.UUID) -> Conversation:
    conversation = store.get_conversation(db, user.id, conversation_id)
    if conversation is None:
        raise ApiError(404, "not_found", "No such conversation.")
    return conversation


def _day_start(now: datetime) -> datetime:
    """Midnight of the current local day, in UTC."""
    zone = ZoneInfo(settings.timezone)
    local = now.astimezone(zone)
    return datetime.combine(local.date(), time(), zone).astimezone(UTC)


def _spent(db: Session, since: datetime, user: User | None = None) -> float:
    """From the spending ledger, not the chats: a deleted chat's answers still count today."""
    query = select(func.coalesce(func.sum(Spend.cost_usd), 0.0)).where(Spend.at >= since)
    if user is not None:
        query = query.where(Spend.user_id == user.id)
    return float(db.scalar(query))


def check_caps(db: Session, user: User, now: datetime) -> None:
    since = _day_start(now)
    if _spent(db, since) >= settings.chat_daily_cap_total_usd:
        raise ApiError(
            429,
            "app_daily_limit",
            "Patterns has answered all it can for today. Try again tomorrow.",
        )
    if _spent(db, since, user) >= settings.chat_daily_cap_per_user_usd:
        raise ApiError(
            429, "daily_limit", "You've reached today's limit for questions. Try again tomorrow."
        )


def _attachment(data: LoadedData, given: AttachmentIn | None) -> Attachment | None:
    if given is None:
        return None
    if given.kind == "metric":
        if given.metric not in data.daily.frame.columns:
            raise ApiError(422, "invalid_request", "That metric is not in your data.")
        return Attachment(metric=given.metric)
    finding = next((f for f in data.report.findings if f.id == given.id), None)
    if finding is None:
        raise ApiError(404, "not_found", "That finding is no longer in your report.")
    evidence = tuple(data.report.evidence[i] for i in finding.evidence_ids)
    return Attachment(
        metric=finding.metric, finding=f"{finding.title}. {finding.summary}", evidence=evidence
    )


def answer_text(summary: str, claims: list[str], notes: list[str]) -> str:
    """What the person reads: the summary as the answer, then any fixed notes.

    The verified claims back the summary and are shown as evidence links, not repeated as text;
    they are read out only when there is no summary."""
    body = summary.strip() or " ".join(c.strip() for c in claims if c.strip())
    paragraphs: list[str] = []
    for part in (body, *notes):
        part = part.strip()
        if part and part not in paragraphs:
            paragraphs.append(part[0].upper() + part[1:])
    return "\n\n".join(paragraphs) or FAILED


def logging_thread(earlier: list[ChatMessage]) -> list[str]:
    """The person's messages so far in the request the agent is still asking about, oldest first.
    Each reply is one detail; the request is all of them together."""
    said: list[str] = []
    at = len(earlier) - 1
    while (
        at >= 1
        and len(said) < MAX_THREAD
        and earlier[at].role == "assistant"
        and earlier[at].pending_log_expert
        and earlier[at - 1].role == "user"
    ):
        said.insert(0, earlier[at - 1].text)
        at -= 2
    return said


def continued_request(thread: list[str], asked: str, reply: str) -> str:
    """A reply with the request it continues, for the agent and the router."""
    added = "".join(f"They added: {text}\n" for text in thread[1:])
    return f"Earlier request: {thread[0]}\n{added}You asked: {asked}\nTheir reply: {reply}"


def update_summary(sessions: Sessions, llm: LLM, user_id, conversation_id: uuid.UUID) -> None:
    """Folds the turns that left the verbatim window into the chat's summary, after the answer."""
    try:
        with sessions() as db:
            conversation = store.get_conversation(db, user_id, conversation_id)
            if conversation is None:
                return
            previous, seen = conversation.summary, conversation.summary_until
            turns = turns_from(store.history(db, user_id, HISTORY_FOLDED, conversation_id))
        pending = to_fold(turns, seen)
        if len(pending) < FOLD_AT:
            return
        folded = fold(llm, previous, pending)
        with sessions() as db:
            if folded.text is not None:
                store.save_summary(db, user_id, conversation_id, folded.text, pending[-1].at, seen)
            store.charge_answer(db, user_id, conversation_id, folded.cost_usd)
    except Exception:
        logger.exception("Updating a chat's summary failed")


def listen_to(
    sessions: Sessions,
    agent: AgentParts,
    user_id,
    question_id,
    text: str,
    today,
    now: datetime,
    asked: bool = False,
) -> None:
    """Hears what the person's message says about them; nothing is kept without their tap
    (`app.db.memory.propose_fact`). Returns the status of what it recorded (empty when nothing
    passed the rules), or None when listening failed. `asked`: the request reader read an
    explicit request to remember, however it was worded ("Would you remember that I choose
    swimming?" is a question, and was not listened to, Codex's audit of 84db5f5)."""
    if not asked and not worth_listening(text):
        return []
    statuses: list[str] = []
    try:
        with sessions() as db:
            held = memory.held_facts(db, user_id)[:MAX_KNOWN]
            known = [(fact.id, fact.text) for fact in held]
        result = listen(agent.llm, text, today, [words for _, words in known])
        kept = fit_to_keep(result.heard, agent.guard)
        if not kept and is_explicit(text):
            # Asked outright to remember it: one miss of the listener or the guard (seen once in
            # the conversation evaluation, 2026-11-14) must not become "I didn't keep that".
            again = listen(agent.llm, text, today, [words for _, words in known])
            again.cost_usd += result.cost_usd
            result, kept = again, fit_to_keep(again.heard, agent.guard)
        # Something they volunteer ("I'm a student, I had projects") is worth a card at once; a
        # fact tucked into a question ("as a vegetarian, how much protein?") waits to be said twice.
        explicit = asked or is_explicit(text) or is_statement(text)
        with sessions() as db:
            question = db.get(ChatMessage, question_id)
            for heard in kept if question is not None else ():
                with suppress(memory.MemoryRejected):
                    fact = memory.propose_fact(
                        db,
                        user_id,
                        heard.kind,
                        heard.text,
                        explicit=explicit,
                        start=heard.start,
                        end=heard.end,
                        same_as=None if heard.same_as is None else known[heard.same_as][0],
                        replaces=None if heard.replaces is None else known[heard.replaces][0],
                        message_id=question_id,
                        now=now,
                    )
                    if fact is not None:
                        statuses.append(fact.status)
            if question is not None and question.conversation_id:
                store.charge_answer(db, user_id, question.conversation_id, result.cost_usd)
    except Exception:
        logger.exception("Listening to a message failed")
        return None
    return statuses


CHATTED = ("chatted", "chat_fallback")
MAX_PENDING = 5
CARD_NOTE = "I've put that on a card below: tap Keep and I'll bear it in mind from now on."
FORGETS = re.compile(
    r"^\s*(?:please\s+)?(?:forget|don'?t remember|stop remembering|ignore what i said)\b",
    re.IGNORECASE,
)
FORGET_NOTE = (
    "I've put the change on a card below: tap Keep and I'll stop using the old one. You can also "
    "remove anything I keep in Settings, under What Patterns knows."
)
NOT_KEPT = (
    "I didn't keep that. I keep things about you, like your routine, goals or plans: nothing "
    "medical, and nothing about how I should answer."
)
NOT_HEARD = "I couldn't note that just now. Could you tell me again in a moment?"
ALREADY_KEPT = "I already keep that in mind."


NOTHING_KEPT = "I don't keep anything about you yet, so there's nothing to forget."
NOT_KEPT_HERE = (
    "Okay, I won't keep anything from this message, and nothing else about you is kept. I can "
    "still use what you said here, in this chat."
)
NOT_KEPT_HERE_ASK = (
    "Okay, I won't keep anything from this message. If you also want something already kept "
    "removed, which one?"
)
FORGET_CARD = (
    "I've put it on a card below: tap Forget and I'll stop using \u201c{text}\u201d. Nothing is "
    "removed until you tap."
)
FORGET_WHICH = "Which of these should I forget? You can also remove any of them in Settings."
MAX_LISTED = 5


def forget_from(sessions: Sessions, agent: AgentParts, user_id, question_id, text, now) -> str:
    """ "Forget my old running goal": a card for the one kept fact it means, which their tap then
    deletes, or the kept facts to choose from when it is not clear which. Never a deletion here."""
    try:
        with sessions() as db:
            kept = [(fact.id, fact.text) for fact in memory.kept_facts(db, user_id)][:MAX_KNOWN]
        if not kept:
            return NOTHING_KEPT
        index, cost = which_kept(agent.llm, text, [words for _, words in kept])
        with sessions() as db:
            question = db.get(ChatMessage, question_id)
            if question is not None and question.conversation_id:
                store.charge_answer(db, user_id, question.conversation_id, cost)
            if index is None:
                listed = "\n".join(f"- {words}" for _, words in kept[:MAX_LISTED])
                return f"{FORGET_WHICH}\n{listed}"
            memory.propose_forget(db, user_id, kept[index][0], message_id=question_id, now=now)
        return FORGET_CARD.format(text=kept[index][1])
    except Exception:
        logger.exception("Preparing a forget card failed")
        return NOT_HEARD


def _on_day(moment: datetime, day, zone) -> datetime:
    """The same local clock time on another local day, in the account's named zone, as a UTC
    instant: adding days to a fixed offset moved a noon walk to 11:00 across a daylight-saving
    change. Durations are then added to the instant, never to the wall clock: 00:30 plus two
    hours on the night clocks go back is 01:30 local, two hours later, not 02:30."""
    local = moment.astimezone(zone)
    return datetime.combine(day, local.time().replace(tzinfo=None), tzinfo=zone).astimezone(UTC)


def _local(moment: datetime, zone) -> str:
    return moment.astimezone(zone).isoformat()


def card_fields(payload: dict, zone) -> dict:
    """The waiting card as the reader sees it: what a correction can be said against."""
    if payload.get("kind") == "workout":
        start = datetime.fromisoformat(payload["startTime"])
        end = datetime.fromisoformat(payload["endTime"])
        elapsed = (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() / 60
        active = payload["activeSeconds"] / 60
        local = start.astimezone(zone)
        return {
            "kind": "workout",
            "exercise": payload.get("exerciseType"),
            "day": f"{local.date().isoformat()} ({local:%a})",
            "start": f"{local:%H:%M}",
            "active_minutes": round(active, 1),
            "elapsed_minutes": round(elapsed, 1),
            "paused_minutes": round(elapsed - active, 1),
        }
    eaten = datetime.fromisoformat(payload["consumedAt"]).astimezone(zone)
    return {"kind": "food", "day": f"{eaten.date().isoformat()} ({eaten:%a})"}


def card_edit(prior: dict, typed: Request, zone) -> tuple[float | None, date | None]:
    """What a correction changes on the card, worked out against the card: a day said against
    it counts from its own local day, never from today ("a day later" became the day after the
    clock, the a196 audit); a duration the card already has is no change (a date-only edit
    came back with the elapsed 50 minutes, which turned a 12-minute pause into active time)."""
    fields = card_fields(prior, zone)
    day = typed.log_day
    if day is None and typed.card_day_offset is not None:
        day = date.fromisoformat(fields["day"][:10]) + timedelta(days=typed.card_day_offset)
    minutes = typed.duration_minutes
    held = ("active_minutes", "elapsed_minutes") if fields["kind"] == "workout" else ()
    if minutes is not None and any(abs(minutes - fields[k]) < 0.5 for k in held):
        minutes = None
    return minutes, day


def corrected_payload(prior: dict, minutes: float | None, day, zone) -> dict | None:
    """The waiting card with only what the correction states changed: a new duration keeps the
    start and ends that long after it; a new day keeps the local clock times and the elapsed
    time. None when it states neither, or when a paused workout makes "the duration" unclear
    (active time or elapsed)."""
    if minutes is None and day is None:
        return None
    payload = {
        k: v for k, v in prior.items() if k not in ("measured", "provenance", "estimateSource")
    }
    if prior.get("kind") == "workout":
        start = datetime.fromisoformat(prior["startTime"]).astimezone(UTC)
        end = datetime.fromisoformat(prior["endTime"]).astimezone(UTC)
        elapsed = end - start  # real time, as instants: a pause stays inside it
        if minutes is not None:
            if abs(elapsed.total_seconds() - prior["activeSeconds"]) > 1:
                return None
            elapsed = timedelta(minutes=minutes)
            payload["activeSeconds"] = round(minutes * 60)
        if day is not None:
            start = _on_day(start, day, zone)
        end = start + elapsed  # UTC arithmetic: the same elapsed time across a clock change
        return payload | {"startTime": _local(start, zone), "endTime": _local(end, zone)}
    if minutes is not None:
        return None  # a meal has no duration: the model's to read
    eaten = _on_day(datetime.fromisoformat(prior["consumedAt"]), day, zone)
    return payload | {"consumedAt": _local(eaten, zone)}


def noted_reply(statuses: list[str] | None) -> str:
    """What to say to "remember that …", from what listening recorded: never a card that isn't
    there (the memory evaluation found one promised when listening had failed)."""
    if statuses is None:
        return NOT_HEARD
    if "proposed" in statuses:
        return NOTED
    if "approved" in statuses:
        return ALREADY_KEPT
    return NOT_KEPT


def _answer(
    sessions: Sessions,
    agent: AgentParts,
    user_id,
    question_id,
    data: LoadedData,
    body: Question,
    attachment: Attachment | None,
    now: datetime,
    conversation_id: uuid.UUID | None = None,
) -> list[ChatMessage]:
    """Runs on a worker thread: answers, stores the answer, and frees the person for the next."""
    heard = False  # the message was answered, and is one that may say something about them
    today = now.astimezone(ZoneInfo(settings.timezone)).date()
    try:
        with sessions() as db:
            # The conversation's own turns and summary; memory is shared with the person's others.
            earlier = [
                m
                for m in store.history(db, user_id, HISTORY_USED, conversation_id)
                if m.id != question_id
            ]
            traces = db.scalars(
                select(AnswerTrace)
                .join(ChatMessage, AnswerTrace.message_id == ChatMessage.id)
                .where(ChatMessage.user_id == user_id, ChatMessage.id.in_([m.id for m in earlier]))
            )
            states = {
                row.message_id: step["state"]
                for row in traces
                for step in row.steps or []
                if step.get("type") == "request" and isinstance(step.get("state"), dict)
            }
            turns = turns_from(earlier, states)
            cited = store.load_evidence(db, user_id, {i for t in turns for i in t.evidence_ids})
            # Where the person is, from their device: the server's zone is not theirs.
            owner = db.get(User, user_id)
            zone = ZoneInfo(timezone_of(owner) if owner else settings.timezone)
            today = now.astimezone(zone).date()
            person = memory.profile(db, user_id, today, now)
            archive = memory.memory_items(db, user_id, now, conversation_id, with_faded=True)
            remembered = [
                item
                for item in memory.memory_items(db, user_id, now, conversation_id)
                if item.id not in person.fact_ids
            ]
            own = store.get_conversation(db, user_id, conversation_id) if conversation_id else None
            chat = ChatState(
                summary=own.summary if own else None,
                until=own.summary_until if own else None,
                waiting=tuple(store.waiting_cards(db, user_id, earlier)),
                profile=person.lines,
                kept=person.lines[: len(person.fact_ids)],  # one line per approved fact, first
                pending=tuple(
                    fact.text
                    for fact in memory.held_facts(db, user_id)
                    if fact.status == "proposed"
                )[:MAX_PENDING],
                interests=memory.interests(db, user_id, now),
            )
            food_logs = [
                row.payload
                for row in db.scalars(
                    select(HealthAction).where(
                        HealthAction.user_id == user_id,
                        HealthAction.kind == "food",
                        HealthAction.status == "succeeded",
                    )
                )
            ]
            checkins = [
                (row.day, row.rating, list(row.tags or []))
                for row in db.scalars(select(CheckIn).where(CheckIn.user_id == user_id))
            ]
        last = earlier[-1] if earlier and earlier[-1].role == "assistant" else None
        # Drafts from this chat's recent answers that still wait for the person's tap: "log it"
        # after a reply that made none still means the card above (2026-11-16).
        recent_ids = [
            i
            for message in earlier[-2 * WAITING_ANSWERS :]
            if message.role == "assistant"
            for i in message.action_ids or []
        ]
        waiting: list[HealthAction] = []
        action_states: list[str] = []  # for "has it been saved?", read from the store
        if recent_ids:
            with sessions() as db:
                rows = [
                    row
                    for i in recent_ids
                    if (row := db.get(HealthAction, uuid.UUID(i))) is not None
                    and row.user_id == user_id
                ]
                waiting = [row for row in rows if row.status == "draft"]
                action_states = [row.status for row in rows]
                db.expunge_all()
        # "Nah, I meant 100 g of each": the agent prepares the corrected draft, and the one it
        # replaces is cancelled, rather than asking them to edit the card (2026-11-16).
        # Interpret once, before preparing tools: corrections need the server's actual draft.
        started = monotonic()
        request_bundle = (
            interpret(
                agent.llm,
                body.text,
                turns,
                today,
                pending_draft=bool(waiting),
                draft=card_fields(waiting[-1].payload, zone) if len(waiting) == 1 else None,
            )
            if urgent_free(body.text)
            else (None, {}, Budget())
        )
        typed, request_state, reading_budget = request_bundle
        memory_denied = typed is not None and typed.memory == "deny"
        correcting = bool(waiting) and (
            typed.kind == "correction" if typed is not None else bool(CORRECTS.match(body.text))
        )
        if typed is not None and typed.kind == "correction" and len(waiting) != 1:
            typed = Request(kind="clarify", clarification="Which draft card should I change?")
            request_bundle = typed, request_state, reading_budget
            correcting = False
        continuing_log = None
        if last and last.pending_log_expert:
            created = (
                last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=UTC)
            )
            if timedelta(0) <= now - created <= timedelta(hours=24):
                continuing_log = last.pending_log_expert
        if correcting:
            continuing_log = "nutrition" if waiting[-1].kind == "food" else "activity"
        edit_minutes, edit_day = (
            card_edit(waiting[-1].payload, typed, zone)
            if correcting and typed is not None
            else (None, None)
        )
        # With the app's own scores as daily metrics, and the morning check-ins (rating and tags),
        # so they can be asked about and cited.
        frame = with_checkins(with_scores(data.daily.frame), checkins, CHECKIN_TAGS)
        # The agent gets the person's local time, so "just now" or "this morning" needs no
        # question; the data range is in the task separately.
        local_now = now.astimezone(zone)
        question = body.text
        thread = logging_thread(earlier) if continuing_log else []
        if thread:
            # A reply to the agent's logging question only makes sense with the request it
            # answers, so the agent gets all of it, not the bare reply.
            question = continued_request(thread, earlier[-1].text, body.text)
        if correcting:
            question = (
                f"Revise this pending draft with the person's correction. Preserve fields they "
                f"did not change. Draft (quoted data): {json.dumps(waiting[-1].payload)}\n"
                f"Their reply: {body.text}"
            )
        prepared: list[str] = []

        def search_past(query: str) -> list[dict]:
            with sessions() as db:
                return store.search_messages(db, user_id, query, conversation_id)

        def measurer(start: datetime, end: datetime, exercise_type: str) -> Measured:
            # Imported here: the actions routes import Google's, which import this module.
            from app.api.actions import measure_workout

            with sessions() as db:
                return measure_workout(db, user_id, start, end, exercise_type)

        described: list[str] = []
        outside = Outside(sessions, user_id, now, _day_start(now), food_data_for(agent.llm))
        # Present only with a food lookup to fill it: a draft with no values is then told to look
        # the food up rather than ask the person.
        estimates: list[str] | None = [] if outside.food_data else None
        draft_tools = proposal_tools(
            sessions,
            user_id,
            question_id,
            now,
            prepared,
            measurer,
            estimates,
            said=[*thread, body.text],
            local_now=local_now,
            described=described,
            required_duration_seconds=edit_minutes * 60 if edit_minutes is not None else None,
            required_day=edit_day if correcting else (typed.log_day if typed else None),
            prior_draft=waiting[-1].payload if correcting else None,
        )
        if outside.food_data:
            draft_tools["nutrition"] = [
                *draft_tools.get("nutrition", ()),
                food_tool(outside, estimates),
            ]
        reminders: list[str] = []
        listed: list[dict] = []
        reminding_tools = reminder_tools(
            sessions, user_id, now, reminders, said=[*thread, body.text], listed=listed
        )
        # A correction the reading fully states is applied to the stored card by code first,
        # through the same tool and checks, so no drafting model can touch the card after it
        # (both a196 date-only edits went wrong in the model's draft; given the intended edit,
        # the card's own values were kept).
        by_code = None
        if correcting and (edit_minutes is not None or edit_day is not None):
            payload = corrected_payload(waiting[-1].payload, edit_minutes, edit_day, zone)
            tools = draft_tools.get("activity" if waiting[-1].kind == "workout" else "nutrition")
            if payload is not None and tools:
                _, by_code = tools[0].run(payload)
        try:
            reply = ask(
                agent.llm,
                agent.router,
                frame,
                question,
                choice=body.expert,
                depth=Depth(body.depth),
                today=local_now,
                history=turns,
                stored_evidence=cited,
                attachment=attachment,
                guard=agent.guard,
                memory=remembered,
                now=local_now,
                action_tools=draft_tools,
                continuing_log=continuing_log,
                reminder_tools=reminding_tools,
                chat=chat,
                archive=archive,
                search_past=search_past,
                outside=outside,
                food_logs=food_logs,
                made_a_draft=lambda: bool(prepared),
                after_draft=bool(waiting) and not correcting,
                request_bundle=request_bundle,
                action_states=action_states,
                fixed_reply=(" ".join(described) or DRAFT_NOTE) if prepared else None,
            )
            if by_code is not None:
                reply.result.trace.append({"type": "correction_by_code", **by_code})
        except Exception:
            logger.exception("Answering failed")
            reply = None
        # A correction the model did not turn into a card: code makes it from the card's own
        # values and the new duration or day, through the same tool and checks. If that fails
        # too, the old card stays and the reply says so (a run's correction got "ask it another
        # way" and kept its old duration, the v5 audit).
        if reply is not None and correcting and not prepared and typed is not None:
            payload = corrected_payload(waiting[-1].payload, edit_minutes, edit_day, zone)
            tools = draft_tools.get("activity" if waiting[-1].kind == "workout" else "nutrition")
            if payload is not None and tools and by_code is None:
                _, step = tools[0].run(payload)
                reply.result.trace.append({"type": "correction_by_code", **step})
            if prepared:
                reply.result.summary = " ".join(described) or DRAFT_NOTE
            elif "?" in reply.result.summary and reply.result.summary != NO_ANSWER:
                reply.result.notes.append(STILL_WAITING)  # its question stands; the card too
            else:
                reply.result.summary, reply.result.claims = CORRECTION_FAILED, []
        # Any turn: the model's words may not claim a card or a write the store does not hold.
        # Checked before code adds its own notes ("I've put that on a card below" is a memory
        # card that is there).
        if (
            reply is not None
            and not prepared
            and reply.result.stop_reason not in FROM_CODE
            and (
                (not waiting and CLAIMS_A_DRAFT.search(reply.result.summary))
                or (
                    "succeeded" not in action_states
                    and (typed is None or typed.kind not in ("data", "causality", "investigate"))
                    and claims_false_success(reply.result.summary)
                )
            )
        ):
            reply.result.trace.append({"type": "unbacked_action_claim"})
            reply.result.summary, reply.result.claims = NOTHING_WAITING, []
        # "Remember that …" is heard now, not after: the reply says what actually happened.
        noted = reply is not None and reply.result.stop_reason == "noted"
        action = typed.memory_action if typed is not None else None
        if noted and action == "forget":
            # A change ("forget Mondays, it's Tuesdays now") is the listener's replacement card;
            # a plain "forget my old goal" is a card to forget that kept fact. "Don't save" stops
            # only the new fact, never the forget.
            changed = False
            if typed.states_new_fact and not memory_denied:
                outcome = listen_to(sessions, agent, user_id, question_id, body.text, today, now)
                changed = bool(outcome and "proposed" in outcome)
            said = (
                FORGET_NOTE
                if changed
                else forget_from(sessions, agent, user_id, question_id, body.text, now)
            )
            if memory_denied and (said == NOTHING_KEPT or said.startswith(FORGET_WHICH)):
                # "Just here in this chat, I like kayaking. Keep that out of my profile": a
                # statement not to keep, with nothing kept that it removes (the v5 audit said
                # "nothing to forget").
                said = (
                    NOT_KEPT_HERE
                    if said == NOTHING_KEPT
                    else f"{NOT_KEPT_HERE_ASK}\n{said.split(chr(10), 1)[-1]}"
                )
            reply.result.summary = said
        elif noted and not memory_denied:
            asked = action == "remember"
            outcome = listen_to(
                sessions, agent, user_id, question_id, body.text, today, now, asked=asked
            )
            reply.result.summary = noted_reply(outcome)
        # A read-only request ("remind me what I said", "is it saved?") gives no permission to
        # propose a fact from its own words: a readback became a preference card (the v5 audit).
        read_only = reply is not None and (
            reply.route.action == "conversation"
            or reply.result.stop_reason == "recalled"
            or (
                typed is not None
                and (
                    typed.kind in ("status", "confirmation", "correction", "clarify")
                    or (typed.kind == "memory" and typed.memory_action in ("recall", "forget"))
                )
            )
        )
        # Listening needs permission from the message itself: a statement about them or an explicit
        # request to remember, as read clause by clause. A pure question gives none, however
        # personal its words ("count the days my steps were 6000 or above" became a goal, the
        # v6 audit). An older flat reading, or none, keeps the earlier word rules.
        told = typed.told if typed is not None and typed.told is not None else True
        read_only = read_only or not told
        # Something they told us in passing: heard now too, so the reply can point to its card.
        chatted = reply is not None and reply.result.stop_reason in CHATTED
        # "That seems wrong, I walked more" disputes a figure; it says nothing lasting about them.
        # Only something they said about themselves; "delete all my data" or "who made you?"
        # raised a card once (2026-11-16).
        if (
            chatted
            and not memory_denied
            and not read_only
            and is_statement(body.text)
            and not certain_talk(body.text)
        ):
            outcome = listen_to(sessions, agent, user_id, question_id, body.text, today, now)
            if outcome and "proposed" in outcome:
                note = FORGET_NOTE if FORGETS.match(body.text) else CARD_NOTE
                reply.result.summary = f"{reply.result.summary}\n\n{note}"
        elapsed = monotonic() - started
        with sessions() as db:
            question = db.get(ChatMessage, question_id)
            if reply is None:
                answer = store.add_answer(
                    db,
                    user_id,
                    FAILED,
                    claims=[],
                    evidence=[],
                    answered_by=None,
                    routed=None,
                    consulted=[],
                    refused=False,
                    run_id=None,
                    conversation_id=conversation_id,
                )
                store.add_trace(db, failed_trace(elapsed), message_id=answer.id)
                return [question, answer]
            result = reply.result
            if correcting and prepared:
                for old in waiting:
                    if str(old.id) not in prepared:
                        health_store.cancel(db, user_id, old.id, old.version, now)
            if prepared:
                note = " ".join(described) or DRAFT_NOTE
                if reply.route.classification.intent == Intent.LOG or any(
                    step.get("continuing_log_expert") for step in result.trace
                ):
                    # The expert's own words when they are safe; the card holds the values.
                    result.summary, result.claims = note, []
                elif reply.route.expert == "nutrition" and not available(
                    EXPERTS["nutrition"], frame
                ):
                    result.summary = "No nutrition history is available yet. " + note
                else:
                    result.notes.append(note)
            elif (
                reply.route.classification.intent == Intent.LOG
                and result.stop_reason != "limits"  # a fixed reply ("tap Log it on the card")
                and result.summary != CORRECTION_FAILED  # code's, and already true
                and DRAFT_WITHOUT_ONE.search(result.summary)
                and "?" not in result.summary
            ):  # it says a card is waiting, and there is none
                result.summary = NO_DRAFT_REPLY

            reminding = any(step.get("reminding") for step in result.trace)
            if listed and result.summary == NO_ANSWER:  # the listing is code's, and so is this
                result.summary, result.claims = listing_reply(listed), []
            if reminders:
                # The agent's words when they do not claim it is on; the card holds the details.
                drafts = [db.get(Reminder, uuid.UUID(i)) for i in reminders]
                described = [
                    (r.title, describe(SCHEDULE.validate_python(r.schedule)))
                    for r in drafts
                    if r is not None
                ]
                alarm = bool(ALARM.search(body.text))
                result.summary = reminder_reply(result.summary, described, asked_alarm=alarm)
                result.claims = []
            refused = reply.route.action == "refuse"
            # "Remember my goal is 8,000 steps" can read as a reminder; it is still worth hearing.
            heard = (
                not memory_denied
                and not read_only
                and not noted
                and not chatted
                and not refused
                and (
                    reply.route.classification.intent not in QUIET_INTENTS or is_explicit(body.text)
                )
            )
            memory.mark_used(db, user_id, reply.context.memory_used, now)
            if not refused:
                asked_about = [c.metric for c in result.claims]
                memory.note_interest(
                    db,
                    user_id,
                    [attachment.metric if attachment else None, *asked_about],
                    "asked",
                    now,
                )
            answer = store.add_answer(
                db,
                user_id,
                answer_text(result.summary, [c.text for c in result.claims], result.notes),
                claims=[c.model_dump(mode="json") for c in result.all_claims],
                evidence=result.evidence.values(),
                answered_by=None if refused else result.expert,
                routed=None if refused else body.expert == "auto",
                consulted=list(result.consulted),
                refused=refused,
                run_id=result.run_id,
                cost_usd=result.budget.cost_usd,
                action_ids=prepared or None,
                reminder_ids=reminders or None,
                sources=result.sources or None,
                conversation_id=conversation_id,
                # The agent asked for a reminder's missing detail: the reply continues the request.
                pending_log_expert=REMINDERS
                if reminding and not reminders and not prepared
                else (reply.route.expert or "general")
                if not prepared
                and result.stop_reason != "limits"
                and (reply.route.expert in draft_tools or reply.route.action == "general")
                and (
                    reply.route.classification.intent == Intent.LOG
                    # Asking "log it, or ask about your data?" waits for the answer too.
                    or result.stop_reason == "clarification"
                    or (any(step.get("continuing_log_expert") for step in result.trace))
                )
                else None,
            )
            store.add_trace(
                db,
                personal_trace(result, elapsed, refused=refused),
                run_id=result.run_id,
                message_id=answer.id,
            )
            logger.info(
                "Answered run %s: %s, %d claims, $%.4f",
                result.run_id,
                result.stop_reason,
                len(result.claims),
                result.budget.cost_usd,
            )
            return [question, answer]
    finally:
        with _busy_lock:
            _busy.discard(user_id)
        with suppress(RuntimeError):  # the server is shutting down: this can wait or go unheard
            if agent.background and conversation_id:
                _pool.submit(update_summary, sessions, agent.llm, user_id, conversation_id)
            if agent.background and heard:
                _pool.submit(
                    listen_to, sessions, agent, user_id, question_id, body.text, today, now
                )


@router.get("/chat", response_model=list[schemas.ChatMessage], response_model_exclude_none=True)
def get_chat(
    db: Db,
    user: Annotated[User, Depends(approved_user)],
    conversation: uuid.UUID | None = None,
) -> list:
    """A conversation's messages; without `conversation`, the most recently used one."""
    chosen = (
        _owned(db, user, conversation) if conversation else store.latest_conversation(db, user.id)
    )
    if chosen is None:
        return []
    return [_message(m) for m in store.history(db, user.id, HISTORY_SHOWN, chosen.id)]


@router.get("/conversations", response_model=list[schemas.Conversation])
def list_conversations(db: Db, user: Annotated[User, Depends(approved_user)]) -> list:
    return [_conversation(row, count) for row, count in store.conversations(db, user.id)]


@router.post("/conversations", response_model=schemas.Conversation, status_code=201)
def create_conversation(
    db: Db, user: Annotated[User, Depends(approved_user)]
) -> schemas.Conversation:
    return _conversation(store.create_conversation(db, user.id), 0)


@router.patch("/conversations/{conversation_id}", response_model=schemas.Conversation)
def update_conversation(
    conversation_id: uuid.UUID,
    body: schemas.ConversationUpdate,
    db: Db,
    user: Annotated[User, Depends(approved_user)],
) -> schemas.Conversation:
    """Renames or pins a conversation; pinned ones are listed first."""
    conversation = _owned(db, user, conversation_id)
    if body.title is not None:
        conversation.title = store.title_from(body.title)
    if body.pinned is not None:
        if body.pinned and not conversation.pinned:  # a chat worth keeping says what matters
            said = store.history(db, user.id, HISTORY_FOLDED, conversation.id)
            topics = [c.get("metric") for message in said for c in message.claims or ()]
            memory.note_interest(db, user.id, topics, "pinned")
        conversation.pinned = body.pinned
    db.flush()
    count = next((n for row, n in store.conversations(db, user.id) if row.id == conversation.id), 0)
    return _conversation(conversation, count)


@router.put(
    "/chat/{message_id}/rating",
    response_model=schemas.ChatMessage,
    response_model_exclude_none=True,
)
def rate_answer(
    message_id: uuid.UUID,
    body: schemas.RatingIn,
    db: Db,
    user: Annotated[User, Depends(approved_user)],
) -> schemas.ChatMessage:
    """The person's thumbs up or down on one of their answers, counted in the pilot report."""
    rated = store.rate_answer(db, user.id, message_id, body.rating, datetime.now(UTC))
    if rated is None:
        raise ApiError(404, "not_found", "That answer is no longer in this chat.")
    return _message(rated)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: uuid.UUID, db: Db, user: Annotated[User, Depends(approved_user)]
) -> None:
    """Deletes the conversation, its messages and its episode; facts and findings stay."""
    conversation = _owned(db, user, conversation_id)
    if user.id in _busy:
        raise ApiError(409, "busy", "Still answering a question; try again in a moment.")
    store.forget_candidates(db, user.id, ChatMessage.conversation_id == conversation.id)
    db.execute(delete(ChatMessage).where(ChatMessage.conversation_id == conversation.id))
    db.execute(delete(MemoryEpisode).where(MemoryEpisode.conversation_id == conversation.id))
    db.delete(conversation)
    db.flush()


@router.post("/chat", response_model=list[schemas.ChatMessage], response_model_exclude_none=True)
def post_chat(
    body: Question,
    db: Db,
    user: Annotated[User, Depends(approved_user)],
    data: Annotated[LoadedData, Depends(get_data)],
    agent: Annotated[AgentParts, Depends(get_agent)],
    sessions: Annotated[Sessions, Depends(get_sessions)],
) -> list:
    now = datetime.now(UTC)
    check_caps(db, user, now)
    attachment = _attachment(data, body.attachment)
    if body.replaces:
        # An edited or retried question stays in its own conversation.
        replaced = db.get(ChatMessage, body.replaces)
        if replaced is None or replaced.user_id != user.id or replaced.role != "user":
            raise ApiError(404, "not_found", "That message is no longer in this chat.")
        if body.conversation_id and body.conversation_id != replaced.conversation_id:
            raise ApiError(422, "invalid_request", "That message is in another conversation.")
        conversation = _owned(db, user, replaced.conversation_id)
    else:
        conversation = (
            _owned(db, user, body.conversation_id)
            if body.conversation_id
            else store.latest_conversation(db, user.id) or store.create_conversation(db, user.id)
        )
    conversation_id = conversation.id
    db.commit()  # the answering thread opens its own sessions and must see the conversation
    with _busy_lock:
        if user.id in _busy:
            raise ApiError(409, "busy", "Still answering your last question.")
        _busy.add(user.id)
    try:
        # Stored before answering, so the question shows even if the answer comes later.
        with sessions() as own:
            # Only now, with no other answer running for this person, is anything removed.
            if body.replaces:
                store.replace_from(own, user.id, body.replaces)
            question = store.add_question(
                own,
                user.id,
                body.text.strip(),
                body.attachment.model_dump(exclude_none=True) if body.attachment else None,
                store.get_conversation(own, user.id, conversation_id),
            )
            question_id = question.id
        future = _pool.submit(
            _answer,
            sessions,
            agent,
            user.id,
            question_id,
            data,
            body,
            attachment,
            now,
            conversation_id,
        )
    except BaseException:
        with _busy_lock:
            _busy.discard(user.id)
        raise
    try:
        rows = future.result(timeout=settings.chat_wait_s)
    except WaitTimeout:
        raise ApiError(
            504,
            "still_answering",
            "This is taking longer than usual. The answer will appear here when it is ready.",
        ) from None
    return [_message(row) for row in rows]
