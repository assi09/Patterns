"""The memory write path: what may be stored, by whom, and for how long (docs/architecture.md).

- **Findings** come only from verified claims of investigation runs; a newer finding on the same
  metric supersedes the older one.
- **Context questions** are written by code from a template and a fixed menu of options; the
  person's answer must be one of them. A metric and period once asked about is not asked again,
  and questions stop for a while after the person dismisses two.
- **Check-ins** are the person's: a rating from 1 to 5 and tags from a fixed list, for today only.
- **Facts** are proposed by the agent and kept only once the person approves; text that reads like
  an instruction is refused, and a fact the person declined is not proposed again.
- **Episodes** are how one chat reaches the others: when a chat goes idle, code writes one dated
  line from its verified claims. Nothing else from a chat crosses over.

Every function takes the user, and every query filters on it. Rejected writes raise
`MemoryRejected`, whose message is safe to show.
"""

import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.agent.context import MemoryItem
from app.agent.facts import FactRejected, validate_fact
from app.agent.present import METRICS, label, short_date
from app.analysis.evidence import Evidence
from app.db.chat import load_evidence, store_evidence
from app.db.models import (
    CHECKIN_TAGS,
    CONTEXT_OPTIONS,
    ChatMessage,
    CheckIn,
    ContextQuestion,
    Conversation,
    Finding,
    MemoryEpisode,
    MemoryFact,
)

FINDING_KINDS = ("change", "association")
FINDING_DAYS = 90
ANSWER_DAYS = 180
CHECKIN_DAYS = 365
FACT_UNUSED_DAYS = 60  # approved facts unused this long are no longer retrieved
EPISODE_DAYS = 90
EPISODE_IDLE = timedelta(hours=1)  # a chat unused this long is consolidated
EPISODE_CLAIMS = 2
MAX_EPISODE_CHARS = 300
# Which of a chat's claims are worth keeping, best first; `day` and data-quality notes are not.
EPISODE_KINDS = ("change", "association", "suggestion", "no_change")
# After this many dismissals within the window, no new question for a while.
BACKOFF_DISMISSALS, BACKOFF_WINDOW_DAYS, BACKOFF_QUIET_DAYS = 2, 30, 14
DECLINED = "rather_not_say"  # an answer, but counted like a dismissal
PROMPT = "Something changed in your {metric} around {day}. Was anything going on then?"


class MemoryRejected(ValueError):
    """A write the memory rules do not allow; the message is safe to show."""


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime) -> datetime:
    """SQLite returns naive datetimes; they are stored in UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


# Findings


def save_findings(
    session: Session,
    user_id: uuid.UUID,
    run_id: str,
    claims: Iterable[dict],
    evidence: dict[str, Evidence],
    now: datetime | None = None,
) -> list[Finding]:
    """Stores a run's verified change and association claims as findings, with their evidence."""
    now = now or _now()
    saved: list[Finding] = []
    for claim in claims:
        if claim.get("kind") not in FINDING_KINDS or not claim.get("metric"):
            continue
        ids = list(claim.get("evidence_ids", []))
        if missing := [i for i in ids if i not in evidence]:
            raise MemoryRejected(f"A finding cites evidence that was not given: {missing}.")
        cited = [evidence[i] for i in ids]
        windows = [w for e in cited for w in e.windows]
        effects = [
            abs(v)
            for e in cited
            for v in (e.stats.get("cliffs_delta"), e.stats.get("rho"))
            if isinstance(v, int | float)
        ]
        metric = claim["metric"]
        session.execute(
            update(Finding)
            .where(
                Finding.user_id == user_id,
                Finding.metric == metric,
                Finding.superseded_at.is_(None),
                Finding.run_id != run_id,
            )
            .values(superseded_at=now)
        )
        finding = Finding(
            user_id=user_id,
            run_id=run_id,
            metric=metric,
            kind=claim["kind"],
            direction=claim.get("direction"),
            text=claim["text"],
            evidence_ids=ids,
            window_start=min(w.start for w in windows),
            window_end=max(w.end for w in windows),
            effect=max(effects) if effects else None,
            created_at=now,
        )
        session.add(finding)
        saved.append(finding)
        store_evidence(session, user_id, run_id, cited, set(ids))
    session.flush()
    return saved


def current_findings(
    session: Session, user_id: uuid.UUID, now: datetime | None = None
) -> list[Finding]:
    """Findings not superseded and younger than 90 days, newest first."""
    since = (now or _now()) - timedelta(days=FINDING_DAYS)
    query = (
        select(Finding)
        .where(
            Finding.user_id == user_id,
            Finding.superseded_at.is_(None),
            Finding.created_at >= since,
        )
        .order_by(Finding.created_at.desc())
    )
    return list(session.scalars(query))


# Context questions


