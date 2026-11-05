"""How the agent works on each kind of question: a plan in code, which the agent may widen once.

The router's one Jev call also answers the question's type. Each type gets a starting set of tools
(the data tools first; outside tools only where they belong), a budget, a short "how to work"
guide placed in the task (the system prompt stays the same for every question, so its prefix is
cached), and up-front evidence: a snapshot of last night and today against the person's usual
range for `day`, `lookup` and `coaching`, and for `coaching` the habits their own data supports,
run by code before the model starts. Only `why` and `change` record hypotheses.

The starting set is not a cage: `expand_tools` (once per answer, with a reason kept in the trace)
gives the agent every tool and one more budget step when its first look is not enough.
"""

import json
from dataclasses import dataclass, replace
from datetime import timedelta

import pandas as pd

from app.agent.agent import DEFAULT_GUIDE, ExtraTool
from app.agent.llm import Budget
from app.agent.present import label
from app.agent.strategy_types import DEFAULT_TYPE
from app.agent.tools import TOOLS, Toolbox, evidence_payload
from app.analysis.coaching import habit_options
from app.analysis.day import compare_day
from app.analysis.evidence import Evidence, ToolError, Window

EXPAND = "expand_tools"
SNAPSHOT_METRICS = (
    "sleep_minutes",
    "sleep_efficiency",
    "bedtime_hour",
    "recovery_score",
    "resting_hr",
    "hrv_ms",
    "steps",
    "strain",
    "stress_score",
)
# The metrics a coaching goal is about, by the expert that leads.
GOALS = {
    "sleep": ("sleep_efficiency", "sleep_minutes"),
    "recovery": ("recovery_score", "hrv_ms"),
    "activity": ("recovery_score", "steps"),
    "nutrition": (),
    None: ("sleep_efficiency", "recovery_score"),
}
COACHING_DAYS = 60
TEST_TOOLS = ("compare_windows", "change_point", "trend", "correlate", "weekday_split", "coverage")


@dataclass(frozen=True)
class Strategy:
    tools: tuple[str, ...]  # the starting set; expand_tools gives the rest
    guide: str
    budget: Budget
    snapshot: bool = False
    coaching: bool = False
    deepens: bool = False  # a deep answer gets twice the budget
    memory: bool = True  # may search memory and past chats; a question about one day has no need


_WHY = DEFAULT_GUIDE

STRATEGIES: dict[str, Strategy] = {
    "day": Strategy(
        tools=("compare_day", "usual_ranges", "coverage"),
        guide="How to work: the snapshot below already compares the latest day with the usual "
        "range, as evidence you may cite. Answer from it if it covers the question; otherwise use "
        "compare_day for the metrics it lacks. No hypotheses. Then call submit_findings.",
        budget=Budget(max_calls=3, max_tool_calls=4, max_cost_usd=0.01),
        snapshot=True,
        memory=False,
    ),
    "lookup": Strategy(
        tools=("describe", "rank_days", "usual_ranges", "compare_day", "coverage", "checkins"),
        guide="How to work: answer the value asked for with the fewest tool calls (the snapshot "
        "below may already cover it). No hypotheses. Then call submit_findings.",
        budget=Budget(max_calls=3, max_tool_calls=4, max_cost_usd=0.01),
        snapshot=True,
    ),
    "change": Strategy(
        tools=("compare_windows", "change_point", "trend", "coverage", "describe"),
        guide=_WHY,
        budget=Budget(max_calls=5, max_tool_calls=7, max_cost_usd=0.02),
        deepens=True,
    ),
    "why": Strategy(
        tools=tuple(TOOLS),
        guide=_WHY,
        budget=Budget(max_calls=6, max_tool_calls=8, max_cost_usd=0.02),
        deepens=True,
    ),
    "pattern": Strategy(
        tools=(
            "correlate",
            "weekday_split",
            "tag_effect",
            "checkins",
            "coverage",
            "describe",
            "sleep_regularity",
        ),
        guide="How to work: test the relationship asked about directly (correlate, weekday_split, "
        "tag_effect) and check coverage. No hypotheses needed. Then call submit_findings.",
        budget=Budget(max_calls=4, max_tool_calls=6, max_cost_usd=0.015),
        deepens=True,
    ),
    "coaching": Strategy(
        tools=(
            "habit_options",
            "sleep_regularity",
            "training_load",
            "correlate",
            "tag_effect",
            "coverage",
        ),
        guide="How to work: the habits this person's data supports are already tested below, as "
        "evidence you may cite. Suggest only those marked supported (at most two), as claims of "
        "kind suggestion; a significant correlation you find may back one too. Vetted guidance on "
        "how to try them is below too; you may use it, next to their evidence. With none "
        "supported, say so and offer to test a habit. No hypotheses. Then call submit_findings.",
        budget=Budget(max_calls=4, max_tool_calls=5, max_cost_usd=0.015),
        snapshot=True,
        coaching=True,
    ),
}
COACHING_OFFER = (
    "Want me to set a reminder for this, or help you test it for a few weeks? Just ask."
)


