"""The tools the agent may call: descriptions for the model, argument checks, and dispatch to the
deterministic analysis tools.

The model only chooses a tool, metrics and dates; the computing happens here, on data the server
holds. A toolbox is built per run with the metrics its expert may see, and keeps every `Evidence`
it produced so the verifier can check claims against them. Problems with a call are returned to
the model as an error it can correct, never raised.
"""

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.llm import ToolCall
from app.agent.present import display, label
from app.analysis import coaching, habits
from app.analysis import tools as analysis
from app.analysis.day import compare_day
from app.analysis.evidence import Evidence, ToolError, Window
from app.analysis.habits import CHECKIN_RATING, TAG_PREFIX
from app.db.models import CHECKIN_TAGS

# Kept with any metric set: activity totals are not comparable on days the device was barely worn.
# Every expert sees wear time and the morning check-in (its rating and the tags chosen).
ALWAYS_VISIBLE = ("wear_minutes", CHECKIN_RATING)


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Period(_Arguments):
    start: date = Field(description="First day, YYYY-MM-DD")
    end: date = Field(description="Last day (inclusive), YYYY-MM-DD")


class MetricPeriod(Period):
    metric: str = Field(description="A metric from the list")


class CompareArguments(_Arguments):
    metric: str = Field(description="A metric from the list")
    recent_start: date
    recent_end: date
    baseline_start: date = Field(description="The baseline must not overlap the recent window")
    baseline_end: date


class DayArguments(_Arguments):
    metric: str = Field(description="A metric from the list")
    day: date = Field(description="The day, YYYY-MM-DD; the last day of data for 'today'")


class CorrelateArguments(Period):
    driver: str = Field(description="The metric that may explain the change")
    target: str = Field(description="The metric that changed")
    max_lag: int = Field(0, ge=0, le=analysis.MAX_LAG_DAYS, description="Days the effect may lag")


class RankArguments(MetricPeriod):
    order: Literal["best", "worst", "highest", "lowest"] = Field(
        description="best and worst follow which way is better for the metric"
    )
    count: int = Field(3, ge=1, le=5)


class GoalArguments(MetricPeriod):
    goal_value: float = Field(
        description="The number from what they said, in the metric's unit; a bedtime is in hours "
        "from midnight, so 23:00 is -1"
    )
    direction: Literal["at_least", "at_most"]


class DayOnly(_Arguments):
    day: date = Field(description="The day, YYYY-MM-DD; the last day of data for 'today'")


class TagArguments(MetricPeriod):
    tag: Literal[CHECKIN_TAGS] = Field(description="A morning check-in tag")


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    arguments: type[_Arguments]
    run: Callable[[pd.DataFrame, _Arguments], Evidence]


def _window(args: _Arguments, prefix: str = "") -> Window:
    return Window(start=getattr(args, f"{prefix}start"), end=getattr(args, f"{prefix}end"))


TOOLS: dict[str, AgentTool] = {
    tool.name: tool
    for tool in (
        AgentTool(
            "describe",
            "Summary of one metric over a period: mean, median, spread, range, missing days.",
            MetricPeriod,
            lambda frame, a: analysis.describe(frame, a.metric, _window(a)),
        ),
        AgentTool(
            "coverage",
            "How complete each metric is over a period, and which days had low wear time. "
            "Check this before trusting a change: gaps and low wear can fake one.",
            Period,
            lambda frame, a: analysis.coverage(frame, _window(a)),
        ),
        AgentTool(
            "compare_windows",
            "Whether a metric differs between a recent period and an earlier baseline "
            "(Mann-Whitney U, Cliff's delta). Use it to confirm and size a change.",
            CompareArguments,
            lambda frame, a: analysis.compare_windows(
                frame, a.metric, _window(a, "recent_"), _window(a, "baseline_")
            ),
        ),
        AgentTool(
            "trend",
            "Whether a metric drifts steadily over a period (Theil-Sen slope per day).",
            MetricPeriod,
            lambda frame, a: analysis.trend(frame, a.metric, _window(a)),
        ),
        AgentTool(
            "change_point",
            "The day a metric most likely shifted to a new level within a period, and whether "
            "the shift is real (permutation test). Use it to date a change before looking for "
            "what else changed around then.",
            MetricPeriod,
            lambda frame, a: analysis.change_point(frame, a.metric, _window(a)),
        ),
        AgentTool(
            "correlate",
            "Whether the target moves with a driver on the same day or up to max_lag days later "
            "(Spearman, adjusted for the lags tried). Shows association, not cause.",
            CorrelateArguments,
            lambda frame, a: analysis.correlate(frame, a.driver, a.target, _window(a), a.max_lag),
        ),
        AgentTool(
            "compare_day",
            "One day's value against the person's usual range (the middle half of the 28 days "
            "before): above, below or within. Use it for questions about today, last night or "
            "a single day. It describes where the day sits; it is not a test of a change.",
            DayArguments,
            lambda frame, a: compare_day(frame, a.metric, a.day),
        ),
        AgentTool(
            "weekday_split",
            "Whether a metric differs on weekends from weekdays.",
            MetricPeriod,
            lambda frame, a: analysis.weekday_split(frame, a.metric, _window(a)),
        ),
        AgentTool(
            "sleep_regularity",
            "How regular bedtimes and wake times are over a period (their spread in minutes) and "
            "how much later bedtime is on weekends.",
            Period,
            lambda frame, a: habits.sleep_regularity(frame, _window(a)),
        ),
        AgentTool(
            "training_load",
            "The last 7 days' strain against the last 28 days' (lighter, steady or heavier than "
            "usual), and how the recovery score went the morning after the hardest days.",
            DayOnly,
            lambda frame, a: habits.training_load(frame, a.day),
        ),
        AgentTool(
            "rank_days",
            "The best, worst, highest or lowest days of a metric in a period.",
            RankArguments,
            lambda frame, a: habits.rank_days(frame, a.metric, _window(a), a.order, a.count),
        ),
        AgentTool(
            "goal_progress",
            "How often days met a target the person set themselves, overall and over the last "
            "week. The target must come from what they said.",
            GoalArguments,
            lambda frame, a: habits.goal_progress(
                frame, a.metric, a.goal_value, a.direction, _window(a)
            ),
        ),
        AgentTool(
            "usual_ranges",
            "The person's usual range (the middle half of the 28 days before a day) for each main "
            "metric: what is normal for them.",
            DayOnly,
            lambda frame, a: habits.usual_ranges(frame, a.day),
        ),
        AgentTool(
            "checkins",
            "How the person rated their mornings over a period (1 to 5) and how often they chose "
            "each tag (hard training, alcohol, late meal, stress, travel, feeling sick).",
            Period,
            lambda frame, a: habits.checkin_summary(frame, _window(a)),
        ),
        AgentTool(
            "tag_effect",
            "A metric on days the person tagged in their check-in (for example a late meal or "
            "stress) against days without that tag. Association, not cause.",
            TagArguments,
            lambda frame, a: habits.tag_effect(frame, a.tag, a.metric, _window(a)),
        ),
        AgentTool(
            "habit_options",
            "For coaching: which everyday habits from a fixed, non-medical list this person's own "
            "data supports for improving a metric (earlier or more regular bedtime, an easier day "
            "after hard training, more active days, an earlier dinner, winding down on stressful "
            "days), each a comparison of their own days, corrected for the number tested. Suggest "
            "only supported habits, citing this evidence.",
            MetricPeriod,
            lambda frame, a: coaching.habit_options(frame, a.metric, _window(a)),
        ),
    )
}