def ask_question(
    session: Session,
    user_id: uuid.UUID,
    metric: str,
    start: date,
    end: date,
    *,
    run_id: str | None = None,
    now: datetime | None = None,
) -> ContextQuestion | None:
    """Asks about a change, unless it was asked before or the person has been dismissing them."""
    if metric not in METRICS:
        raise MemoryRejected(f"Unknown metric {metric!r}.")
    now = now or _now()
    earlier = list(
        session.scalars(select(ContextQuestion).where(ContextQuestion.user_id == user_id))
    )
    if any(q.metric == metric and q.window_start <= end and start <= q.window_end for q in earlier):
        return None  # never the same thing twice
    recent = now - timedelta(days=BACKOFF_WINDOW_DAYS)
    declined = [q for q in earlier if _declined(q) and _aware(q.answered_at) >= recent]
    if len(declined) >= BACKOFF_DISMISSALS and now - max(
        _aware(q.answered_at) for q in declined
    ) < timedelta(days=BACKOFF_QUIET_DAYS):
        return None
    question = ContextQuestion(
        user_id=user_id,
        run_id=run_id,
        metric=metric,
        prompt=PROMPT.format(metric=label(metric), day=short_date(start)),
        window_start=start,
        window_end=end,
        options=list(CONTEXT_OPTIONS),
        asked_at=now,
    )
    session.add(question)
    session.flush()
    return question


def _declined(question: ContextQuestion) -> bool:
    return question.answered_at is not None and (
        question.status == "dismissed" or question.answer == DECLINED
    )


def answer_question(
    session: Session,
    user_id: uuid.UUID,
    question_id: uuid.UUID,
    answer: str | None,
    now: datetime | None = None,
) -> ContextQuestion:
    """Records the person's choice; None means they skipped the question."""
    question = session.scalar(
        select(ContextQuestion).where(
            ContextQuestion.user_id == user_id, ContextQuestion.id == question_id
        )
    )
    if question is None:
        raise MemoryRejected("There is no such question.")
    if question.status != "asked":
        raise MemoryRejected("This question was already answered.")
    if answer is not None and answer not in question.options:
        raise MemoryRejected(f"Choose one of: {', '.join(question.options)}.")
    question.status = "dismissed" if answer is None else "answered"
    question.answer = answer
    question.answered_at = now or _now()
    session.flush()
    return question


# Check-ins


def save_checkin(
    session: Session,
    user_id: uuid.UUID,
    day: date,
    rating: int,
    tags: Iterable[str] = (),
    *,
    today: date,
) -> CheckIn:
    """Sets or changes today's check-in."""
    if day != today:
        raise MemoryRejected("Only today's check-in can be set or changed.")
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        raise MemoryRejected("The rating is a whole number from 1 to 5.")
    chosen = list(dict.fromkeys(tags))
    if unknown := [t for t in chosen if t not in CHECKIN_TAGS]:
        raise MemoryRejected(f"Unknown tags: {', '.join(unknown)}.")
    checkin = session.get(CheckIn, (user_id, day))
    if checkin is None:
        checkin = CheckIn(user_id=user_id, day=day, rating=rating, tags=chosen)
        session.add(checkin)
    else:
        checkin.rating, checkin.tags = rating, chosen
    session.flush()
    return checkin


def checkins(session: Session, user_id: uuid.UUID, start: date, end: date) -> list[CheckIn]:
    """Check-ins from `start` to `end` inclusive, oldest first."""
    query = (
        select(CheckIn)
        .where(CheckIn.user_id == user_id, CheckIn.day >= start, CheckIn.day <= end)
        .order_by(CheckIn.day)
    )
    return list(session.scalars(query))


# Facts


def _normalized(text: str) -> str:
    return " ".join(text.casefold().split())


def propose_fact(
    session: Session,
    user_id: uuid.UUID,
    kind: str,
    text: str,
    metrics: Iterable[str] = (),
    *,
    run_id: str | None = None,
) -> MemoryFact | None:
    """Stores the agent's proposal for the person to approve; None if they declined it before."""
    try:
        cleaned, concerned = validate_fact(kind, text, metrics)
    except FactRejected as exc:
        raise MemoryRejected(str(exc)) from exc
    same = [
        fact
        for fact in session.scalars(select(MemoryFact).where(MemoryFact.user_id == user_id))
        if _normalized(fact.text) == _normalized(cleaned)
    ]
    if any(fact.status == "declined" for fact in same):
        return None  # the person said no; do not ask again
    if same:
        return same[0]
    fact = MemoryFact(
        user_id=user_id, kind=kind, text=cleaned, metrics=concerned, source_run_id=run_id
    )
    session.add(fact)
    session.flush()
    return fact


