"""The specialist experts: each owns a set of metrics and answers questions about them.

An expert runs the same investigation loop as the general agent (`run_agent`) with its own prompt,
a toolbox over the metrics it owns plus the ones it reads to explain them, and one extra rule:
**only the owner makes claims about a metric**. A claim about another expert's metric passes only
when every evidence it cites was produced by that expert, through `consult`.

`consult` runs another expert on a narrower question with a smaller budget and hands back its
verified claims and their evidence, which the lead may then cite. **The router decides who may be
consulted** (the other likely topics of a cross-domain question), not the depth and not the lead;
depth only sets the lead's budget, and each allowed consult adds its own on top. Consulted experts
cannot consult in turn, so a question costs at most one lead run and a few short ones.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum

import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from app.agent.agent import (
    DEFAULT_GUIDE,
    SYSTEM_PROMPT,
    AgentResult,
    ExtraTool,
    answer_task,
    run_agent,
)
from app.agent.guard import Guard, GuardError
from app.agent.llm import LLM, Budget
from app.agent.present import label, metric_list
from app.agent.tools import ALWAYS_VISIBLE, Toolbox, evidence_payload
from app.agent.verifier import MENTIONS, Claim
from app.analysis.evidence import Evidence

LOGGING_PROMPT = (
    "\nYou can prepare log drafts even with no historical data. Use only values the "
    "person explicitly supplied. Resolve times like 'just now', 'this morning' or 'yesterday "
    "at lunch' from the current local time and UTC offset at the top of the task, and write "
    "them with that offset. That is the person's own time zone: never ask for it. "
    "A clock time with no day ('at 3 pm') is the latest one that has passed, usually today. "
    "'Just now' with a duration means it has just ended: the end is the current time. "
    "The request so far is in the task: never ask again for something it already says. Prepare "
    "the draft only once you have what it needs; until then just ask for what is missing, every "
    "missing detail in one question. Ask only when a time is truly unclear. "
    "Proposals are not statistics or verified claims. Never infer calories/macros or "
    "measurements. A prepared draft is not logged or sent to Google. Tell the person "
    "it needs review and confirmation; never claim execution. Keep draft values in the "
    "tool result, not in statistical claims or the summary. For mixed requests, analyse "
    "existing history separately; an unconfirmed draft is not in that history. When a message "
    "both logs something and asks something, do both: prepare the draft first, then answer. "
    "For a logging-only request, do not run statistical investigations. After a successful "
    "proposal, immediately call submit_findings with a short, number-free summary saying "
    "the draft needs review, claims=[], and no hypotheses. If details are missing, call "
    "submit_findings with the clarification question as summary and claims=[] instead. "
    "Do not finish with a plain-text message; the app reads the submission tool."
)

CONSULT = "consult"
MAX_CONSULTS = 2
# Model calls a consult must leave the lead, so it can still submit and repair once.
LEAD_RESERVE_CALLS = 3


class Depth(StrEnum):
    QUICK = "quick"  # a small tool budget
    DEEP = "deep"  # more model and tool calls, to test more windows


@dataclass(frozen=True)
class Expert:
    name: str
    owns: tuple[str, ...]
    reads: tuple[str, ...]  # other experts whose metrics it may use to explain its own
    focus: str  # what to look at first, added to the prompt
    notes: str = ""  # guardrails specific to these metrics


EXPERTS: dict[str, Expert] = {
    expert.name: expert
    for expert in (
        Expert(
            "sleep",
            owns=(
                "sleep_minutes",
                "time_in_bed",
                "sleep_efficiency",
                "sleep_score",
                "deep_sleep_minutes",
                "light_sleep_minutes",
                "rem_sleep_minutes",
                "awake_in_bed_minutes",
                "bedtime_hour",
            ),
            reads=("activity",),
            focus="Check bedtime and time in bed before anything else: most changes in time "
            "asleep come from going to bed later or earlier.",
        ),
        Expert(
            "recovery",
            owns=(
                "hrv_ms",
                "resting_hr",
                "respiratory_rate",
                "skin_temp_variation_c",
                "readiness",
                "recovery_score",
                "stress_score",
                "still_minutes",
                "still_hr_above_resting",
            ),
            reads=("sleep", "activity"),
            focus="Look at the nights and training before a change: shorter sleep and hard "
            "training days often show up in HRV and resting heart rate a day or two later.",
            notes="Readiness is Fitbit's own score, kept for comparison; describe it, do not "
            "build on it. The recovery and stress scores are the app's own estimates, built from "
            "other metrics: recovery from last night's HRV, resting heart rate and time asleep; "
            "stress mostly from the heart rate while still and awake, allowing for the day's "
            "exercise. To explain a change in a score, test its inputs. Stress means physical "
            "signs in the data, never how the person feels or a condition.",
        ),
        Expert(
            "activity",
            owns=(
                "steps",
                "distance_km",
                "active_zone_minutes",
                "sedentary_minutes",
                "lightly_active_minutes",
                "moderately_active_minutes",
                "very_active_minutes",
                "calories",
                "cardio_load",
                "strain",
                "hr_zone_light_minutes",
                "hr_zone_moderate_minutes",
                "hr_zone_vigorous_minutes",
                "hr_zone_peak_minutes",
            ),
            reads=("recovery", "sleep"),
            focus="Check wear time first: days the device was barely worn lower every activity "
            "total. Then look for weekday and weekend patterns.",
            notes="Calories burned is a low-confidence estimate: describe only relative changes "
            '("about 15% above your usual"), never claims built on its absolute value. Strain is '
            "the app's own 0 to 21 score of the day's load, from minutes in Fitbit's heart-rate "
            "zones; to explain it, look at the zone minutes and workouts.",
        ),
        # No nutrition columns exist yet; the expert is listed so routing can name it.
        Expert(
            "nutrition",
            owns=(),
            reads=("sleep", "activity"),
            focus="Look at energy and macronutrients before single nutrients.",
        ),
    )
}

# Shared by every expert: each must account for low-wear days, and may say so.
SHARED = ALWAYS_VISIBLE

BUDGETS = {
    Depth.QUICK: Budget(max_calls=6, max_tool_calls=8, max_cost_usd=0.02),
    Depth.DEEP: Budget(max_calls=12, max_tool_calls=20, max_cost_usd=0.05),
}
CONSULT_BUDGET = Budget(max_calls=5, max_tool_calls=6, max_cost_usd=0.015)


def lead_budget(depth: Depth, consults: int, base: Budget | None = None) -> Budget:
    """The depth's budget (or `base`, the question type's), with room for each allowed consult."""
    base = base or BUDGETS[depth]
    return replace(
        base,
        max_calls=base.max_calls + consults * CONSULT_BUDGET.max_calls,
        max_tool_calls=base.max_tool_calls + consults,  # the consult calls themselves
        max_cost_usd=base.max_cost_usd + consults * CONSULT_BUDGET.max_cost_usd,
    )


def owner(metric: str) -> Expert | None:
    return next((e for e in EXPERTS.values() if metric in e.owns), None)


def available(expert: Expert, frame: pd.DataFrame) -> bool:
    """An expert can answer only when at least one of its metrics has data."""
    return any(m in frame.columns and frame[m].notna().any() for m in expert.owns)


def visible_metrics(expert: Expert) -> list[str]:
    """What the expert's tools may compute on: its own metrics and the ones it reads."""
    read = [m for name in expert.reads for m in EXPERTS[name].owns]
    return [*expert.owns, *read]


