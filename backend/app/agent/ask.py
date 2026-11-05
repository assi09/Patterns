"""Answering one question from the Ask screen: build its context, route it, then refuse or answer.

The context (earlier turns, their evidence, an attachment) is chosen by code before any model runs
(`context.py`). The router sees the question and the earlier questions only. An attachment's metric
decides the lead, like picking an expert, unless the person picked one; the scope check and the
choice of consults stay with the router. A question about the conversation itself is answered from
the conversation (`conversation.py`). What the context included and how the question was routed
are the first steps of the trace, so every answer can be traced to its context and its routing.
"""

import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime

import pandas as pd

from app.agent.agent import DEFAULT_GUIDE, SYSTEM_PROMPT, AgentResult, ExtraTool, answer
from app.agent.context import (
    Attachment,
    ChatState,
    Context,
    MemoryItem,
    Turn,
    build,
    earlier_questions,
)
from app.agent.conversation import ask_what_they_want, recall
from app.agent.experts import (
    BUDGETS,
    EXPERTS,
    LOGGING_PROMPT,
    Depth,
    ask_expert,
    available,
    lead_budget,
    owner,
    visible_metrics,
)
from app.agent.guard import Guard, JevGuard
from app.agent.intent import Intent
from app.agent.jev import JevClient, JevError
from app.agent.knowledge import Card, cards_for, guidance_block, knowledge_tool, source_note
from app.agent.llm import LLM
from app.agent.memory_tools import conversation_search_tool, memory_lookup_tool
from app.agent.router import (
    FallbackRouter,
    JevRouter,
    KeywordRouter,
    Route,
    Router,
    RouterError,
    decide,
)
from app.agent.strategy import (
    COACHING_OFFER,
    coaching_evidence,
    expand_tool,
    scaled,
    snapshot,
    strategy_for,
)
from app.analysis.evidence import Evidence
from app.reminders.tools import REMINDER_PROMPT

# A coaching answer that already offers a reminder or a test needs no extra line.
OFFERED = re.compile(r"\b(remind\w*|test\w*|experiment\w*)\b", re.IGNORECASE)

# The pending state of a chat whose last answer asked about a reminder (see `api/chat.py`).
REMINDERS = "reminders"

# Shown without calling the model: the refusal costs nothing and cannot be talked around.
REFUSAL = (
    "I can only describe patterns in your own Fitbit data, so I can't help with medical "
    "questions, diagnoses or advice, or with questions about anything else."
)


@dataclass
class Answer:
    route: Route
    result: AgentResult
    context: Context


HABITS = "habit_options"


def _scope(route: Route) -> set[str] | None:
    """The metrics in play: the lead's own and the ones it reads, and its consults' (None: all)."""
    if route.action != "expert":
        return None
    metrics = set(visible_metrics(EXPERTS[route.expert]))
    for name in route.consult:
        metrics |= set(EXPERTS[name].owns)
    return metrics


def default_router(settings) -> Router:
    """Jev with the keyword rule as fallback; the keyword rule alone without a TypeSafe key."""
    try:
        return FallbackRouter(JevRouter.from_settings(settings), KeywordRouter())
    except RouterError:
        return KeywordRouter()


def default_guard(settings) -> Guard | None:
    """Jev checking shown text for advice; none without a TypeSafe key (word checks only)."""
    try:
        return JevGuard(JevClient.from_settings(settings))
    except JevError:
        return None


def _route_step(route: Route) -> dict:
    c = route.classification
    return {
        "type": "route",
        "source": c.source,
        "probabilities": {label: round(p, 4) for label, p in c.probabilities.items()},
        "needs": {expert: round(p, 4) for expert, p in c.needs.items()},
        "intent": c.intent,
        "question_type": c.question_type,
        "intent_probabilities": {
            intent: round(p, 4) for intent, p in c.intent_probabilities.items()
        },
        "action": route.action,
        "expert": route.expert,
        "consult": list(route.consult),
        "routed": route.routed,
        "latency_s": round(c.latency_s, 3),
        "cost_usd": c.cost_usd,
        "error": c.error,
    }


