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
from app.agent.conversation import ask_what_they_want, chat_reply, recall
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
from app.agent.followup import standalone, with_period, with_relative_day
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
from app.agent.limits import (
    FUTURE_GUIDE,
    FUTURE_TOOLS,
    OTHER_PERSON_REPLY,
    UNTRACKED_REPLY,
    asks_future,
    other_person,
    outside_the_data,
    untracked,
    untracked_note,
)
from app.agent.listener import is_explicit, worth_listening
from app.agent.llm import LLM, Budget
from app.agent.memory_tools import conversation_search_tool, memory_lookup_tool
from app.agent.periods import asks_over_days, with_dates
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
from app.agent.requested import execute as execute_request
from app.agent.requests import interpret
from app.agent.router import (
    OFF_TOPIC,
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
    BROAD_GUIDE,
    COACHING_OFFER,
    CROSS_AREA_GUIDE,
    PREMISE_GUIDE,
    asked_day,
    asked_metrics,
    candidate_causes,
    check_premise,
    coaching_evidence,
    cross_area_evidence,
    eating_context,
    expand_tool,
    figures_check,
    overview_evidence,
    premise_answer_check,
    scaled,
    snapshot,
    strategy_for,
)
from app.agent.strategy_types import (
    AFFIRM,
    LOGGABLE,
    REACTION,
    as_request,
    certain_talk,
    is_small_talk,
    is_statement,
    offer_in,
)
from app.agent.verifier import MEDICAL, STATISTIC_WORDS, Claim
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
# Said kindly, with something it can do instead: one fixed sentence for everything read as cold.
MEDICAL_REFUSAL = (
    "That one's a medical question, so it isn't something I can answer. What I can do is show "
    "you what your own data looks like, or suggest everyday habits from it. Want a look at how "
    "your recent days compare with your usual?"
)
MEDICAL_AGAIN = (
    "That's another one for the medical side, so I'll leave it. If it's about sleeping better, I "
    "can look at your own nights and suggest everyday habits that fit them."
)
OFF_TOPIC_AGAIN = "That one's outside my lane too. Ask me anything about your own data, though."
OFF_TOPIC_REFUSAL = (
    "That's outside what I know about. I stick to you: your Fitbit data, everyday habits, "
    "logging food and workouts, and reminders. Anything there you'd like to look at?"
)
OVERALL_GUIDE = (
    "How to work: they ask how they are doing overall. Open with a one-sentence verdict in plain "
    "words ('Mostly on track this week, with one rough night.'). If they name a period (this "
    "week, this month), compare that period with the weeks before using compare_windows on the "
    "main metrics (time asleep, recovery score, resting heart rate, steps) and give the figures; "
    "without one, answer from the snapshot of the latest day below. No hypotheses. Then call "
    "submit_findings."
)
OVERALL_TOOLS = ("compare_windows", "describe", "compare_day", "usual_ranges")
OVERALL = re.compile(
    r"^\s*(?:am i (?:ok|okay|alright|all right|fine|doing (?:ok|okay|well|good|fine|alright))|"
    r"how am i (?:doing|looking)|how(?:'s| is| has) my (?:week|day|month|body|data)(?: been)?|"
    r"how(?:'re| are) things looking|compare (?:this|last) (?:week|month) (?:to|with|against))\b",
    re.IGNORECASE,
)


@dataclass
class Answer:
    route: Route
    result: AgentResult
    context: Context


LINKING_TYPES = ("why", "change", "pattern")
ASKS_WHY = ("why", "change")
# Broad when the question names no metric (and, for a lookup, no statistic either).
BROAD_TYPES = ("why", "change", "lookup")
BROAD_TOOLS = ("compare_windows", "change_point", "trend", "coverage", "checkins", "correlate")
NO_CONSULT = ("day", "lookup", "coaching")
STATED_TYPES = ("day", "lookup", "change", "pattern")  # answered with the figures themselves
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


TOLD_HERE_TURNS = 6  # the latest messages of this chat whose statements count as context
MAX_TOLD = 3


