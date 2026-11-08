"""The Ask screen's conversation: `GET /chat` and `POST /chat`.

A question is answered by `ask()` with the person's own data, conversation and memory. The request
waits for the answer up to `settings.chat_wait_s`; a slower answer keeps running and is stored when
it is done, so the app finds it when it reloads the chat. One question at a time per person.

Spending: every answer's cost is stored, and a question is refused before any model runs once the
person, or the whole app, has reached its daily cap. The caps count local days.
"""

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as WaitTimeout
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.actions.schemas import Measured
from app.actions.tools import proposal_tools
from app.agent.ask import REMINDERS, ask, default_guard, default_router
from app.agent.context import Attachment, ChatState, turns_from
from app.agent.conversation import DRAFT_NOTE
from app.agent.experts import EXPERTS, Depth, available
from app.agent.guard import Guard
from app.agent.intent import Intent
from app.agent.listener import MAX_KNOWN, fit_to_keep, is_explicit, listen, worth_listening
from app.agent.llm import LLM, LLMError, OpenAILLM
from app.agent.router import Router
from app.agent.summary import FOLD_AT, fold, to_fold
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
    ChatMessage,
    CheckIn,
    Conversation,
    MemoryEpisode,
    User,
)
from app.db.session import session_scope
from app.outside import FoodData, Outside
from app.reminders.store import timezone_of
from app.reminders.tools import reminder_reply, reminder_tools

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

HISTORY_SHOWN = 100  # messages the app gets back
HISTORY_USED = 20  # messages the agent sees as context; the context builder trims further
HISTORY_FOLDED = 40  # messages looked at for the running summary
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
        evidence_ids=list(row.evidence_ids or []),
        action_ids=list(row.action_ids or []) or None,
        reminder_ids=list(row.reminder_ids or []) or None,
        attachment=row.attachment,
        answered_by=row.answered_by if row.role == "assistant" else None,
        routed=row.routed if row.role == "assistant" else None,
        consulted=list(row.consulted or []) or None,
        refused=row.refused or None,
        conversation_id=str(row.conversation_id) if row.conversation_id else None,
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
    query = select(func.coalesce(func.sum(ChatMessage.cost_usd), 0.0)).where(
        ChatMessage.created_at >= since
    )
    if user is not None:
        query = query.where(ChatMessage.user_id == user.id)
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
) -> None:
    """Hears what the person's message says about them, after the answer; nothing is kept without
    their tap (`app.db.memory.propose_fact`)."""
    if not worth_listening(text):
        return
    try:
        with sessions() as db:
            held = memory.held_facts(db, user_id)[:MAX_KNOWN]
            known = [(fact.id, fact.text) for fact in held]
        result = listen(agent.llm, text, today, [words for _, words in known])
        kept = fit_to_keep(result.heard, agent.guard)
        explicit = is_explicit(text)
        with sessions() as db:
            question = db.get(ChatMessage, question_id)
            for heard in kept if question is not None else ():
                with suppress(memory.MemoryRejected):
                    memory.propose_fact(
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
            if question is not None and question.conversation_id:
                store.charge_answer(db, user_id, question.conversation_id, result.cost_usd)
    except Exception:
        logger.exception("Listening to a message failed")


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
            turns = turns_from(earlier)
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
                interests=memory.interests(db, user_id, now),
            )
            checkins = [
                (row.day, row.rating, list(row.tags or []))
                for row in db.scalars(select(CheckIn).where(CheckIn.user_id == user_id))
            ]
        last = earlier[-1] if earlier and earlier[-1].role == "assistant" else None
        continuing_log = None
        if last and last.pending_log_expert:
            created = (
                last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=UTC)
            )
            if timedelta(0) <= now - created <= timedelta(hours=24):
                continuing_log = last.pending_log_expert
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
        prepared: list[str] = []

        def search_past(query: str) -> list[dict]:
            with sessions() as db:
                return store.search_messages(db, user_id, query, conversation_id)

        def measurer(start: datetime, end: datetime, exercise_type: str) -> Measured:
            # Imported here: the actions routes import Google's, which import this module.
            from app.api.actions import measure_workout

            with sessions() as db:
                return measure_workout(db, user_id, start, end, exercise_type)

        estimates: list[str] = []
        described: list[str] = []
        outside = Outside(sessions, user_id, now, _day_start(now), food_data())
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
        )
        if outside.food_data:
            draft_tools["nutrition"] = [
                *draft_tools.get("nutrition", ()),
                food_tool(outside, estimates),
            ]
        reminders: list[str] = []
        reminding_tools = reminder_tools(
            sessions, user_id, now, reminders, said=[*thread, body.text]
        )
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
                now=now,
                action_tools=draft_tools,
                continuing_log=continuing_log,
                reminder_tools=reminding_tools,
                chat=chat,
                archive=archive,
                search_past=search_past,
                outside=outside,
            )
        except Exception:
            logger.exception("Answering failed")
            reply = None
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
                return [question, answer]
            result = reply.result
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
            reminding = any(step.get("reminding") for step in result.trace)
            if reminders:
                # The agent's words when they do not claim it is on; the card holds the details.
                result.summary, result.claims = reminder_reply(result.summary), []
            refused = reply.route.action == "refuse"
            heard = not refused and reply.route.classification.intent not in QUIET_INTENTS
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
                claims=[c.model_dump(mode="json") for c in result.claims],
                evidence=result.evidence.values(),
                answered_by=None if refused else result.expert,
                routed=None if refused else body.expert == "auto",
                consulted=list(result.consulted),
                refused=refused,
                run_id=result.run_id,
                cost_usd=result.budget.cost_usd,
                action_ids=prepared or None,
                reminder_ids=reminders or None,
                conversation_id=conversation_id,
                # The agent asked for a reminder's missing detail: the reply continues the request.
                pending_log_expert=REMINDERS
                if reminding
                and not reminders
                and not prepared
                and result.summary.rstrip().endswith("?")
                else (reply.route.expert or "general")
                if not prepared
                and (reply.route.expert in draft_tools or reply.route.action == "general")
                and (
                    reply.route.classification.intent == Intent.LOG
                    # Asking "log it, or ask about your data?" waits for the answer too.
                    or result.stop_reason == "clarification"
                    or (any(step.get("continuing_log_expert") for step in result.trace))
                )
                else None,
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