def decide_fact(
    session: Session,
    user_id: uuid.UUID,
    fact_id: uuid.UUID,
    approve: bool,
    now: datetime | None = None,
) -> MemoryFact:
    fact = _fact(session, user_id, fact_id)
    if fact.status != "proposed":
        raise MemoryRejected("This fact was already decided.")
    fact.status = "approved" if approve else "declined"
    fact.decided_at = now or _now()
    session.flush()
    return fact


def delete_fact(session: Session, user_id: uuid.UUID, fact_id: uuid.UUID) -> None:
    session.delete(_fact(session, user_id, fact_id))
    session.flush()


def _fact(session: Session, user_id: uuid.UUID, fact_id: uuid.UUID) -> MemoryFact:
    fact = session.scalar(
        select(MemoryFact).where(MemoryFact.user_id == user_id, MemoryFact.id == fact_id)
    )
    if fact is None:
        raise MemoryRejected("There is no such fact.")
    return fact


# Lifetimes


def expire(session: Session, user_id: uuid.UUID, now: datetime | None = None) -> dict[str, int]:
    """Deletes what has outlived its lifetime; returns how many rows of each kind went."""
    now = now or _now()
    removed = {}
    for name, table, column, days in (
        ("findings", Finding, Finding.created_at, FINDING_DAYS),
        ("context_questions", ContextQuestion, ContextQuestion.asked_at, ANSWER_DAYS),
        ("episodes", MemoryEpisode, MemoryEpisode.through, EPISODE_DAYS),
    ):
        result = session.execute(
            delete(table).where(table.user_id == user_id, column < now - timedelta(days=days))
        )
        removed[name] = result.rowcount
    cutoff = now.date() - timedelta(days=CHECKIN_DAYS)
    result = session.execute(
        delete(CheckIn).where(CheckIn.user_id == user_id, CheckIn.day < cutoff)
    )
    removed["checkins"] = result.rowcount
    return removed


# Retrieval: rows as the context builder ranks them

OPTION_TEXT = {
    "travel": "travel",
    "work_or_exam_schedule": "their work or exam schedule",
    "more_training": "more training",
    "less_training": "less training",
    "illness": "being ill",
    "new_device": "a new device",
    "other": "something else",
}


def memory_items(
    session: Session,
    user_id: uuid.UUID,
    now: datetime | None = None,
    conversation_id: uuid.UUID | None = None,
) -> list[MemoryItem]:
    """This person's memory that may still be retrieved: current findings with their evidence,
    answers from the last 180 days (not "rather not say"), approved facts used or decided in the
    last 60 days, and the episodes of their chats other than `conversation_id`, the one being
    answered, whose own turns it already has."""
    now = now or _now()
    items: list[MemoryItem] = []
    findings = current_findings(session, user_id, now)
    evidence = load_evidence(session, user_id, {i for f in findings for i in f.evidence_ids})
    for finding in findings:
        items.append(
            MemoryItem(
                kind="finding",
                id=str(finding.id),
                text=finding.text,
                metrics=(finding.metric,),
                created=_aware(finding.created_at),
                importance=finding.effect or 0.0,
                start=finding.window_start,
                end=finding.window_end,
                evidence=tuple(evidence[i] for i in finding.evidence_ids if i in evidence),
            )
        )
    answered = session.scalars(
        select(ContextQuestion).where(
            ContextQuestion.user_id == user_id,
            ContextQuestion.status == "answered",
            ContextQuestion.asked_at >= now - timedelta(days=ANSWER_DAYS),
        )
    )
    for question in answered:
        if question.answer not in OPTION_TEXT:
            continue  # "rather not say" tells nothing
        items.append(
            MemoryItem(
                kind="answer",
                id=str(question.id),
                text=(
                    f"Asked what was going on when their {label(question.metric)} changed "
                    f"around {short_date(question.window_start)}, the person said: "
                    f"{OPTION_TEXT[question.answer]}."
                ),
                metrics=(question.metric,),
                created=_aware(question.answered_at),
                importance=1.0,
                start=question.window_start,
                end=question.window_end,
            )
        )
    for fact in session.scalars(
        select(MemoryFact).where(MemoryFact.user_id == user_id, MemoryFact.status == "approved")
    ):
        last = _aware(fact.last_used_at or fact.decided_at or fact.created_at)
        if now - last > timedelta(days=FACT_UNUSED_DAYS):
            continue  # unused facts fade out
        items.append(
            MemoryItem(
                kind="preference" if fact.kind == "preference" else "fact",
                id=str(fact.id),
                text=fact.text,
                metrics=tuple(fact.metrics),
                created=_aware(fact.decided_at or fact.created_at),
                importance=1.0,
            )
        )
    items += _episodes(session, user_id, conversation_id)
    return items