# A correction to the draft just made. Drafts are edited on their card, where the values are.
CORRECTS = re.compile(
    r"^\s*(?:actually|(?:no|nah|nope|sorry|oops|wait)\b[\s,.!]*(?:i meant|it was|it's|its|"
    r"make it|i had|i ate|that was|should be|\d)|wait|oops|correction|make (?:it|that)|"
    r"change (?:it|that)|it was (?:actually )?\d|it should be|should be|i meant)\b",
    re.IGNORECASE,
)
# "Log it", "yes", "looks good" while a draft waits: the card is where it is confirmed.
# "Yes", "log it", and the two together ("Yes, log it", "yes, log that walking workout"), which
# lost the draft waiting above and asked what to log (the audit of 2026-11-18). A few words may
# name what it is; a number would be a new entry, not this one.
_CONFIRM = (
    r"(?:yes|yeah|yep|yup|ok|okay|sure|confirm(?: it)?|save it|add it|do it|go ahead|"
    r"sounds good|looks good|looks right|correct|perfect|great|please|pls|plz|"
    r"(?:log|save|add) (?:it|that|this|the)(?: [a-z]+){0,3})"
)
CONFIRMS = re.compile(rf"^\s*{_CONFIRM}(?:[\s,.!]+{_CONFIRM}){{0,3}}[\s.!]*$", re.IGNORECASE)
CONFIRM_ON_CARD = (
    "Tap Log it on the card above to add it. I don't send anything to Google myself, so it stays "
    "a draft until you do."
)
EDIT_ON_CARD = (
    "Got it. Change it on the card above: tap Edit, fix it, then confirm. Nothing is sent to "
    "Google until you do."
)


# "During it", "that one": a how-to follow-up about the thing the last question named.
REFERS_TO_IT = re.compile(r"\b(?:it|that one|this one|that exercise|that move|doing that)\b", re.I)


# "Does that mean walking caused my shorter sleep?", "can you tell me it definitely causes it?":
# about the link just shown. Sent to the general lookup, it was refused as off topic (the audit of
# 2026-11-18); the honest answer is the same every time, so code gives it.
CAUSE_FOLLOW_UP = re.compile(
    r"^(?=.*\b(?:caus(?:e|es|ed|ing)|is (?:it|that) because)\b)(?=.*\b(?:it|that|this|so)\b)",
    re.IGNORECASE,
)
ASSOCIATION_REPLY = (
    "These observational records cannot establish or rule out a cause. Whether the measurements "
    "move together needs a relationship test with enough paired data; a missing measurement or "
    "an inconclusive test does not establish an association."
)


def plain_reply(said: str, frame: pd.DataFrame, today: date, after_draft: bool) -> str | None:
    """What is said without a model: another person's data, a correction to the draft just made
    (changed on its card), or days the data does not reach."""
    if who := other_person(said):
        return OTHER_PERSON_REPLY.format(who=who)
    if after_draft and CONFIRMS.match(said):  # "log it": a person's tap on the card logs it
        return CONFIRM_ON_CARD
    if after_draft and CORRECTS.match(said):  # "actually it was 3 eggs"
        return EDIT_ON_CARD
    if not frame.empty:
        return outside_the_data(said, frame.index.min().date(), today)
    return None


def told_here(history: Sequence[Turn]) -> list[str]:
    """What the person said about themselves earlier in this chat, newest first. It shapes the
    answer before any card is kept: "I'm a student, I had projects" must reach the advice asked for
    a minute later."""
    said = []
    for turn in reversed(history[-TOLD_HERE_TURNS:]):
        text = clean(turn.question, 200)
        if worth_listening(text) and text not in said:
            said.append(text)
    return said[:MAX_TOLD]


def told_block(lines: Sequence[str]) -> str:
    if not lines:
        return ""
    quoted = "\n".join(f"- {line}" for line in lines)
    return (
        "Earlier in this chat they told you, as quoted data:\n"
        f"{quoted}\n"
        "If the data shows something it fits (a short night, a drop), say so in their words, never "
        "as a cause. If nothing changed, do not force a link. It is what they said, not a "
        "statistic: make no claim for it."
    )


