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
from datetime import UTC, date, datetime

import pandas as pd

from app.agent.agent import (
    DEFAULT_GUIDE,
    NO_ANSWER,
    SYSTEM_PROMPT,
    AgentResult,
    ExtraTool,
    answer,
)
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
    specialist_notes,
    visible_metrics,
)
from app.agent.followup import standalone, with_relative_day
from app.agent.guard import Guard, GuardError, JevGuard
from app.agent.intent import Intent
from app.agent.jev import JevClient, JevError
from app.agent.knowledge import (
    KNOWLEDGE,
    Card,
    Guidance,
    cards_for,
    cited_sources,
    guidance_block,
    guidance_for,
    knowledge_tool,
    load_cards,
    more_passages,
    source_note,
)
from app.agent.listener import is_explicit
from app.agent.llm import LLM, Budget
from app.agent.memory_tools import conversation_search_tool, memory_lookup_tool
from app.agent.personal import (
    NOT_ABOUT_EATING_LEVERS,
    NOT_ABOUT_EATING_OPTIONS,
    PERSONAL_TOOLS,
    Fit,
    Relevant,
    as_points,
    asked_count,
    draft_check,
    fit_to_life,
    food_log_summary,
    memory_evidence,
    personal_check,
    rank_memory,
    relevant_block,
    top_up,
    without_filler,
)
from app.agent.router import (
    FallbackRouter,
    JevRouter,
    KeywordRouter,
    Route,
    Router,
    RouterError,
    decide,
)
from app.agent.sanitize import clean
from app.agent.strategy import (
    COACHING_OFFER,
    CROSS_AREA_GUIDE,
    PREMISE_GUIDE,
    asked_day,
    check_premise,
    coaching_evidence,
    cross_area_evidence,
    eating_context,
    expand_tool,
    premise_answer_check,
    scaled,
    snapshot,
    strategy_for,
)
from app.agent.verifier import Claim
from app.agent.world import answer_world
from app.analysis.evidence import Evidence
from app.outside import Outside
from app.reminders.tools import REMINDER_PROMPT

# A coaching answer that already offers a reminder or a test needs no extra line.
OFFERED = re.compile(r"\b(remind\w*|test\w*|experiment\w*)\b", re.IGNORECASE)

# The pending state of a chat whose last answer asked about a reminder (see `api/chat.py`).
REMINDERS = "reminders"

# Shown without calling the model: the refusal costs nothing and cannot be talked around.
# What must not wait for a tracker app. Matched in code, so it holds when the router is down. It
# errs towards replying: a sore chest after a hard session gets this too, and that is fine.
URGENT_BODY = re.compile(
    r"\b(chest (?:pain|pains|hurts?|pressure|tightness|is tight|feels tight)|"
    r"pain in (?:my|the) chest|(?:can'?t|cannot|struggling to|hard to) breathe|"
    r"(?:passed|blacked|passing|blacking) out|fainted|"
    r"(?:face|mouth) (?:is )?droop\w*|slurred speech|sudden numbness|"
    r"numb(?:ness)? (?:on|in) one side|coughing (?:up )?blood)\b",
    re.IGNORECASE,
)
URGENT_MIND = re.compile(
    r"\b(kill(?:ing)? myself|suicid\w*|end(?:ing)? my life|want to die|don'?t want to (?:live|be "
    r"here)|hurt(?:ing)? myself|self[- ]harm)\b",
    re.IGNORECASE,
)
URGENT_BODY_REPLY = (
    "That could be serious, and it isn't something your tracker data can answer. If it's "
    "happening now or getting worse, please call your local emergency number or get to urgent "
    "care. If it has passed, it's still worth getting it checked by a doctor soon."
)
URGENT_MIND_REPLY = (
    "I'm really sorry you're feeling this way, and I'm glad you said it. I'm not the right help "
    "for this, but you shouldn't carry it alone. Please reach out now to someone you trust, a "
    "local crisis line, or your local emergency number if you might act on these thoughts."
)
NOTED = "Got it. Tap Keep on the card and I'll bear that in mind from now on."
REFUSAL = (
    "That's outside what I can help with. I'm good for your Fitbit data, everyday habits, logging "
    "food and workouts, and reminders, but not medical questions or other topics."
)


@dataclass
class Answer:
    route: Route
    result: AgentResult
    context: Context


