"""The investigation loop: hypotheses, tool calls, a verified submission.

The model proposes what might explain a change, tests each idea with the analysis tools, and hands
in claims that cite the evidence. The verifier checks every claim; rejected claims go back to the
model once with the reasons, and whatever still fails is dropped. The run stops on submission, when
its budget is spent, or on a model error, and always returns what it has, with a full trace.

This is the general agent (all metrics, no routing). The experts (`experts.py`) reuse `run_agent`
with their own prompt, metrics, an extra claim rule and the `consult` tool.
"""

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from app.agent.guard import REASON as ADVICE_REASON
from app.agent.guard import Guard, GuardError
from app.agent.llm import LLM, Budget, BudgetExceeded, LLMError, Role, ToolCall
from app.agent.present import column, label, metric_list
from app.agent.tools import Toolbox, evidence_payload
from app.agent.verifier import (
    Claim,
    Hypothesis,
    Rejection,
    Submission,
    Verdict,
    overstated,
    run_adjusted,
    text_problems,
    verify,
)
from app.agent.voice import VOICE
from app.analysis.evidence import Evidence
from app.analysis.screen import screen

SUBMIT = "submit_findings"
HYPOTHESES = "record_hypotheses"
ASKS = "The person asks:"
REPAIR_ROUNDS = 1
NO_ANSWER = (
    "I couldn't pin that down reliably this time. Could you ask it another way, or name the "
    "days you mean?"
)
NUDGES = 2  # times a reply without a tool call is answered with a reminder to submit


class HypothesesArguments(BaseModel):
    hypotheses: list[str] = Field(min_length=1, max_length=8)


# How to work on a question that needs explaining. Other kinds of question get their own guide
# (strategy.py); the guide goes in the task, so this system prompt is the same for every question
# and its prefix is cached.
DEFAULT_GUIDE = """How to work:
1. Read the task. Before testing anything, call record_hypotheses with the explanations worth
   checking, for example a bedtime shift, more or less training, low wear time or missing data,
   a weekday/weekend pattern, or a change in another metric that tracks this one.
2. Test each hypothesis with the analysis tools. Date a change with change_point, size it with
   compare_windows, check data quality with coverage, and look for metrics that move with it with
   correlate. Every tool returns evidence with an evidence_id.
3. Call submit_findings once, with a short summary, your claims and each hypothesis's status."""