def _names(metrics) -> str:
    return ", ".join(label(m) for m in metrics) or "none"


def system_prompt(expert: Expert, frame: pd.DataFrame, consultable: list[str]) -> str:
    owned = [m for m in expert.owns if m in frame.columns]
    read = [m for m in visible_metrics(expert) if m in frame.columns and m not in expert.owns]
    lines = [
        SYSTEM_PROMPT,
        f"You are the {expert.name} expert.",
        f"- You make claims only about your metrics: {metric_list(owned)}. Every claim's metric "
        "field must be one of these names before the parentheses, or wear_minutes when data "
        "quality matters.",
        f"- You may use these to explain changes in yours, but not make claims about them: "
        f"{metric_list(read) or 'none'}.",
        f"- {expert.focus}",
    ]
    if expert.notes:
        lines.append(f"- {expert.notes}")
    # Without the owners' metrics the model cannot tell that "HRV" means asking recovery.
    others = [e for e in EXPERTS.values() if e.name != expert.name and available(e, frame)]
    lines.append(
        "- Other experts and the metrics they own: "
        + "; ".join(f"{e.name}: {_names(m for m in e.owns if m in frame.columns)}" for e in others)
        + "."
    )
    if consultable:
        lines.append(
            f"- This question also concerns {', '.join(consultable)}: call {CONSULT} with "
            "that expert and a short question before you answer; never describe a metric no "
            "evidence in this run covers. You may cite the evidence a consult returns, "
            "including in claims about that expert's metrics."
        )
    else:
        lines.append(
            "- When the question is about a metric you cannot see, answer what your metrics show "
            "and say which expert to ask about the rest; never describe that metric yourself."
        )
    return "\n".join(lines)