LINKING_TYPES = ("why", "change", "pattern")
ASKS_WHY = ("why", "change")
NO_CONSULT = ("day", "lookup", "coaching")
MAX_REPLY_WORDS = 12
NEW_QUESTION = re.compile(
    r"\s*(?:how|what|why|when|which|did|do|does|is|are|was|were|can|could|show|tell)\b",
    re.IGNORECASE,
)
COACHING_NO_ANSWER = (
    "I don't see anything specific in your data to build advice on yet. What gets in the way on a "
    "normal day? That would tell me where to look."
)
EXTRA_PASSAGES = 4
HABIT_OPTIONS = "habit_options"
WANTED_EXTRA_CALLS = 2  # more points take a longer submission, and sometimes a second try
ADVICE_TOOLS = ("habit_options", "personal_options")


def _just_a_reply(text: str) -> bool:
    """Whether a message in a logging request gives a detail rather than asks something new."""
    return "?" not in text and len(text.split()) <= MAX_REPLY_WORDS and not NEW_QUESTION.match(text)


def urgent_free(question: str) -> bool:
    return not (URGENT_MIND.search(question) or URGENT_BODY.search(question))


def _is_personal(record: Evidence) -> bool:
    """Something specific about this person that a suggestion could stand on."""
    return (
        record.tool in PERSONAL_TOOLS
        or (record.tool == "habit_options" and bool(record.stats.get("supported")))
        or (record.tool == "personal_options" and bool(record.stats.get("options")))
    )


def _day(moment) -> date:
    return moment.date() if isinstance(moment, datetime) else moment or datetime.now(UTC).date()


def _zone(moment):
    return moment.tzinfo if isinstance(moment, datetime) and moment.tzinfo else UTC


def _food_lines(record: Evidence) -> str:
    stats = record.stats
    notes = "; ".join(option["note"] for option in stats["options"]) or "nothing stands out yet"
    return (
        f"The food they logged (evidence_id {record.id}): {stats['meals_logged']} meals over "
        f"{stats['days_logged']} days; {notes}"
    )


def _fill_points(llm: LLM, result: AgentResult, question: str, wanted: int, guard) -> None:
    """When an answer falls short of the points asked for, the rest come straight from the sources
    it retrieved, marked as general and linked."""
    points = [c for c in result.claims if c.kind in ("suggestion", "guidance")]
    if len(points) >= wanted:
        result.summary = as_points(result.summary)
        return
    cited = {i for c in result.claims for i in c.evidence_ids}
    records = [e for e in result.evidence.values() if e.tool == KNOWLEDGE and e.id not in cited]
    extra, cost = more_passages(question, llm, wanted + EXTRA_PASSAGES)
    result.budget.cost_usd += cost
    known = {e.stats["passage_id"] for e in result.evidence.values() if e.tool == KNOWLEDGE}
    records += [e for e in extra if e.stats["passage_id"] not in known]
    base = "" if result.summary in (NO_ANSWER, "", COACHING_NO_ANSWER) else result.summary
    added = top_up(base, wanted, len(points), records)
    if added and guard:
        try:
            flags = guard.judge([a.tip for a in added]).flagged
        except GuardError:
            return
        added = [a for a, bad in zip(added, flags, strict=True) if not bad]
    lines = [as_points(base)] if base else []
    lines += [f"- {a.tip}" for a in added]
    if added:
        closing = "The last points are general guidance from the sources."
        result.summary = "\n".join(lines) + f"\n\n{closing}"
    elif base:
        result.summary = as_points(base)
    for item in added:
        result.evidence[item.record.id] = item.record
        result.claims.append(
            Claim(text=item.tip[:600], kind="guidance", evidence_ids=[item.record.id])
        )


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