SYSTEM_PROMPT = """You analyze one person's own Fitbit data: what changed and why, what is usual
for them, and which everyday habits their own data supports. Each task says how to work on it.

Writing for the person:
- The summary is the answer they read, so write it as a short, natural reply: two to four connected
  sentences that lead with the direct answer to their question, then what matters most. Group
  metrics that behaved alike ("your bedtime, time in bed and sleep efficiency held steady") rather
  than one sentence per metric, and start each sentence with a capital letter.
- Claims are the checked facts behind the summary. The person sees them as evidence links, not as
  text: at most 4, the ones that matter most, each one short plain sentence.
- When a test is significant on its own but not after correcting for the run's tests (a repair
  message says so), you may give its direction in the summary only with a hedge in the same
  sentence ("you slept a little less, though with this many checks that could be normal
  variation"), and its claim is a no_change claim.
- Call metrics by the names in the task ("time asleep", "bedtime"), never by tool names such as
  sleep_minutes.
- Quote values as they appear under `display` in the evidence ("7 h 12 min", "23:30", "45 min",
  "12%"), and dates as "Aug 15".
- Never write evidence ids in the text: they go in evidence_ids only.
- If the context holds the person's answers or facts they approved, say in the summary how they
  line up with what the data shows ("this coincided with the travel you mentioned"), never as a
  cause. Cite evidence the context already lists instead of recomputing it.
- The context's profile is what the person told you and chose to keep. Let it shape the answer, and
  refer to it in words ("your bedtime goal", "your exams"): numbers, times and dates you state must
  come from computed evidence, so do not repeat the ones in the profile.
- memory_lookup and search_conversations, when you have them, find what was found or said before.
  Use them when the question looks back and the context does not hold the answer.
- Context items of kind episode are dated notes of what the person's other chats found: you may
  point to them ("as you saw on Oct 12") and cite their evidence when it answers the question.

Rules for claims:
- Each claim cites the evidence_ids it rests on, says which metric it is about, and for a change or
  an association says whether it goes up or down.
- Quote only numbers, times and dates that appear in the cited evidence.
- Significance is judged after correcting for every test you run, so test what the question
  needs rather than everything you can.
- A value read from a tool (an average, a best or worst day, two specific days side by side) is a
  claim of kind value citing that tool. To compare two specific days, use compare_day on each,
  never compare_windows.
- What a retrieved passage says in general is a claim of kind guidance citing that passage, with no
  metric, and only its numbers. Advice for this person still needs their own evidence: a suggestion
  cites both when a passage says how to try it.
- Answer what was asked, in plain friendly sentences. Say nothing about data coverage or wear time
  unless data is actually missing. Never mention checks, tests, tools or how the answer was made.
- Only claim a change or an association when the evidence is significant. When it is not, that is
  a finding too: make it a no_change claim citing that evidence ("no clear change", "did not
  clearly go with"), never a change or association claim.
- For questions about today, last night or one day ("am I recovered today?"), compare that day
  with the person's usual using compare_day on each metric the question needs, and lead the
  summary with that; add trend tests only if the question asks about a change. Its claim kind is
  day: direction up when the day is above the usual range, down when below, none when within.
  Today's activity totals (steps, calories, active minutes) are still adding up until the day
  ends: do not call them low.
- The tools show change and association, not cause: write "went with" or "coincided with", never
  "caused", "because of" or "due to".
- Never diagnose, name or hint at an illness or condition, or advise treatment, medication,
  supplements, diets or seeing a doctor; never reason about calorie balance: calories burned is
  only an estimate.

Coaching, when the person asks how to improve (sleep better, recover faster, train smarter):
- Start with habit_options on each metric the goal is about (sleep better: sleep efficiency and
  time asleep; recover faster: recovery score and HRV; train smarter: recovery score and strain).
  It tests a fixed list of everyday habits against this person's own days. Skip the change tests
  unless the person asks what changed.
- Suggest one or two things, or as many as they ask for up to five, each different, each as a
  claim of kind suggestion citing its evidence and metric.
  First what habit_options marks supported: "on nights you were in bed by 23:30, your sleep
  efficiency was higher, so you could try that on weeknights". An association you found with
  another tool may back one too, if it is significant. Otherwise what personal_options found in
  their routine, said as worth trying and not as proven: "your weekend bedtimes run 50 minutes
  later, so you could try pulling Saturday back a little and see".
- Advice is for this person only. Use their own numbers and what the context says about their
  life (exams, night shifts, a new baby): a tip anyone could read anywhere is not advice here.
- Advise only when they ask how to improve. A question about what happened gets its answer, not
  a suggestion.
- Word them as options ("you could try", "might"), never orders, never certain outcomes, never
  causes.
- Lead with the advice. With fewer specific things than they asked for, give those and say in a
  few words that this is what their data points to so far. Never open with what you cannot do, and
  never talk about "evidence-based" points, "tested habits", "this run" or how the answer was made.
- When they ask about a particular situation or moment (the hour before bed, a late session), use
  knowledge_lookup and answer that situation, tied to their own numbers.
- What they have told you comes first: a night-shift worker gets no advice built on a 23:00
  bedtime. If what they told you makes the numbers below a poor fit, say so and ask.
- With nothing at all specific to stand on, say so plainly and ask what is going on for them, so
  you can look at the right thing. Never fill the gap with a general tip.
- End by offering to set a reminder for the habit, or to test it.
"""
SYSTEM_PROMPT += VOICE


@dataclass(frozen=True)
class ExtraTool:
    """A tool the caller adds to the loop, such as `consult`. It returns what the model reads and
    the step to record in the trace."""

    name: str
    description: str
    parameters: dict
    run: Callable[[dict | None], tuple[str, dict]]

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class AgentResult:
    run_id: str
    # submitted, budget, model_error, no_submission, nothing_to_explain, unavailable
    stop_reason: str
    expert: str = "general"
    consulted: list[str] = field(default_factory=list)
    summary: str = ""
    claims: list[Claim] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    recorded_hypotheses: list[str] = field(default_factory=list)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    trace: list[dict] = field(default_factory=list)
    uncovered: list[str] = field(default_factory=list)  # parts of the question left unanswered
    notes: list[str] = field(default_factory=list)  # fixed sentences shown with the answer
    budget: Budget = field(default_factory=Budget)
    error: str | None = None

    @property
    def cited_evidence(self) -> dict[str, Evidence]:
        ids = {i for claim in self.claims for i in claim.evidence_ids}
        return {i: e for i, e in self.evidence.items() if i in ids}