def strategy_for(question_type: str | None) -> Strategy:
    return STRATEGIES.get(question_type or DEFAULT_TYPE, STRATEGIES[DEFAULT_TYPE])


def scaled(strategy: Strategy, deep: bool) -> Budget:
    """The type's budget; a deep answer to a why, change or pattern question gets twice as much."""
    budget = strategy.budget
    if deep and strategy.deepens:
        budget = replace(
            budget,
            max_calls=budget.max_calls * 2,
            max_tool_calls=budget.max_tool_calls * 2,
            max_cost_usd=budget.max_cost_usd * 2,
        )
    return replace(budget)  # a fresh copy: budgets are charged as they run


def expand_tool(toolbox: Toolbox, budget: Budget, trace: list[dict]) -> ExtraTool:
    """Gives the agent every tool and one more budget step, once, with its reason recorded."""

    def run(arguments: dict | None) -> tuple[str, dict]:
        if any(step.get("expanded") for step in trace):
            return json.dumps({"error": "You already widened your tools in this answer."}), {}
        reason = str((arguments or {}).get("reason", ""))[:200]
        toolbox.tools = dict(TOOLS)
        budget.max_calls += 3
        budget.max_tool_calls += 5
        budget.max_cost_usd += 0.01
        step = {"expanded": True, "reason": reason}
        trace.append({"type": "expand", **step})
        return json.dumps({"tools": sorted(TOOLS), "note": "All tools are available now."}), step

    return ExtraTool(
        EXPAND,
        "Only when the tools you have cannot answer the question: get every analysis tool and a "
        "little more budget, once per answer. Say in one line why.",
        {
            "type": "object",
            "properties": {"reason": {"type": "string", "maxLength": 200}},
            "required": ["reason"],
        },
        run,
    )


def snapshot(frame: pd.DataFrame, metrics: list[str]) -> tuple[list[Evidence], str]:
    """The latest day against the usual range for the main metrics in scope, as evidence."""
    if frame.empty:
        return [], ""
    day = frame.index.max().date()
    found = []
    for metric in SNAPSHOT_METRICS:
        if metric not in metrics:
            continue
        try:
            evidence = compare_day(frame, metric, day)
        except ToolError:
            continue
        if evidence.sufficient:
            found.append(evidence)
    if not found:
        return [], ""
    lines = []
    for e in found:
        shown = evidence_payload(e)["display"]
        lines.append(
            f"- {label(e.metrics[0])} (evidence_id {e.id}): {shown.get('value', '')}, usual "
            f"{shown.get('usual_low', '')} to {shown.get('usual_high', '')}, "
            f"{e.stats['position']} the usual range"
        )
    return found, f"Snapshot of the latest day ({day.isoformat()}), computed:\n" + "\n".join(lines)


def coaching_evidence(
    frame: pd.DataFrame, expert: str | None, metrics: list[str]
) -> tuple[list[Evidence], str]:
    """habit_options on the goal's metrics over the last 60 days, run before the model starts."""
    if frame.empty:
        return [], ""
    end = frame.index.max().date()
    window = Window(start=end - timedelta(days=COACHING_DAYS - 1), end=end)
    found, lines = [], []
    for metric in GOALS.get(expert, GOALS[None]):
        if metric not in metrics or metric not in frame.columns:
            continue
        try:
            evidence = habit_options(frame, metric, window)
        except ToolError:
            continue
        found.append(evidence)
        supported = [lever["habit"] for lever in evidence.stats["levers"] if lever["supported"]]
        lines.append(
            f"- {label(metric)} (evidence_id {evidence.id}): "
            + (f"supported: {'; '.join(supported)}" if supported else "no habit clearly supported")
        )
    if not found:
        return [], ""
    return found, "Habits tested on this person's own days (habit_options):\n" + "\n".join(lines)