def events_during(memory: Sequence[MemoryItem], tested: Sequence[Evidence]) -> str:
    """What the person told us happened while the change they ask about did: "why did my sleep
    drop around Aug 15?" with exams kept for Aug 15 to 21. Put in front of the agent by code, as
    it was left unsaid when merely among the memory items."""
    windows = [e.windows[0] for e in tested if e.windows]
    if not windows:
        return ""
    start, end = min(w.start for w in windows), max(w.end for w in windows)
    overlapping = [
        item
        for item in memory
        if item.start is not None and item.start <= end and (item.end or item.start) >= start
    ]
    if not overlapping:
        return ""
    lines = [
        f"- {clean(item.text, 120)} ({item.start:%b %-d}"
        + (f" to {item.end:%b %-d}" if item.end and item.end != item.start else "")
        + ")"
        for item in overlapping[:2]
    ]
    return (
        "They told you about this, during the period the change is in, as quoted data:\n"
        + "\n".join(lines)
        + "\nIf the change holds there, say in the summary that it lined up with this, in their "
        "words; never that it caused it. It is what they told you, not a statistic: make no "
        "claim for it."
    )


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
    outside: Outside | None = None,
    food_logs: Sequence[dict] = (),
    made_a_draft: Callable[[], bool] | None = None,
    guidance_mode: str = "picked",  # "none" and "all" exist to compare them (eval/advice_compare)
) -> Answer:
    """Routes the question and has the right agent answer it, with verified claims.

    `history` is the conversation so far (oldest first), `stored_evidence` the evidence its
    answers cite and `memory` the person's stored memory, all loaded by the caller for this person
    only. Routing comes first, so memory is chosen for the metrics the question is about."""
    reply_text = question.rsplit("Their reply: ", 1)[-1]
    rewrite_cost = 0.0
    if urgent_free(question):  # what a follow-up refers to, before routing or an expert sees it
        day = today.date() if isinstance(today, datetime) else today or date.today()
        means = with_relative_day(question, history, day)
        question, rewrite_cost = standalone(
            llm, question, history, means if means != question else None
        )
    if choice == "auto" and attachment and (attached := owner(attachment.metric)):
        choice = attached.name  # the attachment decides the topic
    route = decide(router.classify(question, earlier_questions(history)), choice)
    # A single value, last night or advice is one expert's job; a second expert costs as much again
    # and, measured, changed nothing. Questions linking areas (why, change, pattern) keep them.
    if route.classification.question_type in NO_CONSULT and route.consult:
        route = replace(route, consult=())
    continuing = (
        (continuing_log in (action_tools or {}) or continuing_log == "general")
        and (
            choice in ("auto", continuing_log)
            or (continuing_log == "general" and choice in (action_tools or {}))
        )
        and (
            route.classification.intent == Intent.CLARIFY
            # "40 minutes, no wait 50" reads as a statement about data; a new question does not.
            or (route.classification.intent == Intent.READ and _just_a_reply(reply_text))
        )
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
    # Experts answer inside their area, where they matched the general agent at less cost. A why
    # question, or one the router says spans areas, goes to the general agent with every metric:
    # measured, experts kept to their own metrics found a cause in another area 11% of the time
    # against 56% (docs/evaluation.md). The expert it would have gone to is kept as the advisor.
    advisor = None
    if (
        route.action == "expert"
        and route.routed  # an expert the person picked answers, as asked
        and not continuing
        and route.classification.intent not in (Intent.LOG, Intent.MIXED, Intent.REMIND)
        and (route.classification.question_type == "why" or route.consult)
    ):
        advisor = route.expert
        route = Route("general", None, (), route.routed, route.classification)
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
    # A question about the world goes to its lookup, unless it comes with something to do.
    world = (
        outside is not None
        and route.classification.question_type == "world"
        and route.action in ("expert", "general")
        and not (acting or continuing or reminding or logging_tools)
    )
    plan = (
        None
        if acting or continuing or reminding or logging_tools or world
        else strategy_for(route.classification.question_type)
    )
    # Someone with nothing logged can still ask how to eat better: the rest of their data and
    # what they told you still bear on it, so a general run answers, under the nutrition name.
    lead_on_no_data = None
    if (
        plan
        and plan.coaching
        and route.action == "expert"
        and route.expert in EXPERTS
        and not available(EXPERTS[route.expert], frame)
    ):
        lead_on_no_data = route.expert
        route = Route("general", None, (), route.routed, route.classification)
    block, evidence, owners = context.block, dict(context.evidence), dict(context.owners)
    relevant: list[Relevant] = []
    fit, memory_cost, personal_ids = Fit(), Budget(), set()
    if plan and plan.coaching and guidance_mode != "none" and urgent_free(question):
        moment = now or datetime.now(UTC)
        kept = chat.profile if chat else ()
        relevant = rank_memory(question, archive, kept, llm, moment, memory_cost)
        fit = fit_to_life([*kept, *(r.text for r in relevant)])
        records = [memory_evidence(item) for item in relevant]
        evidence |= {record.id: record for record in records}
        personal_ids |= {record.id for record in records}
        about = relevant_block(relevant, records, fit)
        block = "\n\n".join(part for part in (block, about) if part)
    guidance: list[Card] = []
    retrieved: Guidance | None = None
    # The public guidance on this expert's topics; `search` widens if nothing there fits, and an
    # answer that crosses areas or has no expert searches everything.
    topics = route.expert if route.action == "expert" and not route.consult else None
    # What the question takes for granted, checked before anyone sets out to explain it.
    false_premise = False
    if plan and route.classification.question_type in ASKS_WHY and urgent_free(question):
        premise = check_premise(frame, question, route.expert or advisor)
        if premise:
            evidence |= {record.id: record for record in premise.evidence}
            block = "\n\n".join(part for part in (block, premise.text) if part)
            false_premise = not premise.holds
            if false_premise:
                route = replace(route, consult=())
                plan = replace(plan, guide=PREMISE_GUIDE, tools=("describe", "compare_windows"))
            elif lined_up := events_during(memory, premise.evidence):
                block = "\n\n".join((block, lined_up))
    # Linking two areas: run the tests here rather than pay a second expert to choose them.
    if (
        plan
        and route.action == "expert"
        and route.consult
        and route.classification.question_type in LINKING_TYPES
    ):
        records, text = cross_area_evidence(frame, route.expert, route.consult)
        if records:
            evidence |= {record.id: record for record in records}
            for record in records:  # its driver's expert stands behind what it says of that metric
                if driver_owner := owner(record.metrics[0]):
                    owners[record.id] = driver_owner.name
            block = "\n\n".join(part for part in (block, text) if part)
            route = replace(route, consult=())
            plan = replace(
                plan,
                guide=CROSS_AREA_GUIDE,
                tools=("coverage", "correlate", "compare_windows", "change_point"),
            )
    if plan:
        visible = sorted(_scope(route) or frame.columns)
        found: list[tuple[list[Evidence], str]] = []
        if plan.snapshot and (lead_on_no_data or route.expert) != "nutrition":
            found.append(snapshot(frame, visible, asked_day(question, today, frame)))
        if plan.coaching:
            lead = lead_on_no_data or route.expert
            eating = lead == "nutrition"
            skip_levers = fit.levers | (NOT_ABOUT_EATING_LEVERS if eating else frozenset())
            skip_options = fit.options | (NOT_ABOUT_EATING_OPTIONS if eating else frozenset())
            found.append(coaching_evidence(frame, lead, visible, skip_levers, skip_options))
            if food := food_log_summary(food_logs, _day(today or now), _zone(today)):
                found.append(([food], _food_lines(food)))
            if lead == "nutrition":
                found.append(eating_context(frame, skip=fit.options))
        for records, text in found:
            block = "\n\n".join(part for part in (block, text) if part)
            for record in records:
                evidence[record.id] = record
                metric_owner = owner(record.metrics[0]) if record.metrics else None
                if metric_owner:
                    owners[record.id] = metric_owner.name
                if plan.coaching and _is_personal(record):
                    personal_ids.add(record.id)
        if plan.coaching:
            # What their data points to, and what this question is about: retrieved by code, so
            # it costs no model round and cannot be skipped.
            picked = cards_for(e for records, _ in found for e in records if e.tool in ADVICE_TOOLS)
            guidance = picked
            if guidance_mode != "picked":
                guidance = list(load_cards()) if guidance_mode == "all" else []
            if guidance_mode == "picked":
                retrieved = guidance_for(
                    question, picked, llm, " ".join(r.text for r in relevant), area=topics
                )
                evidence |= {record.id: record for record in retrieved.evidence}
                block = "\n\n".join(part for part in (block, retrieved.text) if part)
            else:
                block = "\n\n".join(part for part in (block, guidance_block(guidance)) if part)
    if plan and plan.coaching:
        tools.append(knowledge_tool(llm=llm, area=topics))
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
    # What they said gets ignored far above the question: it has to be there at the point of use.
    asked = question
    if relevant or fit.notes:
        what = "; ".join([*(r.text for r in relevant), *fit.notes])
        asked = f"{question}\n(What they told you, which the advice has to fit: {what})"
    wanted = asked_count(question) if plan and plan.coaching else 0
    passage_ids = frozenset(e.id for e in retrieved.evidence) if retrieved else frozenset()
    check = (
        personal_check(personal_ids, fit, wanted, passage_ids) if plan and plan.coaching else None
    )
    if false_premise:
        check = premise_answer_check
    if made_a_draft and logging_tools and route.classification.intent == Intent.LOG:
        check = draft_check(made_a_draft)
    if wanted:
        asked += (
            f"\n(They asked for {wanted} points: give {wanted} different ones. Everything needed "
            "is above, so submit now without calling other tools, and start each with 'You could "
            "try'.)"
        )
        extra = replace(plan.budget, max_calls=plan.budget.max_calls + WANTED_EXTRA_CALLS)
        plan = replace(plan, budget=extra)
    if plan and fit.levers:  # its own run of this tool would hand what was ruled out back
        plan = replace(plan, tools=tuple(t for t in plan.tools if t != HABIT_OPTIONS))
    urgent = (
        URGENT_MIND_REPLY
        if URGENT_MIND.search(question)
        else URGENT_BODY_REPLY
        if URGENT_BODY.search(question)
        else None
    )
    if urgent:  # before anything else, and no model: this reply must not be able to go wrong
        route = replace(route, action="refuse")
        result = AgentResult(run_id=uuid.uuid4().hex[:12], stop_reason="urgent", summary=urgent)
    elif route.action == "refuse":
        result = AgentResult(run_id=uuid.uuid4().hex[:12], stop_reason="refused", summary=REFUSAL)
    elif is_explicit(question) and "?" not in question and not logging_tools:
        # Keeping it is the person's tap on the card the listener raises; no data to look at.
        result = AgentResult(run_id=uuid.uuid4().hex[:12], stop_reason="noted", summary=NOTED)
    elif world:
        result = answer_world(llm, question, outside, guard=guard)
    elif route.action == "conversation":
        result = recall(
            llm,
            question,
            history,
            guard=guard,
            summary=chat.usable_summary if chat else None,
            past=search_past(question) if search_past else (),
            profile=chat.profile if chat else (),
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
        and route.classification.question_type != "coaching"  # "what should I do?" is no meal
        and "?" not in question  # someone asking something has not just told you what they ate
    ):
        result = ask_what_they_want(llm, question, expert=route.expert, guard=guard)
    elif route.action == "general":
        result = answer(
            llm,
            frame,
            asked,
            today=today,
            budget=scaled(plan, deep) if plan else replace(BUDGETS[depth]),
            system_prompt=SYSTEM_PROMPT
            + action_prompt
            + (specialist_notes(frame) if route.classification.question_type == "why" else ""),
            context=block,
            evidence=evidence,
            guard=guard,
            extra_tools=tools,
            tools=plan.tools if plan else None,
            guide=plan.guide if plan else DEFAULT_GUIDE,
            widen=expand_tool if plan else None,
            answer_check=check,
        )
        if lead_on_no_data:
            result.expert = lead_on_no_data
    else:
        result = ask_expert(
            llm,
            frame,
            route.expert,
            asked,
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
            answer_check=check,
        )
        result.notes += _notes(frame, route, result)
    stopped_early = result.stop_reason in ("urgent", "refused", "noted")
    if plan and plan.coaching:
        result.summary = without_filler(result.summary)
        if wanted and not stopped_early:
            _fill_points(llm, result, question, wanted, guard)
    if plan and plan.coaching and result.summary in (NO_ANSWER, ""):
        result.summary = COACHING_NO_ANSWER
    if (
        plan
        and plan.coaching
        and any(claim.kind == "suggestion" for claim in result.claims)
        and not OFFERED.search(result.summary)
    ):
        result.notes.append(COACHING_OFFER)  # coaching ends with something to do
    if plan and plan.coaching and not stopped_early:
        result.budget.cost_usd += memory_cost.cost_usd
        result.trace.append(
            {
                "type": "personal",
                "memory": [{"text": r.text[:80], "score": round(r.score, 3)} for r in relevant],
                "skipped_levers": sorted(fit.levers),
                "personal_evidence": len(personal_ids),
            }
        )
    if retrieved is not None and not stopped_early:
        result.trace.append(retrieved.step)
        result.budget.cost_usd += retrieved.cost_usd
    if guidance and not stopped_early:
        result.trace.append({"type": "guidance", "cards": [card.id for card in guidance]})
    if not stopped_early:
        known = {link["url"] for link in result.sources}
        result.sources += [s for s in cited_sources(result) if s["url"] not in known]
    # A lookup has already said where its answer comes from.
    if not stopped_early and not world and (note := source_note(result)):
        result.notes.append(note)
    result.budget.cost_usd += rewrite_cost
    result.trace[:0] = [_context_step(context), _route_step(route)]
    if continuing:
        result.trace[1]["continuing_log_expert"] = continuing_log
    if reminding:
        result.trace[1]["reminding"] = True
    return Answer(route, result, context)