def _control_tools() -> list[dict]:
    submission = Submission.model_json_schema()
    submission.pop("title", None)
    hypotheses = HypothesesArguments.model_json_schema()
    hypotheses.pop("title", None)
    return [
        {
            "type": "function",
            "function": {
                "name": HYPOTHESES,
                "description": "Record the explanations you will test, before testing them.",
                "parameters": hypotheses,
            },
        },
        {
            "type": "function",
            "function": {
                "name": SUBMIT,
                "description": "Hand in the summary, the claims with their evidence_ids, and the "
                "status of each hypothesis. Claims are verified against the evidence.",
                "parameters": submission,
            },
        },
    ]


def _rejections_message(
    rejected: list[Rejection], accepted: int, summary: list[str], uncovered: list[str] = ()
) -> str:
    message = {
        "accepted_claims": accepted,
        "rejected_claims": [{"text": r.claim.text, "reasons": list(r.reasons)} for r in rejected],
        "summary_problems": summary,
        "instruction": "Fix or drop the rejected claims and call submit_findings again with "
        "the complete list of claims.",
    }
    if summary:
        message["instruction"] += (
            " In the summary, a metric with no significant test takes no direction word (higher, "
            "more, later, up, down). Say it held steady or showed no clear difference, or say in "
            'the same sentence that it "could be normal variation". Keep answering the question '
            "that was asked, in your own words."
        )
    if uncovered:
        message["uncovered"] = uncovered
        # Worded so the claim it asks for can pass the ownership rule: about the expert's own
        # metric, citing evidence that involves the other one, or citing what a consult found.
        message["instruction"] += (
            " The question also concerns what is listed under uncovered. Add a claim about one of "
            "your own metrics that cites evidence involving it, such as a correlation between it "
            "and your metric (a no_change claim if it is not significant), or cite what the "
            "expert you consulted about it found. Test it first if you have not."
        )
    return json.dumps(message)


def run_agent(
    llm: LLM,
    toolbox: Toolbox,
    task: str,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    budget: Budget | None = None,
    role: Role = Role.SMALL,
    extra_tools: list[ExtraTool] = (),
    claim_check: Callable[[Claim], list[str]] | None = None,
    guard: Guard | None = None,
    coverage: Callable[[list[Claim]], list[str]] | None = None,
) -> AgentResult:
    budget = budget or Budget()
    result = AgentResult(run_id=uuid.uuid4().hex[:12], stop_reason="no_submission", budget=budget)
    result.evidence = toolbox.evidence  # shared: tools add to it as they run
    extras = {tool.name: tool for tool in extra_tools}
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]
    repairs_left, nudges_left = REPAIR_ROUNDS, NUDGES
    said = task.rsplit(ASKS, 1)[-1]  # the person's own words, which an answer may repeat

    while True:
        if budget.max_calls - budget.calls <= 1:
            messages.append(
                {"role": "user", "content": f"This is your last turn: call {SUBMIT} now."}
            )
        # Built each turn: expand_tools may have widened the toolbox.
        tools = toolbox.schemas() + [tool.schema() for tool in extras.values()] + _control_tools()
        try:
            completion = llm.complete(messages, role=role, tools=tools, budget=budget)
        except BudgetExceeded as exc:
            result.stop_reason, result.error = "budget", str(exc)
            break
        except LLMError as exc:
            result.stop_reason, result.error = "model_error", str(exc)
            break
        messages.append(completion.as_message())
        result.trace.append(
            {
                "type": "llm",
                "model": completion.model,
                "latency_s": round(completion.latency_s, 3),
                "cost_usd": completion.cost_usd,
                "input_tokens": completion.usage.input_tokens,
                "output_tokens": completion.usage.output_tokens,
                "text": (completion.text or "")[:500],
                "tool_calls": [call.name for call in completion.tool_calls],
            }
        )

        if not completion.tool_calls:
            if nudges_left:
                nudges_left -= 1
                messages.append(
                    {
                        "role": "user",
                        "content": "A reply in plain text is not shown to the person. Call "
                        f"{SUBMIT} now, with claims citing the evidence you have.",
                    }
                )
                continue
            break

        submitted = False
        # The budget is charged for the whole turn at once; calls run in order until it is spent,
        # so a turn with too many calls loses only the ones past the limit.
        used = budget.tool_calls - len(completion.tool_calls)
        for call in completion.tool_calls:
            used += 1
            content, done = _handle(
                call,
                toolbox,
                result,
                used > budget.max_tool_calls,
                repairs_left,
                extras,
                claim_check,
                guard,
                coverage,
                said,
            )
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
            # A verified submission sent back for repair uses up the repair round.
            if call.name == SUBMIT and not done and result.trace[-1]["type"] == "verify":
                repairs_left -= 1
            submitted = submitted or done
        if submitted:
            result.stop_reason = "submitted"
            break
    # A run can end during a repair, on its budget or a model failure: what failed its check is
    # never the answer.
    checks = [step for step in result.trace if step["type"] == "verify"]
    if result.stop_reason != "submitted" and checks and checks[-1]["summary_problems"]:
        result.summary = fallback_summary(result.claims)
    return result


