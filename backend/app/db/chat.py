"""Storing and reading a person's conversations and the evidence their answers cite.

A person has any number of conversations; memory (facts, findings, answers) is the person's and
shared by all of them. A turn is stored only after it is complete: the question, then the answer
with its verified claims and the evidence they cite. Every query filters on the user.
"""

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.agent.sanitize import clean, reads_like_instruction, stems
from app.analysis.evidence import Evidence
from app.db.models import (
    AnswerTrace,
    ChatMessage,
    Conversation,
    EvidenceRecord,
    HealthAction,
    MemoryFact,
    Reminder,
    Spend,
)

NEW_TITLE = "New chat"
SEARCHED_MESSAGES = 500
SEARCH_FOUND = 5
SEARCH_TEXT_CHARS = 240
TITLE_LENGTH = 60


def title_from(question: str) -> str:
    """A conversation's name from its first question: one line, at most TITLE_LENGTH characters."""
    text = " ".join(question.split()) or NEW_TITLE
    return text if len(text) <= TITLE_LENGTH else text[: TITLE_LENGTH - 1].rstrip() + "…"


def create_conversation(
    session: Session, user_id: uuid.UUID, title: str = NEW_TITLE
) -> Conversation:
    conversation = Conversation(user_id=user_id, title=title)
    session.add(conversation)
    session.flush()
    return conversation


def get_conversation(
    session: Session, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation | None:
    return session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )


def latest_conversation(session: Session, user_id: uuid.UUID) -> Conversation | None:
    return session.scalar(
        select(Conversation)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )


def conversations(session: Session, user_id: uuid.UUID) -> list[tuple[Conversation, int]]:
    """The person's conversations, most recently used first, each with its number of messages."""
    counts = (
        select(ChatMessage.conversation_id, func.count().label("messages"))
        .where(ChatMessage.user_id == user_id)
        .group_by(ChatMessage.conversation_id)
        .subquery()
    )
    rows = session.execute(
        select(Conversation, func.coalesce(counts.c.messages, 0))
        .outerjoin(counts, counts.c.conversation_id == Conversation.id)
        .where(Conversation.user_id == user_id)
        .order_by(Conversation.pinned.desc(), Conversation.updated_at.desc())
    )
    return [(conversation, count) for conversation, count in rows]


def replace_from(
    session: Session, user_id: uuid.UUID, message_id: uuid.UUID
) -> Conversation | None:
    """Removes one of the person's questions and everything after it in its conversation, so an
    edited or retried question is answered afresh; returns the conversation, or None when the
    message is not their question."""
    message = session.scalar(
        select(ChatMessage).where(
            ChatMessage.id == message_id,
            ChatMessage.user_id == user_id,
            ChatMessage.role == "user",
        )
    )
    if message is None or message.conversation_id is None:
        return None
    conversation = get_conversation(session, user_id, message.conversation_id)
    reached = conversation.summary_until if conversation else None
    if reached and message.created_at <= reached:
        # It speaks of messages that are going: the turns left are folded again.
        conversation.summary = conversation.summary_until = None
    going = (
        ChatMessage.user_id == user_id,
        ChatMessage.conversation_id == message.conversation_id,
        ChatMessage.created_at >= message.created_at,
    )
    forget_candidates(session, user_id, *going)
    session.execute(delete(ChatMessage).where(*going))
    return conversation


def forget_candidates(session: Session, user_id: uuid.UUID, *messages) -> None:
    """What was only heard in these messages goes with them; what the person saw stays theirs."""
    session.execute(
        delete(MemoryFact).where(
            MemoryFact.user_id == user_id,
            MemoryFact.status == "candidate",
            MemoryFact.source_message_id.in_(select(ChatMessage.id).where(*messages)),
        )
    )


def add_question(
    session: Session,
    user_id: uuid.UUID,
    text: str,
    attachment: dict | None = None,
    conversation: Conversation | None = None,
) -> ChatMessage:
    message = ChatMessage(
        user_id=user_id,
        role="user",
        text=text,
        attachment=attachment,
        conversation_id=conversation.id if conversation else None,
    )
    session.add(message)
    if conversation is not None:
        if conversation.title == NEW_TITLE:
            conversation.title = title_from(text)
        conversation.updated_at = datetime.now(UTC)
    session.flush()
    return message