def ownership_check(expert: Expert, borrowed: dict[str, str]):
    """The claim rule for an expert. `borrowed` maps evidence ids to the expert that made them."""

    def check(claim: Claim) -> list[str]:
        if claim.kind == "guidance":  # a public source's words belong to no expert's metrics
            return []
        if claim.kind == "suggestion" and claim.metric is None:
            return []  # may rest on what they said, which is about no metric
        metric = claim.metric
        if metric is None:
            if claim.kind == "data_quality":
                return []
            return ["say which of your metrics the claim is about"]
        if metric in expert.owns or metric in SHARED:
            return []
        metric_owner = owner(metric)
        if metric_owner and all(borrowed.get(i) == metric_owner.name for i in claim.evidence_ids):
            return []
        whose = f"the {metric_owner.name} expert's metric" if metric_owner else "not your metric"
        return [
            f"{label(metric)} is {whose}: claim only what its owner's evidence shows, or leave "
            "it out"
        ]

    return check


def coverage_check(needed: list[str], evidence: dict[str, Evidence]):
    """Which of the experts a question needs the verified claims do not draw on: none of the
    claims is about one of their metrics or cites evidence that includes one (a correlation
    counts for both of its metrics; a coverage check, which lists every metric, does not)."""

    def uncovered(claims: list[Claim]) -> list[str]:
        seen = {c.metric for c in claims if c.metric}
        for claim in claims:
            for evidence_id in claim.evidence_ids:
                record = evidence.get(evidence_id)
                if record is not None and record.tool != "coverage":
                    seen |= set(record.metrics)
        return [name for name in needed if not seen & set(EXPERTS[name].owns)]

    return uncovered


class ConsultArguments(BaseModel):
    expert: str
    question: str = Field(min_length=1, max_length=300)


@dataclass
class _Consults:
    """The consult tool for one lead run: runs the other expert and lends its evidence."""

    llm: LLM
    frame: pd.DataFrame
    lead: Expert
    toolbox: Toolbox  # the lead's: consulted evidence is added so it can be cited
    budget: Budget  # the lead's: consults are charged to it
    today: date | None
    allowed: tuple[str, ...]  # chosen by the router
    borrowed: dict[str, str]
    consulted: list[str]
    verified: dict[str, list[Claim]] = field(default_factory=dict)  # each consult's claims
    context: str = ""  # the conversation, so a consulted expert knows what is being talked about

    def experts(self) -> list[str]:
        return [
            name
            for name in self.allowed
            if name != self.lead.name and name in EXPERTS and available(EXPERTS[name], self.frame)
        ]

    def tool(self) -> ExtraTool:
        parameters = ConsultArguments.model_json_schema()
        parameters.pop("title", None)
        parameters["properties"]["expert"]["enum"] = self.experts()
        return ExtraTool(
            CONSULT,
            "Ask another expert about its metrics. Returns its verified claims and their "
            "evidence, which you may cite.",
            parameters,
            self.run,
        )

    def _refuse(self, message: str) -> tuple[str, dict]:
        return json.dumps({"error": message}), {"error": message}

    def run(self, arguments: dict | None) -> tuple[str, dict]:
        try:
            args = ConsultArguments.model_validate(arguments or {})
        except ValidationError:
            return self._refuse("Give an expert and a short question.")
        if args.expert not in self.experts():
            return self._refuse(f"Consult one of: {', '.join(self.experts())}.")
        if args.expert in self.consulted:
            return self._refuse(f"You already consulted the {args.expert} expert.")
        calls_left = self.budget.max_calls - self.budget.calls - LEAD_RESERVE_CALLS
        cost_left = (self.budget.max_cost_usd - self.budget.cost_usd) / 2
        if calls_left < 2:
            return self._refuse("Not enough budget left to consult; submit with what you have.")

        child = replace(
            CONSULT_BUDGET,
            max_calls=min(CONSULT_BUDGET.max_calls, calls_left),
            max_cost_usd=min(CONSULT_BUDGET.max_cost_usd, cost_left),
        )
        result = ask_expert(
            self.llm,
            self.frame,
            args.expert,
            args.question,
            depth=Depth.QUICK,
            today=self.today,
            budget=child,
            context=self.context,
        )
        self.consulted.append(args.expert)
        self.verified[args.expert] = list(result.claims)
        self.budget.calls += child.calls
        self.budget.cost_usd += child.cost_usd

        lent = result.cited_evidence
        for evidence_id, evidence in lent.items():
            self.toolbox.evidence[evidence_id] = evidence
            self.borrowed[evidence_id] = args.expert
        content = {
            "expert": args.expert,
            "summary": result.summary,
            "claims": [claim.model_dump() for claim in result.claims],
            "evidence": [evidence_payload(e) for e in lent.values()],
        }
        if not result.claims:
            content["note"] = "The expert found nothing it could verify."
        step = {
            "expert": args.expert,
            "question": args.question,
            "run_id": result.run_id,
            "stop_reason": result.stop_reason,
            "claims": len(result.claims),
            "cost_usd": child.cost_usd,
            "steps": result.trace,
        }
        return json.dumps(content), step