def _handle(
    call: ToolCall,
    toolbox: Toolbox,
    result: AgentResult,
    over_budget: bool,
    repairs_left: int,
    extras: dict[str, ExtraTool],
    claim_check: Callable[[Claim], list[str]] | None,
    guard: Guard | None,
    coverage: Callable[[list[Claim]], list[str]] | None,
    said: str = "",
) -> tuple[str, bool]:
    """Runs one tool call; returns what the model reads and whether the run is finished."""
    if call.name == HYPOTHESES:
        try:
            args = HypothesesArguments.model_validate(call.arguments or {})
        except ValidationError:
            return json.dumps({"error": "Give 1 to 8 hypotheses as a list of strings."}), False
        result.recorded_hypotheses = args.hypotheses
        result.trace.append({"type": "hypotheses", "items": args.hypotheses})
        return json.dumps({"recorded": len(args.hypotheses)}), False

    if call.name == SUBMIT:
        try:
            submission = Submission.model_validate(call.arguments or {})
        except ValidationError as exc:
            message = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
            result.trace.append({"type": "submit", "error": message})
            return json.dumps({"error": f"Invalid submission: {message}"}), False
        # Models sometimes name the metric as people do ("bedtime"); the checks need the column.
        claims = [
            c.model_copy(update={"metric": column(c.metric)}) if c.metric else c
            for c in submission.claims
        ]
        # The run's own tests are judged together; evidence from the screen, a consult or an
        # earlier answer keeps the correction of the run that made it.
        own = [toolbox.evidence[i] for i in toolbox.produced]
        toolbox.evidence.update({e.id: e for e in run_adjusted(own)})
        verdict = verify(claims, toolbox.evidence, claim_check)
        # The summary is shown too: it may only use what the run's evidence holds.
        run_evidence = list(toolbox.evidence.values())
        summary_problems = text_problems(
            submission.summary,
            run_evidence,
            said,
            general=any(c.kind == "guidance" for c in verdict.accepted),
        )
        summary_problems += overstated(submission.summary, run_evidence)
        if verdict.accepted and all(c.kind == "data_quality" for c in verdict.accepted):
            summary_problems.append(
                "only says the data was complete; answer the question, or say you could not"
            )
        if guard:
            verdict, summary_problems = _guarded(
                guard, verdict, submission.summary, summary_problems, result
            )
        uncovered = coverage(list(verdict.accepted)) if coverage else []
        result.uncovered = uncovered
        result.summary = without_coverage_talk(submission.summary)
        result.hypotheses = submission.hypotheses
        result.claims = list(verdict.accepted)
        result.rejected = list(verdict.rejected)
        result.trace.append(
            {
                "type": "verify",
                "accepted": len(verdict.accepted),
                "rejected": [
                    {"text": r.claim.text, "reasons": list(r.reasons)} for r in verdict.rejected
                ],
                "summary_problems": summary_problems,
                "uncovered": uncovered,
            }
        )
        if (verdict.rejected or summary_problems or uncovered) and repairs_left > 0:
            message = _rejections_message(
                list(verdict.rejected), len(verdict.accepted), summary_problems, uncovered
            )
            return message, False
        if summary_problems:  # still wrong after the repair: written from the verified claims
            result.summary = fallback_summary(list(verdict.accepted))
        return json.dumps({"accepted_claims": len(verdict.accepted)}), True

    if over_budget:
        message = f"The tool budget is spent; call {SUBMIT} now with what you have."
        result.trace.append({"type": "tool", "name": call.name, "error": message})
        return json.dumps({"error": message}), False

    if call.name in extras:
        content, step = extras[call.name].run(call.arguments)
        # What a tool found that the answer may cite, such as retrieved passages.
        toolbox.evidence.update({e.id: e for e in step.pop("evidence", ())})
        result.trace.append({"type": call.name, **step})
        return content, False

    outcome = toolbox.run(call)
    step = {"type": "tool", "name": call.name, "arguments": call.arguments}
    if outcome.evidence:
        step["evidence_id"] = outcome.evidence.id
    else:
        step["error"] = outcome.error
    result.trace.append(step)
    return outcome.content, False