def _notes(frame: pd.DataFrame, route: Route, result: AgentResult) -> list[str]:
    """Fixed sentences for what the answer could not cover, so a gap is said, not hidden."""
    missing = [
        name for name in route.consult if name in EXPERTS and not available(EXPERTS[name], frame)
    ]
    notes = [f"There is no {name} data yet, so it is left out here." for name in missing]
    if result.uncovered:
        names = " or ".join(result.uncovered)
        notes.append(
            f"Your {names} data was not checked for this answer; ask about it if you would "
            "like it looked at."
        )
    return notes


def _context_step(context: Context) -> dict:
    return {"type": "context", **context.included, "dropped": context.dropped}


def ask(
    llm: LLM,
    router: Router,
    frame: pd.DataFrame,
    question: str,
    *,
    choice: str = "auto",
    depth: Depth = Depth.QUICK,
    today: date | None = None,
    history: Sequence[Turn] = (),
    stored_evidence: dict[str, Evidence] | None = None,
    attachment: Attachment | None = None,
    guard: Guard | None = None,
    memory: Sequence[MemoryItem] = (),
    now: datetime | None = None,
    action_tools: dict[str, list[ExtraTool]] | None = None,
    continuing_log: str | None = None,
    reminder_tools: list[ExtraTool] | None = None,
    chat: ChatState | None = None,
    archive: Sequence[MemoryItem] = (),
    search_past: Callable[[str], list[dict]] | None = None,
) -> Answer:
    """Routes the question and has the right agent answer it, with verified claims.

    `history` is the conversation so far (oldest first), `stored_evidence` the evidence its
    answers cite and `memory` the person's stored memory, all loaded by the caller for this person
    only. Routing comes first, so memory is chosen for the metrics the question is about."""
    if choice == "auto" and attachment and (attached := owner(attachment.metric)):
        choice = attached.name  # the attachment decides the topic
    route = decide(router.classify(question, earlier_questions(history)), choice)
    continuing = (
        (continuing_log in (action_tools or {}) or continuing_log == "general")
        and (
            choice in ("auto", continuing_log)
            or (continuing_log == "general" and choice in (action_tools or {}))
        )
        and route.classification.intent == Intent.CLARIFY
        and route.action not in ("refuse", "conversation")
    )
    # A reminder request, or the answer to the agent's question about one ("at 10").
    reminding = (
        bool(reminder_tools)
        and route.action not in ("refuse", "conversation")
        and (
            route.classification.intent == Intent.REMIND
            or (continuing_log == REMINDERS and route.classification.intent == Intent.CLARIFY)
        )
    )
    if continuing:
        # This state comes from the server's unfinished clarification, not earlier text alone.
        if continuing_log == "general":
            if route.expert not in (action_tools or {}):
                route = Route("general", None, (), True, route.classification)
        else:
            route = Route("expert", continuing_log, (), choice == "auto", route.classification)
    context = build(
        history,
        stored_evidence or {},
        attachment,
        memory=memory,
        scope=_scope(route),
        now=now,
        chat=chat,
    )
    tools: list[ExtraTool] = []
    logging_tools = []
    if (
        route.classification.intent in (Intent.LOG, Intent.MIXED) or continuing
    ) and route.action != "refuse":
        if route.action == "general":
            logging_tools = [tool for group in (action_tools or {}).values() for tool in group]
        else:
            # The lead's own, and in a new request those of the experts the router says it also
            # needs: "a swim after three figs" is a workout and a meal. A reply continuing a
            # request stays with its kind; its text quotes the question, which names both.
            names = (route.expert,) if continuing else (route.expert, *route.consult)
            logging_tools = [tool for name in names for tool in (action_tools or {}).get(name, [])]
    tools += logging_tools
    if reminding:
        tools += reminder_tools
    action_prompt = (LOGGING_PROMPT if logging_tools else "") + (
        REMINDER_PROMPT if reminding else ""
    )
    # How to work on this kind of question; logging and reminders keep the full toolbox.
    acting = route.classification.intent in (Intent.LOG, Intent.MIXED, Intent.REMIND)
    plan = (
        None
        if acting or continuing or reminding or logging_tools
        else strategy_for(route.classification.question_type)
    )
    block, evidence, owners = context.block, dict(context.evidence), dict(context.owners)
    guidance: list[Card] = []
    if plan:
        visible = sorted(_scope(route) or frame.columns)
        found: list[tuple[list[Evidence], str]] = []
        if plan.snapshot:
            found.append(snapshot(frame, visible))
        if plan.coaching:
            found.append(coaching_evidence(frame, route.expert, visible))
        for records, text in found:
            block = "\n\n".join(part for part in (block, text) if part)
            for record in records:
                evidence[record.id] = record
                if metric_owner := owner(record.metrics[0]):
                    owners[record.id] = metric_owner.name
        if plan.coaching:
            guidance = cards_for(e for records, _ in found for e in records if e.tool == HABITS)
            block = "\n\n".join(part for part in (block, guidance_block(guidance)) if part)
    if plan and plan.coaching:
        tools.append(knowledge_tool())
    if plan and plan.memory:  # what a search may find can be cited, like the rest of memory
        if archive:
            tools.append(memory_lookup_tool(archive))
        if search_past:
            tools.append(conversation_search_tool(search_past))
        for item in archive:
            metric_owner = next((owner(m) for m in item.metrics if owner(m)), None)
            for record in item.evidence:
                evidence.setdefault(record.id, record)
                if metric_owner:
                    owners.setdefault(record.id, metric_owner.name)
    deep = depth == Depth.DEEP
    if route.action == "refuse":
        result = AgentResult(run_id=uuid.uuid4().hex[:12], stop_reason="refused", summary=REFUSAL)
    elif route.action == "conversation":
        result = recall(
            llm,
            question,
            history,
            guard=guard,
            summary=chat.usable_summary if chat else None,
            past=search_past(question) if search_past else (),
        )
    elif action_tools and route.classification.intent == Intent.MANAGE:
        result = AgentResult(
            run_id=uuid.uuid4().hex[:12],
            stop_reason="action_controls",
            summary="Use the entry card to edit or cancel a draft. To remove a logged entry, "
            "choose Undo and confirm the removal. Chat messages cannot confirm Google writes. "
            "Reminders are paused, changed or deleted in Reminders.",
        )
    elif (
        action_tools
        and route.classification.intent_probabilities
        and route.classification.intent == Intent.CLARIFY
        and route.expert in ("nutrition", "activity")
        and not continuing
    ):
        result = ask_what_they_want(llm, question, expert=route.expert, guard=guard)
    elif route.action == "general":
        result = answer(
            llm,
            frame,
            question,
            today=today,
            budget=scaled(plan, deep) if plan else replace(BUDGETS[depth]),
            system_prompt=SYSTEM_PROMPT + action_prompt,
            context=block,
            evidence=evidence,
            guard=guard,
            extra_tools=tools,
            tools=plan.tools if plan else None,
            guide=plan.guide if plan else DEFAULT_GUIDE,
            widen=expand_tool if plan else None,
        )
    else:
        result = ask_expert(
            llm,
            frame,
            route.expert,
            question,
            depth=depth,
            consult=route.consult,
            today=today,
            context=block,
            evidence=evidence,
            owners=owners,
            budget=lead_budget(depth, len(route.consult), scaled(plan, deep)) if plan else None,
            tools=plan.tools if plan else None,
            guide=plan.guide if plan else None,
            widen=expand_tool if plan else None,
            guard=guard,
            # A request only to log asks nothing about the data, so no part of it can be left
            # uncovered; a mixed request still needs its question answered.
            needs=()
            if reminding
            or (logging_tools and (route.classification.intent == Intent.LOG or continuing))
            else (route.expert, *route.consult),
            extra_tools=tools,
            allow_logging=bool(logging_tools),
            action_prompt=REMINDER_PROMPT if reminding else "",
        )
        result.notes += _notes(frame, route, result)
    if (
        plan
        and plan.coaching
        and any(claim.kind == "suggestion" for claim in result.claims)
        and not OFFERED.search(result.summary)
    ):
        result.notes.append(COACHING_OFFER)  # coaching ends with something to do
    if guidance:
        result.trace.append({"type": "guidance", "cards": [card.id for card in guidance]})
    if note := source_note(result):
        result.notes.append(note)
    result.trace[:0] = [_context_step(context), _route_step(route)]
    if continuing:
        result.trace[1]["continuing_log_expert"] = continuing_log
    if reminding:
        result.trace[1]["reminding"] = True
    return Answer(route, result, context)