METRIC_FIELDS = ("metric", "driver", "target")


@dataclass(frozen=True)
class ToolResult:
    content: str  # what the model reads: the evidence, or what was wrong with the call
    evidence: Evidence | None = None
    error: str | None = None


def evidence_payload(evidence: Evidence) -> dict:
    """The evidence as the model sees it: everything it may cite, keyed by id, with the values as
    a person reads them under `display` (the raw statistics are unchanged)."""
    return {
        "evidence_id": evidence.id,
        "tool": evidence.tool,
        "metrics": list(evidence.metrics),
        "labels": {metric: label(metric) for metric in evidence.metrics},
        "display": display(evidence),
        "windows": [
            {"start": w.start.isoformat(), "end": w.end.isoformat()} for w in evidence.windows
        ],
        "n": evidence.n,
        "sufficient": evidence.sufficient,
        "stats": evidence.stats,
    }


class Toolbox:
    def __init__(
        self, frame: pd.DataFrame, metrics: Iterable[str], tools: Iterable[str] | None = None
    ):
        allowed = set(metrics)
        self.metrics = tuple(sorted(c for c in frame.columns if c in allowed))
        context = [c for c in ALWAYS_VISIBLE if c in frame.columns and c not in allowed]
        # The check-in's tags (1 or 0 on check-in days), for tag_effect and habit_options.
        context += [c for c in frame.columns if c.startswith(TAG_PREFIX) and c not in allowed]
        self.frame = frame[[*self.metrics, *context]]
        self.tools = {name: TOOLS[name] for name in (tools or TOOLS)}
        self.evidence: dict[str, Evidence] = {}
        self.produced: list[str] = []  # ids of the evidence this run's own tool calls made
        days = frame.index
        self.first_day = days.min().date() if len(days) else None
        self.last_day = days.max().date() if len(days) else None

    def schemas(self) -> list[dict]:
        """The tools in the format the model API expects, with the allowed metrics listed."""
        schemas = []
        for tool in self.tools.values():
            parameters = tool.arguments.model_json_schema()
            for name in METRIC_FIELDS:
                if name in parameters.get("properties", {}):
                    parameters["properties"][name]["enum"] = list(self.metrics)
            parameters.pop("title", None)
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": parameters,
                    },
                }
            )
        return schemas

    def run(self, call: ToolCall) -> ToolResult:
        if call.error:
            return self._error(call.error)
        tool = self.tools.get(call.name)
        if tool is None:
            return self._error(f"Unknown tool {call.name!r}. Available: {', '.join(self.tools)}.")
        try:
            args = tool.arguments.model_validate(call.arguments or {})
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in exc.errors()
            )
            return self._error(f"Invalid arguments: {problems}.")
        for name in METRIC_FIELDS:
            metric = getattr(args, name, None)
            if metric is not None and metric not in self.metrics:
                return self._error(
                    f"Metric {metric!r} is not available here. Use one of: "
                    f"{', '.join(self.metrics)}."
                )
        dates = [value for value in args.model_dump().values() if isinstance(value, date)]
        if self.first_day and any(d < self.first_day or d > self.last_day for d in dates):
            return self._error(
                f"Dates must be between {self.first_day} and {self.last_day}, the data available."
            )
        try:
            evidence = tool.run(self.frame, args)
        except (ToolError, ValueError) as exc:
            return self._error(str(exc))
        self.evidence[evidence.id] = evidence
        self.produced.append(evidence.id)
        return ToolResult(content=json.dumps(evidence_payload(evidence)), evidence=evidence)

    @staticmethod
    def _error(message: str) -> ToolResult:
        return ToolResult(content=json.dumps({"error": message}), error=message)