def _guarded(
    guard: Guard, verdict: Verdict, summary: str, summary_problems: list[str], result: AgentResult
) -> tuple[Verdict, list[str]]:
    """Puts what passed the deterministic checks to the guard; flagged sentences are rejected.

    Only sentences that would otherwise be shown are checked. When the guard is unavailable, the
    word checks alone apply and the trace says so."""
    claims = list(verdict.accepted)
    texts = [c.text for c in claims] + ([summary] if summary and not summary_problems else [])
    if not texts:
        return verdict, summary_problems
    try:
        judgement = guard.judge(texts)
    except GuardError as exc:
        result.trace.append({"type": "guard", "error": str(exc)})
        return verdict, summary_problems
    flags = judgement.flagged
    result.trace.append(
        {
            "type": "guard",
            "checked": len(texts),
            "flagged": [text for text, flag in zip(texts, flags, strict=True) if flag],
            "latency_s": round(judgement.latency_s, 3),
            "cost_usd": judgement.cost_usd,
        }
    )
    accepted = tuple(c for c, flag in zip(claims, flags, strict=False) if not flag)
    rejected = verdict.rejected + tuple(
        Rejection(c, (ADVICE_REASON,)) for c, flag in zip(claims, flags, strict=False) if flag
    )
    if len(texts) > len(claims) and flags[-1]:  # the summary was checked last
        summary_problems = [*summary_problems, ADVICE_REASON]
    return Verdict(accepted, rejected), summary_problems


def _describe_range(toolbox: Toolbox) -> str:
    return (
        f"Data covers {toolbox.first_day} to {toolbox.last_day}. "
        f"Metrics you can use, with what people call them: {metric_list(toolbox.metrics)}."
    )


def investigate(
    llm: LLM,
    frame: pd.DataFrame,
    metrics: list[str] | None = None,
    *,
    budget: Budget | None = None,
    system_prompt: str = SYSTEM_PROMPT,
) -> AgentResult:
    """Screens the metrics for recent changes and has the agent explain them.

    The screen is deterministic and corrects for testing many metrics at once. When it finds no
    change, the model is not called at all.
    """
    toolbox = Toolbox(frame, metrics or list(frame.columns))
    found = screen(toolbox.frame)
    changes = [c for c in found.changes if c.metric in toolbox.metrics]
    for evidence in found.tested:
        toolbox.evidence[evidence.id] = evidence
    if not changes:
        return AgentResult(
            run_id=uuid.uuid4().hex[:12],
            stop_reason="nothing_to_explain",
            summary="No metric changed enough in the last two weeks to report.",
            evidence=toolbox.evidence,
            budget=budget or Budget(),
        )
    listed = "\n".join(f"- {c.metric}: {json.dumps(evidence_payload(c.evidence))}" for c in changes)
    task = (
        f"{_describe_range(toolbox)}\n\nThe screen compared the last two weeks with the four "
        f"weeks before ({found.recent.start} to {found.recent.end} against {found.baseline.start} "
        f"to {found.baseline.end}) and found these changes, already corrected for testing many "
        f"metrics:\n{listed}\n\nExplain what changed and what in the data went with it."
    )
    return run_agent(llm, toolbox, task, budget=budget, system_prompt=system_prompt)