SHORT_WHY = re.compile(r"^\s*(?:but |and |so )?why\b[^.]{0,30}$", re.IGNORECASE)
NOTHING_TO_EXPLAIN = (
    "Their last answer found no clear change, and they now ask why. Open by saying kindly that, "
    "as far as their data shows, it has not really changed, so there is nothing to explain yet; "
    "cite the earlier evidence. Then say what would show a real change, or offer to look again "
    "in a week or two. Do not hunt for causes."
)


def _asks_why_of_nothing(said: str, history: Sequence[Turn]) -> bool:
    """ "why?" right after an answer whose findings were all "no clear change"."""
    if not history or not SHORT_WHY.match(said):
        return False
    kinds = [c.get("kind") for c in history[-1].claims if c.get("kind") != "data_quality"]
    return bool(kinds) and all(kind == "no_change" for kind in kinds)


def _certain_talk(text: str) -> bool:
    return certain_talk(text)


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
    lines += [f"- {a.tip.lstrip('- ').strip()}" for a in added]
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
    after_draft: bool = False,  # the last answer prepared a logging draft
    request_bundle: tuple | None = None,  # the API may interpret before preparing action tools
) -> Answer:
    """Routes the question and has the right agent answer it, with verified claims.

    `history` is the conversation so far (oldest first), `stored_evidence` the evidence its
    answers cite and `memory` the person's stored memory, all loaded by the caller for this person
    only. Routing comes first, so memory is chosen for the metrics the question is about."""
    reply_text = question.rsplit("Their reply: ", 1)[-1]
    said = question  # their own words: small talk is judged on these, never on a rewrite
    rewrite_cost = 0.0
    typed, request_state, reading_budget = (None, {}, Budget())
    if urgent_free(question):
        typed, request_state, reading_budget = request_bundle or interpret(
            llm, reply_text, history, _day(today or now), pending_draft=after_draft
        )
    # "Yes" to the offer the last answer ended on takes it up, rather than reading as small talk.
    offer = offer_in(history[-1].answer) if history and AFFIRM.match(question) else None
    if offer:
        question = said = as_request(offer)
    fixed = plain_reply(said, frame, _day(today or now), after_draft)
    if typed is not None:
        # Wearable bounds do not bound confirmed food or public guidance. Precise requests
        # determine availability per source/part, including mixed food and wearable questions.
        if typed.subject != "other" and typed.kind in ("data", "causality", "guidance"):
            fixed = None
        # The reader resolves subjects semantically; a metric noun is not somebody's name.
        if typed.subject == "self" and other_person(said):
            fixed = None
        if typed.subject == "other" and typed.kind != "guidance":
            fixed = "I can only see your own data, not another person's records."
        elif typed.clarification:
            fixed = typed.clarification
        question = typed.question(question)
    if (
        typed is None
        and not fixed
        and history
        and history[-1].claims
        and CAUSE_FOLLOW_UP.search(said)
        and "?" in said
    ):
        fixed = ASSOCIATION_REPLY
    # What a follow-up refers to, before routing or an expert sees it.
    if (
        urgent_free(question)
        and typed is None
        and not fixed
        and not _certain_talk(question)
        and not is_statement(question)
    ):
        # Only without the request reader (a scripted model that has none): in the app every
        # message is read by requests.interpret, which resolves references and dates itself.
        day = today.date() if isinstance(today, datetime) else today or date.today()
        means = with_period(with_relative_day(question, history, day), history)
        question, rewrite_cost = standalone(
            llm, question, history, means if means != question else None
        )
    if choice == "auto" and attachment and (attached := owner(attachment.metric)):
        choice = attached.name  # the attachment decides the topic
    route = decide(router.classify(question, earlier_questions(history)), choice)
    if (
        typed is not None
        and typed.kind in ("data", "causality", "clarify", "guidance")
        and (
            urgent_free(said)
            and not MEDICAL.search(said)
            and (typed.kind != "guidance" or outside is not None)
        )
    ):
        # A precise validated request does not need a second model to choose statistics
        # and a third to restate them. Guidance still uses retrieved public passages.
        classification = replace(
            route.classification,
            question_types={"world" if typed.kind == "guidance" else "lookup": 1.0},
            intent_probabilities={str(i): float(i == Intent.READ) for i in Intent},
        )
        route = Route("general", None, (), choice == "auto", classification)
        context = build(
            history,
            stored_evidence or {},
            attachment,
            memory=memory,
            scope=set(),
            now=now,
            chat=chat,
        )
        if fixed:
            result = AgentResult(run_id=uuid.uuid4().hex[:12], stop_reason="limits", summary=fixed)
        elif typed.kind == "guidance":
            result = answer_world(
                llm,
                question,
                outside,
                guard=guard,
                topic=typed.topics[0] if len(typed.topics) == 1 else None,
            )
            known = {link["url"] for link in result.sources}
            result.sources += [s for s in cited_sources(result) if s["url"] not in known]
        else:
            result = execute_request(
                typed,
                frame,
                _day(today or now),
                food_logs=food_logs,
                zone=(now.tzinfo if now else None),
            )
        result.budget.calls += reading_budget.calls
        result.budget.cost_usd += reading_budget.cost_usd
        result.trace[:0] = [
            _context_step(context),
            _route_step(route),
            {
                "type": "request",
                "request": typed.model_dump(mode="json"),
                "state": request_state,
                "cost_usd": reading_budget.cost_usd,
                "model_calls": reading_budget.calls,
            },
        ]
        return Answer(route, result, context)
    # "Am I ok?" asks how their data looks, not for a diagnosis: answered, as an overall look.
    if route.action == "refuse" and OVERALL.match(said) and not MEDICAL.search(said):
        overall = replace(route.classification, question_types={"lookup": 1.0})
        route = Route("general", None, (), choice == "auto", overall)
    # "My total REM minutes?" is a value over days: the day strategy cannot add days up.
    if route.classification.question_type == "day" and asks_over_days(said):
        over_days = replace(route.classification, question_types={"lookup": 1.0})
        route = replace(route, classification=over_days)
    # Water or a menstrual cycle is not in the data: never the "no food logged" shortcut.
    missing = untracked(said)
    if missing and route.action == "expert" and route.expert == "nutrition":
        route = Route("general", None, (), route.routed, route.classification)
    # A single value, last night or advice is one expert's job; a second expert costs as much again
    # and, measured, changed nothing. Questions linking areas (why, change, pattern) keep them.
    if route.classification.question_type in NO_CONSULT and route.consult:
        route = replace(route, consult=())
    correcting_draft = typed is not None and typed.kind == "correction" and continuing_log
    if correcting_draft:
        route = Route(
            "expert",
            continuing_log,
            (),
            True,
            replace(
                route.classification,
                intent_probabilities={str(i): float(i == Intent.LOG) for i in Intent},
            ),
        )
    continuing = (
        (continuing_log in (action_tools or {}) or continuing_log == "general")
        and (
            choice in ("auto", continuing_log)
            or (continuing_log == "general" and choice in (action_tools or {}))
        )
        and (
            correcting_draft
            or route.classification.intent == Intent.CLARIFY
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
    # "Just had a chicken salad": log it, or look at the data? Asked before any small talk.
    asking_what = bool(
        action_tools
        and route.classification.intent_probabilities
        and route.classification.intent == Intent.CLARIFY
        and route.expert in ("nutrition", "activity")
        and not continuing
        and route.classification.question_type != "coaching"  # "what should I do?" is no meal
        and "?" not in question  # someone asking something has not just told you what they ate
        # "I'm training for a half marathon" is their life, not an entry: no done-verb in it.
        and not (is_statement(said) and not LOGGABLE.search(said))
        and not REACTION.match(said)  # "that seems wrong, I walked more" disputes a figure
    )
    # Hello, thanks, "that's wrong", or telling us about their life: a reply, not a data run.
    chatting = not asking_what and (
        attachment is None
        and not (acting or continuing or reminding or logging_tools or world)
        and route.action in ("expert", "general", "conversation")
        and (
            _certain_talk(said)
            or bool(AFFIRM.match(said))  # a "yes" with no offer before it: nothing to run
            or (
                route.classification.question_type == "chat"
                and "?" not in said
                and (route.action != "conversation" or is_small_talk(said))
            )
        )
    )
    plan = (
        None
        if acting or continuing or reminding or logging_tools or world or chatting or fixed
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
    if missing and plan:
        block = "\n\n".join(part for part in (block, untracked_note(missing)) if part)
    relevant: list[Relevant] = []
    fit, memory_cost, personal_ids = Fit(), Budget(), set()
    if plan and plan.coaching and guidance_mode != "none" and urgent_free(question):
        moment = now or datetime.now(UTC)
        kept = chat.profile if chat else ()
        relevant = rank_memory(question, archive, kept, llm, moment, memory_cost)
        known = {r.text.casefold() for r in relevant}
        relevant = [
            Relevant(text=line, kind="said in this chat", score=1.0)
            for line in told_here(history)
            if line.casefold() not in known
        ] + relevant
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
    # "Why?" straight after an answer that found no change asks to explain nothing.
    if (
        plan
        and route.classification.question_type in ASKS_WHY
        and _asks_why_of_nothing(said, history)
    ):
        false_premise = True
        route = replace(route, consult=())
        plan = replace(plan, guide=PREMISE_GUIDE, tools=("describe", "compare_windows"))
        block = "\n\n".join(part for part in (block, NOTHING_TO_EXPLAIN) if part)
    elif plan and route.classification.question_type in ASKS_WHY and urgent_free(question):
        premise = check_premise(frame, question, route.expert or advisor)
        if premise:
            evidence |= {record.id: record for record in premise.evidence}
            block = "\n\n".join(part for part in (block, premise.text) if part)
            false_premise = not premise.holds
            if false_premise:
                route = replace(route, consult=())
                plan = replace(plan, guide=PREMISE_GUIDE, tools=("describe", "compare_windows"))
            else:
                if route.classification.question_type == "why":
                    records, text = candidate_causes(frame, premise)
                    for record in records:
                        evidence[record.id] = record
                        if record_owner := owner(record.metrics[0]):
                            owners[record.id] = record_owner.name
                    block = "\n\n".join(part for part in (block, text) if part)
                if lined_up := events_during(memory, premise.evidence):
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
    # A broad question ("what changed most?", "why do I feel tired?", "how has life been?") names
    # no metric: code compares every metric first, so the answer is not one area the model chose.
    broad = bool(
        plan
        and not plan.coaching
        and not false_premise
        # Routed to an area they have no data for ("how much protein did I eat?"): the reply that
        # says nothing is logged there is the answer, not an overview of everything else.
        and not (
            route.action == "expert"
            and route.expert in EXPERTS
            and not available(EXPERTS[route.expert], frame)
        )
        and (
            OVERALL.match(said)
            or (
                route.classification.question_type in BROAD_TYPES
                and not asked_metrics(question, list(frame.columns))
                # "Summarise how I've been" routes as a lookup; "what's my average?" stays one.
                and (
                    route.classification.question_type != "lookup"
                    or not any(words.search(question) for words, _, _ in STATISTIC_WORDS)
                )
            )
        )
    )
    if broad:
        records, text = overview_evidence(frame, question, _day(today or now))
        if records:
            for record in records:
                evidence[record.id] = record
                if record_owner := owner(record.metrics[0]):
                    owners[record.id] = record_owner.name
            block = "\n\n".join(part for part in (block, text) if part)
            route = Route("general", None, (), route.routed, route.classification)
            plan = replace(plan, guide=BROAD_GUIDE, tools=BROAD_TOOLS, snapshot=False)
        else:
            broad = False
    if plan and not plan.coaching and (said_before := told_here(history)):
        block = "\n\n".join(part for part in (block, told_block(said_before)) if part)
    if plan:
        visible = sorted(_scope(route) or frame.columns)
        found: list[tuple[list[Evidence], str]] = []
        if plan.snapshot and (lead_on_no_data or route.expert) != "nutrition":
            found.append(snapshot(frame, visible, asked_day(question, today, frame), question))
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
    # The dates its phrases mean, named by code ("last week = Mon Nov 9 to Sun Nov 15"): only for
    # the agent, after routing, so the router and the snapshot read the person's own words.
    local = today if isinstance(today, datetime) else now
    first = frame.index.min().date() if len(frame.index) else None
    asked = with_dates(question, local, first) if isinstance(local, datetime) else question
    # What they said gets ignored far above the question: it has to be there at the point of use.
    if relevant or fit.notes:
        what = "; ".join([*(r.text for r in relevant), *fit.notes])
        asked = f"{asked}\n(What they told you, which the advice has to fit: {what})"
    wanted = asked_count(question) if plan and plan.coaching else 0
    passage_ids = frozenset(e.id for e in retrieved.evidence) if retrieved else frozenset()
    check = (
        personal_check(personal_ids, fit, wanted, passage_ids) if plan and plan.coaching else None
    )
    if plan and asks_future(said) and not plan.coaching:  # "how will I sleep tonight?"
        plan = replace(plan, guide=FUTURE_GUIDE, tools=FUTURE_TOOLS)
    if plan and OVERALL.match(said) and not broad:  # "am I ok?" with too little data to compare
        plan = replace(plan, guide=OVERALL_GUIDE, tools=OVERALL_TOOLS, snapshot=True)
    if plan and route.classification.question_type in STATED_TYPES:
        check = figures_check
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
    elif fixed:
        result = AgentResult(run_id=uuid.uuid4().hex[:12], stop_reason="limits", summary=fixed)
    elif route.action == "refuse":
        # Health-shaped (melatonin to sleep, a symptom): the medical wording; else off topic.
        medical = (
            MEDICAL.search(said)
            or OFF_TOPIC.search(said)
            or any(KeywordRouter._hits(said).values())
            or any(p >= 0.5 for p in route.classification.needs.values())
        )
        wording = MEDICAL_REFUSAL if medical else OFF_TOPIC_REFUSAL
        if history and history[-1].answer.startswith(wording[:40]):  # not the same words twice
            wording = MEDICAL_AGAIN if medical else OFF_TOPIC_AGAIN
        result = AgentResult(run_id=uuid.uuid4().hex[:12], stop_reason="refused", summary=wording)
    elif is_explicit(question) and "?" not in question and not logging_tools:
        # Keeping it is the person's tap on the card the listener raises; no data to look at.
        result = AgentResult(run_id=uuid.uuid4().hex[:12], stop_reason="noted", summary=NOTED)
    elif world:
        refers = history and REFERS_TO_IT.search(said)
        result = answer_world(
            llm, question, outside, guard=guard, earlier=history[-1].question if refers else None
        )
    elif chatting:
        result = chat_reply(
            llm,
            said,
            history,
            guard=guard,
            summary=chat.usable_summary if chat else None,
            profile=chat.profile if chat else (),
        )
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
    elif asking_what:
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
    stopped_early = result.stop_reason in (
        "urgent",
        "refused",
        "noted",
        "chatted",
        "chat_fallback",
        "limits",
    )
    if plan and plan.coaching:
        result.summary = without_filler(result.summary)
        if wanted and not stopped_early:
            _fill_points(llm, result, question, wanted, guard)
    if plan and plan.coaching and result.summary in (NO_ANSWER, ""):
        result.summary = COACHING_NO_ANSWER
    # The honest "not tracked" answer can fail the claim checks, which want a metric: said by
    # code then, never "I couldn't pin that down" (water, a menstrual cycle; 2026-11-16).
    if missing and result.summary in (NO_ANSWER, "", COACHING_NO_ANSWER):
        result.summary, result.claims = UNTRACKED_REPLY.format(thing=missing), []
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
    result.budget.cost_usd += reading_budget.cost_usd
    result.budget.calls += reading_budget.calls
    if typed is not None:
        result.trace.append(
            {
                "type": "request",
                "request": typed.model_dump(mode="json"),
                "state": request_state,
                "cost_usd": reading_budget.cost_usd,
                "model_calls": reading_budget.calls,
            }
        )
    result.trace[:0] = [_context_step(context), _route_step(route)]
    if continuing:
        result.trace[1]["continuing_log_expert"] = continuing_log
    if reminding:
        result.trace[1]["reminding"] = True
    return Answer(route, result, context)