def add_answer(
    session: Session,
    user_id: uuid.UUID,
    text: str,
    *,
    claims: list[dict],
    evidence: Iterable[Evidence],
    answered_by: str | None,
    routed: bool | None,
    consulted: list[str],
    refused: bool,
    run_id: str | None,
    cost_usd: float | None = None,
    action_ids: list[str] | None = None,
    pending_log_expert: str | None = None,
    conversation_id: uuid.UUID | None = None,
    reminder_ids: list[str] | None = None,
    sources: list[dict] | None = None,
) -> ChatMessage:
    """Stores an answer, its verified claims, and the evidence they cite (once per id)."""
    cited = {i for claim in claims for i in claim.get("evidence_ids", [])}
    store_evidence(session, user_id, run_id, evidence, cited)
    message = ChatMessage(
        user_id=user_id,
        role="assistant",
        text=text,
        claims=claims,
        sources=sources,
        evidence_ids=sorted(cited),
        answered_by=answered_by,
        routed=routed,
        consulted=consulted,
        refused=refused,
        run_id=run_id,
        cost_usd=cost_usd,
        action_ids=action_ids,
        reminder_ids=reminder_ids,
        pending_log_expert=pending_log_expert,
        conversation_id=conversation_id,
    )
    session.add(message)
    if cost_usd:
        session.add(Spend(user_id=user_id, kind="answer", cost_usd=cost_usd))
    session.flush()
    return message


def store_evidence(
    session: Session,
    user_id: uuid.UUID,
    run_id: str | None,
    evidence: Iterable[Evidence],
    cited: set[str],
) -> None:
    """Stores the cited evidence, once per id; raises `ValueError` if any of it was not given."""
    records = [e for e in evidence if e.id in cited]
    if missing := cited - {e.id for e in records}:
        raise ValueError(f"claims cite evidence that was not given: {', '.join(sorted(missing))}")
    if not records:
        return
    stored = set(
        session.scalars(
            select(EvidenceRecord.id).where(
                EvidenceRecord.user_id == user_id, EvidenceRecord.id.in_(cited)
            )
        )
    )
    session.add_all(
        EvidenceRecord(
            user_id=user_id,
            id=e.id,
            run_id=run_id,
            tool=e.tool,
            payload=e.model_dump(mode="json"),
        )
        for e in records
        if e.id not in stored
    )