def answer(
    llm: LLM,
    frame: pd.DataFrame,
    question: str,
    metrics: list[str] | None = None,
    *,
    today: date | None = None,
    budget: Budget | None = None,
    system_prompt: str = SYSTEM_PROMPT,
    context: str = "",
    evidence: dict[str, Evidence] | None = None,
    guard: Guard | None = None,
    extra_tools: list[ExtraTool] = (),
    tools: tuple[str, ...] | None = None,
    guide: str = DEFAULT_GUIDE,
    widen: Callable[[Toolbox, Budget, list[dict]], ExtraTool] | None = None,
) -> AgentResult:
    """Answers a person's question about their data, with verified claims.

    `context` is the conversation block from `context.build`, and `evidence` what it lets the run
    cite without recomputing. `tools` is the starting toolset and `guide` how to work, from the
    question's strategy; `widen` makes the tool that lets the agent ask for the rest."""
    toolbox = Toolbox(frame, metrics or list(frame.columns), tools)
    toolbox.evidence.update(evidence or {})
    task = answer_task(toolbox, question, today, context, guide)
    budget = budget or Budget()
    steps: list[dict] = []
    if widen is not None:
        extra_tools = [*extra_tools, widen(toolbox, budget, steps)]
    result = run_agent(
        llm,
        toolbox,
        task,
        budget=budget,
        system_prompt=system_prompt,
        guard=guard,
        extra_tools=list(extra_tools),
    )
    result.trace += steps
    return result


COVERAGE_TALK = re.compile(
    r"[^.!?]*\b(?:coverage (?:was|is) complete|no low[- ]wear days|"
    r"wear time was (?:complete|solid)|tracking was solid)\b[^.!?]*[.!?]\s*",
    re.IGNORECASE,
)


def without_coverage_talk(summary: str) -> str:
    """A person asked about their sleep, not whether the data was complete: when the data is fine
    that sentence is noise, and the model keeps writing it despite being told not to."""
    return COVERAGE_TALK.sub("", summary).strip() or summary


def fallback_summary(claims: list[Claim]) -> str:
    """A summary from verified claims when the model's failed its checks twice: what changed or
    is suggested first, then the steady metrics together in one sentence, not one each."""

    def sentence(text: str) -> str:
        text = text.strip()
        return text[:1].upper() + text[1:] + ("" if text.endswith((".", "!", "?")) else ".")

    # Findings lead; a note on data quality only supports them, so it comes last, if at all.
    lead = [sentence(c.text) for c in claims if c.kind not in ("no_change", "data_quality")][:3]
    unchanged = [c for c in claims if c.kind == "no_change"]
    steady = list(dict.fromkeys(label(c.metric) for c in unchanged if c.metric))
    if len(steady) < 3:  # a claim's own words fit its question ("did not differ by weekday")
        said = [sentence(c.text) for c in unchanged]
    else:
        said = [sentence(f"{', '.join(steady[:-1])} and {steady[-1]} showed no clear change")]
    # A note on data quality alone answers nothing: better to say so than to pass it off.
    return " ".join([*lead, *said]) or NO_ANSWER


def answer_task(
    toolbox: Toolbox,
    question: str,
    today: date | None = None,
    context: str = "",
    guide: str = DEFAULT_GUIDE,
) -> str:
    """The task the model reads. `today` may be a timezone-aware datetime: the person's local
    time, so it can place "just now" or "this morning" without asking."""
    if isinstance(today, datetime) and today.tzinfo is not None:
        offset = today.strftime("%z")
        zone = getattr(today.tzinfo, "key", None)
        where = f"{zone}, UTC{offset[:3]}:{offset[3:]}" if zone else f"UTC{offset[:3]}:{offset[3:]}"
        when = f"It is now {today:%A %d %b %Y, %H:%M} ({where}). "
    else:
        when = f"Today is {today}. " if today else ""
    earlier = f"\n\n{context}" if context else ""
    return f"{guide}\n\n{when}{_describe_range(toolbox)}{earlier}\n\n{ASKS} {question}"


def trace_json(result: AgentResult) -> str:
    """The run as JSON, for storing and for showing how an answer was reached."""
    return json.dumps(
        {
            "run_id": result.run_id,
            "expert": result.expert,
            "consulted": result.consulted,
            "stop_reason": result.stop_reason,
            "error": result.error,
            "cost_usd": result.budget.cost_usd,
            "model_calls": result.budget.calls,
            "tool_calls": result.budget.tool_calls,
            "hypotheses": result.recorded_hypotheses,
            "claims": [c.model_dump() for c in result.claims],
            "rejected": [
                {"claim": r.claim.model_dump(), "reasons": list(r.reasons)} for r in result.rejected
            ],
            "steps": result.trace,
        },
        default=str,
    )