def _episodes(
    session: Session, user_id: uuid.UUID, conversation_id: uuid.UUID | None
) -> list[MemoryItem]:
    query = select(MemoryEpisode).where(MemoryEpisode.user_id == user_id)
    if conversation_id is not None:
        query = query.where(MemoryEpisode.conversation_id != conversation_id)
    rows = list(session.scalars(query))
    evidence = load_evidence(session, user_id, {i for row in rows for i in row.evidence_ids})
    items = []
    for row in rows:
        cited = tuple(evidence[i] for i in row.evidence_ids if i in evidence)
        items.append(
            MemoryItem(
                kind="episode",
                # Not a fact id, so using it in a run leaves the facts' usage alone.
                id=f"episode:{row.id}",
                text=row.text,
                metrics=tuple(row.metrics),
                created=_aware(row.through),
                importance=0.5,
                start=min((w.start for e in cited for w in e.windows), default=None),
                end=max((w.end for e in cited for w in e.windows), default=None),
                evidence=cited,
            )
        )
    return items


# Episodes


def _worth_keeping(messages: Iterable[ChatMessage]) -> list[dict]:
    """A chat's verified claims, best kind first and the newest first within a kind."""
    claims = [
        claim
        for message in reversed(list(messages))
        if message.role == "assistant" and not message.refused
        for claim in message.claims or ()
        if claim.get("kind") in EPISODE_KINDS and claim.get("metric") and claim.get("text")
    ]
    return sorted(claims, key=lambda claim: EPISODE_KINDS.index(claim["kind"]))


def _episode_text(day: date, claims: Iterable[dict]) -> tuple[str, list[dict]]:
    """The dated line, with as many claims as fit; a claim is never cut short."""
    text, kept = short_date(day) + ":", []
    for claim in claims:
        addition = " " + claim["text"].strip()
        if len(kept) == EPISODE_CLAIMS or len(text) + len(addition) > MAX_EPISODE_CHARS:
            continue
        text += addition
        kept.append(claim)
    return text, kept


def consolidate(session: Session, user_id: uuid.UUID, now: datetime | None = None) -> int:
    """Writes or refreshes the episode of each idle chat used since its last one; returns how many
    changed. Only verified claims go in, so a chat without any leaves no episode."""
    now = now or _now()
    episodes = {
        row.conversation_id: row
        for row in session.scalars(select(MemoryEpisode).where(MemoryEpisode.user_id == user_id))
    }
    changed = 0
    for conversation in session.scalars(
        select(Conversation).where(
            Conversation.user_id == user_id,
            Conversation.updated_at <= now - EPISODE_IDLE,
            Conversation.updated_at >= now - timedelta(days=EPISODE_DAYS),
        )
    ):
        used = _aware(conversation.updated_at)
        episode = episodes.get(conversation.id)
        if episode is not None and _aware(episode.through) >= used:
            continue
        messages = session.scalars(
            select(ChatMessage)
            .where(ChatMessage.user_id == user_id, ChatMessage.conversation_id == conversation.id)
            .order_by(ChatMessage.created_at)
        )
        text, claims = _episode_text(used.date(), _worth_keeping(messages))
        if not claims:
            if episode is not None:  # an edit took its claims away
                session.delete(episode)
                changed += 1
            continue
        values = {
            "day": used.date(),
            "text": text,
            "metrics": list(dict.fromkeys(c["metric"] for c in claims)),
            "evidence_ids": list(dict.fromkeys(i for c in claims for i in c["evidence_ids"])),
            "through": used,
        }
        if episode is None:
            session.add(MemoryEpisode(user_id=user_id, conversation_id=conversation.id, **values))
        else:
            for name, value in values.items():
                setattr(episode, name, value)
        changed += 1
    session.flush()
    return changed


def maintain_all(sessions, now: datetime) -> dict[str, int]:
    """The background pass over everyone with a chat: consolidate idle chats, expire what is old.
    Each person has their own session, so one failure leaves the others done."""
    with sessions() as db:
        people = list(db.scalars(select(Conversation.user_id).distinct()))
    totals = {"episodes": 0, "expired": 0}
    for user_id in people:
        with sessions() as db:
            totals["episodes"] += consolidate(db, user_id, now)
            totals["expired"] += sum(expire(db, user_id, now).values())
    return totals


def mark_used(
    session: Session, user_id: uuid.UUID, ids: Iterable[str], now: datetime | None = None
) -> None:
    """Records that these facts went into a run, so facts that keep mattering stay retrievable."""
    wanted = []
    for value in ids:
        try:
            wanted.append(uuid.UUID(value))
        except ValueError:
            continue
    if not wanted:
        return
    for fact in session.scalars(
        select(MemoryFact).where(MemoryFact.user_id == user_id, MemoryFact.id.in_(wanted))
    ):
        fact.last_used_at = now or _now()
        fact.uses += 1
    session.flush()