def history(
    session: Session,
    user_id: uuid.UUID,
    limit: int | None = None,
    conversation_id: uuid.UUID | None = None,
) -> list[ChatMessage]:
    """A conversation, oldest first (every message without `conversation_id`); with `limit`, only
    the latest messages."""
    query = select(ChatMessage).where(ChatMessage.user_id == user_id)
    if conversation_id is not None:
        query = query.where(ChatMessage.conversation_id == conversation_id)
    query = (
        query
        # Newest first for the limit; on a tie the answer sorts first, so reversed the question
        # comes before its answer.
        .order_by(ChatMessage.created_at.desc(), ChatMessage.role.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    return list(reversed(session.scalars(query).all()))


def charge_answer(
    session: Session, user_id: uuid.UUID, conversation_id: uuid.UUID, cost_usd: float
) -> None:
    """Adds background work on a chat to its latest answer, so the daily caps count it."""
    answer = session.scalar(
        select(ChatMessage)
        .where(
            ChatMessage.user_id == user_id,
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.role == "assistant",
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    if answer is not None:
        answer.cost_usd = (answer.cost_usd or 0.0) + cost_usd
    if cost_usd:
        session.add(Spend(user_id=user_id, kind="background", cost_usd=cost_usd))


def save_summary(
    session: Session,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    summary: str,
    until: datetime,
    seen: datetime | None,
) -> bool:
    """Stores a new summary, unless the chat moved on while it was written: another fold landed
    (`seen` is no longer current), or the turns it reaches were edited away."""
    conversation = get_conversation(session, user_id, conversation_id)
    if conversation is None or conversation.summary_until != seen:
        return False
    reached = session.scalar(
        select(ChatMessage.id).where(
            ChatMessage.conversation_id == conversation_id,
            ChatMessage.role == "assistant",
            ChatMessage.created_at == until,
        )
    )
    if reached is None:
        return False
    conversation.summary, conversation.summary_until = summary or None, until
    return True


def waiting_cards(
    session: Session, user_id: uuid.UUID, messages: Iterable[ChatMessage]
) -> list[str]:
    """What these messages prepared that still waits for the person's tap, in plain words."""
    action_ids, reminder_ids = set(), set()
    for message in messages:
        action_ids |= {uuid.UUID(str(i)) for i in message.action_ids or ()}
        reminder_ids |= {uuid.UUID(str(i)) for i in message.reminder_ids or ()}
    waiting = []
    if action_ids:
        kinds = session.scalars(
            select(HealthAction.kind).where(
                HealthAction.user_id == user_id,
                HealthAction.id.in_(action_ids),
                HealthAction.status == "draft",
            )
        )
        waiting += [f"A {kind} log draft has not been confirmed yet." for kind in kinds]
    if reminder_ids:
        titles = session.scalars(
            select(Reminder.title).where(
                Reminder.user_id == user_id,
                Reminder.id.in_(reminder_ids),
                Reminder.status == "proposed",
            )
        )
        waiting += [f"The reminder “{title}” has not been confirmed yet." for title in titles]
    return waiting


def search_messages(
    session: Session,
    user_id: uuid.UUID,
    query: str,
    not_in: uuid.UUID | None = None,
    limit: int = SEARCH_FOUND,
) -> list[dict]:
    """What was said in the person's other chats that shares words with `query`, best first: only
    their latest messages, without refusals or anything that reads like an instruction."""
    words = stems(query)
    if not words:
        return []
    where = [ChatMessage.user_id == user_id]
    if not_in is not None:
        where.append(ChatMessage.conversation_id != not_in)
    rows = session.execute(
        select(ChatMessage, Conversation.title)
        .join(Conversation, Conversation.id == ChatMessage.conversation_id)
        .where(*where)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.role.asc())
        .limit(SEARCHED_MESSAGES)
    ).all()
    scored = []
    refused_in: set[uuid.UUID] = set()  # newest first: a refusal comes just before its question
    for message, title in rows:
        if message.refused:
            refused_in.add(message.conversation_id)
            continue
        if message.role == "user" and message.conversation_id in refused_in:
            refused_in.discard(message.conversation_id)
            continue
        shared = len(words & stems(message.text))
        unsafe = reads_like_instruction(message.text) or reads_like_instruction(title)
        if shared and not unsafe:
            scored.append((shared, message, title))
    scored.sort(key=lambda found: found[0], reverse=True)  # stable: newest first among equals
    return [
        {
            "date": message.created_at.date().isoformat(),
            "chat": title,
            "who": "person" if message.role == "user" else "assistant",
            "text": clean(message.text, SEARCH_TEXT_CHARS),
        }
        for _, message, title in scored[:limit]
    ]


def load_evidence(session: Session, user_id: uuid.UUID, ids: Iterable[str]) -> dict[str, Evidence]:
    """The stored evidence with these ids that belongs to this user; others are left out."""
    wanted = set(ids)
    if not wanted:
        return {}
    rows = session.scalars(
        select(EvidenceRecord).where(
            EvidenceRecord.user_id == user_id, EvidenceRecord.id.in_(wanted)
        )
    )
    return {row.id: Evidence.model_validate(row.payload) for row in rows}


def add_trace(
    session: Session,
    record: dict,
    *,
    run_id: str | None = None,
    message_id: uuid.UUID | None = None,
    team_message_id: uuid.UUID | None = None,
) -> AnswerTrace:
    """Stores how one answer was reached (`app.agent.trace`), next to the answer it belongs to."""
    fields = {k: v for k, v in record.items() if k in TRACE_FIELDS}
    trace = AnswerTrace(
        message_id=message_id, team_message_id=team_message_id, run_id=run_id, **fields
    )
    session.add(trace)
    session.flush()
    return trace


TRACE_FIELDS = {
    "outcome",
    "stop_reason",
    "question_type",
    "latency_ms",
    "stages_ms",
    "model_calls",
    "tool_calls",
    "tool_errors",
    "repair_rounds",
    "rejected_claims",
    "summary_fell_back",
    "guard_down",
    "cost_usd",
    "steps",
}


def rate_answer(
    session: Session, user_id: uuid.UUID, message_id: uuid.UUID, rating: str | None, now: datetime
) -> ChatMessage | None:
    """Sets or clears the person's thumbs on one of their own answers; None if it is not one."""
    message = session.get(ChatMessage, message_id)
    if message is None or message.user_id != user_id or message.role != "assistant":
        return None
    message.rating, message.rated_at = rating, now if rating else None
    session.flush()
    return message