def ask_expert(
    llm: LLM,
    frame: pd.DataFrame,
    name: str,
    question: str,
    *,
    depth: Depth = Depth.QUICK,
    consult: Iterable[str] = (),
    today: date | None = None,
    budget: Budget | None = None,
    context: str = "",
    evidence: dict[str, Evidence] | None = None,
    owners: dict[str, str] | None = None,
    guard: Guard | None = None,
    needs: Iterable[str] = (),
    extra_tools: list[ExtraTool] = (),
    allow_logging: bool = False,
    action_prompt: str = "",
    tools: tuple[str, ...] | None = None,
    guide: str | None = None,
    widen=None,
    answer_check: Callable[[list[Claim], str], list[str]] | None = None,
) -> AgentResult:
    """Has one expert answer a question about the person's data, with verified claims.

    `consult` lists the experts the router allows it to consult, at most `MAX_CONSULTS`.
    `context`, `evidence` and `owners` come from `context.build`: the conversation block, the
    earlier evidence the run may cite, and which expert produced each, so the ownership rule treats
    an earlier answer's evidence like a consult's."""
    expert = EXPERTS[name]
    allowed = tuple(dict.fromkeys(c for c in consult if c != name))[:MAX_CONSULTS]
    budget = budget or lead_budget(depth, len(allowed))
    # Preparing a log or a reminder needs no history ("remind me to log breakfast").
    if not available(expert, frame) and not allow_logging and not action_prompt:
        return AgentResult(
            run_id="",
            stop_reason="unavailable",
            expert=name,
            summary=(
                "You haven't logged any food yet, so there's nothing for me to look at. Tell me "
                "what you ate and I'll set it up for you."
                if name == "nutrition"
                else f"I don't have any {name} data for you yet."
            ),
            budget=budget,
        )
    # The other areas the router says this needs can be correlated with directly: cheaper than a
    # consult, and a claim about them still needs their owner's evidence.
    drivers = [m for other in allowed if other in EXPERTS for m in EXPERTS[other].owns]
    toolbox = Toolbox(frame, [*visible_metrics(expert), *drivers], tools)
    toolbox.evidence.update(evidence or {})
    steps: list[dict] = []
    borrowed: dict[str, str] = dict(owners or {})
    consults = _Consults(
        llm, frame, expert, toolbox, budget, today, allowed, borrowed, [], context=context
    )
    consultable = consults.experts()
    extras = ([consults.tool()] if consultable else []) + list(extra_tools)
    if widen is not None:
        extras.append(widen(toolbox, budget, steps))
    prompt = system_prompt(expert, frame, consultable)
    if allow_logging:
        prompt += LOGGING_PROMPT
    prompt += action_prompt
    coverage = (
        coverage_check(
            [n for n in needs if n in EXPERTS and available(EXPERTS[n], frame)], toolbox.evidence
        )
        if needs
        else None
    )
    result = run_agent(
        llm,
        toolbox,
        answer_task(toolbox, question, today, context, guide or DEFAULT_GUIDE),
        system_prompt=prompt,
        budget=budget,
        extra_tools=extras,
        claim_check=ownership_check(expert, borrowed),
        guard=guard,  # consulted runs are not guarded: only the lead's text is shown
        coverage=coverage,
        answer_check=answer_check,
    )
    carried = carry_consulted(result, consults.verified, borrowed, guard)
    if carried and coverage:
        result.uncovered = coverage(result.claims)
    result.expert = name
    result.consulted = consults.consulted
    result.trace += steps
    return result


def carry_consulted(
    result: AgentResult,
    verified: dict[str, list[Claim]],
    borrowed: dict[str, str],
    guard: Guard | None,
) -> list[Claim]:
    """Adds a consulted expert's verified claims when the summary draws on that expert's metrics
    but the lead cited none of its claims, so the evidence shown matches what the answer says.

    The claims were verified by their owner; their text is shown now, so the guard reads it.
    """
    cited = {i for claim in result.claims for i in claim.evidence_ids}
    carried: list[Claim] = []
    for name, claims in verified.items():
        owned = set(EXPERTS[name].owns)
        mentioned = {m for m, pattern in MENTIONS.items() if pattern.search(result.summary)}
        if not claims or any(borrowed.get(i) == name for i in cited) or not owned & mentioned:
            continue
        carried += claims
    if carried and guard:
        try:
            flags = guard.judge([claim.text for claim in carried]).flagged
        except GuardError as exc:
            result.trace.append({"type": "guard", "error": str(exc)})
        else:
            carried = [claim for claim, flag in zip(carried, flags, strict=True) if not flag]
    result.claims += carried
    if carried:
        result.trace.append({"type": "carried", "claims": len(carried)})
    return carried
