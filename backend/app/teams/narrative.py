"""The weekly team report's prose, written by a model over the aggregate evidence and checked.

The model sees only team evidence: counts, medians, quartiles, p-values and weekday medians, never
a member or a per-person value. It returns a headline and short paragraphs, each declaring what
it says (a change, no change, or a weekday pattern), about which metric and citing evidence ids.
Each paragraph is checked like an agent's claim: a change must rest on a team change that held
after correction, in the stated direction; numbers, dates and metric names must come from the
cited evidence; nothing may single out a person, diagnose or claim a cause. Every change the
statistics found must be covered. Anything wrong after one repair round, a model error or the
budget, and the caller keeps the templated text.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.agent.llm import LLM, Budget, LLMError
from app.agent.verifier import DOWN_WORDS, UP_WORDS, text_problems
from app.analysis.evidence import Evidence
from app.analysis.report import change_text
from app.analysis.team import TeamStatistics, team_info

WRITE = "write_team_report"
MAX_CALLS = 2  # the report, and one repair round

# A sentence about one person, or a guess about who, is not a team aggregate.
INDIVIDUAL = re.compile(
    r"\b(one|a single|a few|some|two|three|certain) (?:of the )?"
    r"(?:person|people|members?|employees?|colleagues?|individuals?)\b|"
    r"\b(he|she|him|her|his|hers|someone|somebody|anyone in particular)\b",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """You write a short weekly report for a team's supervisor about the team's own \
Fitbit data: sleep, activity and the app's recovery, strain and physical stress signs scores. \
That last score is physical signs only, never how anyone feels: call it physical stress signs.

You get only team statistics: each member's week was compared with their own four weeks before, \
and the team's changes were tested together. You never see or mention any individual.

Write a headline (one sentence) and 2 to 8 paragraphs of one or two plain sentences: every \
change first, then the most notable steady metrics and weekday patterns. Each paragraph is one \
of:
- change: a metric whose team change is marked changed=true, in its direction ("up" when the \
median change is positive). Quote the median change and how many people were higher and lower.
- no_change: a metric marked changed=false. Say there was no clear change; you may give the median.
- pattern: a weekday pattern, describing which days ran higher or lower than people's usual.
Cover every metric marked changed=true. Leave out metrics with too little data.

Rules: quote only numbers given in the statistics, in the units given. Name metrics as given in \
"label". Never write evidence ids in the text; list them in evidence_ids. Do not single out or \
guess about any person. Do not explain causes, diagnose, give health or management advice, or \
suggest decisions about anyone: describe the team's patterns only."""


class Paragraph(BaseModel):
    text: str = Field(min_length=1, max_length=400)
    kind: Literal["change", "no_change", "pattern"]
    metric: str = Field(description='The key given as "metric", not the label.')
    direction: Literal["up", "down"] | None = None
    evidence_ids: list[str] = Field(min_length=1)


class TeamNarrative(BaseModel):
    headline: str = Field(min_length=1, max_length=200)
    # Nine metrics and three weekday patterns at most; the prompt asks for fewer.
    paragraphs: list[Paragraph] = Field(min_length=1, max_length=12)


@dataclass
class Narrated:
    headline: str
    paragraphs: list[dict]
    cost_usd: float


@dataclass
class Attempt:
    """What happened, for the report's record and the tests."""

    narrated: Narrated | None = None
    problems: list[str] = field(default_factory=list)
    cost_usd: float = 0.0


def _tool(metrics: list[str]) -> dict:
    """The form, with the paragraph's metric limited to this week's keys."""
    schema = TeamNarrative.model_json_schema()
    schema.pop("title", None)
    schema["$defs"]["Paragraph"]["properties"]["metric"]["enum"] = metrics
    return {
        "type": "function",
        "function": {
            "name": WRITE,
            "description": "Hand in the report: a headline and paragraphs citing evidence ids.",
            "parameters": schema,
        },
    }


def payload(statistics: TeamStatistics) -> list[dict]:
    """What the model reads: aggregates only, with labels, units and readable changes."""
    changed = {e.id for e in statistics.changed}
    items = []
    for evidence in statistics.changes:
        metric = evidence.metrics[0]
        item = {
            "evidence_id": evidence.id,
            "metric": metric,
            "label": team_info(metric).label,
            "kind": "team_change",
            "members": evidence.stats["members"],
        }
        if evidence.sufficient:
            stats = evidence.stats
            item |= {
                "changed": evidence.id in changed,
                "median_change": change_text(metric, stats["median_change"]),
                "members_higher": stats["members_up"],
                "members_lower": stats["members_down"],
                "p_value_adjusted": stats["p_value_adjusted"],
            }
        else:
            item["too_little_data"] = True
        items.append(item)
    for evidence in statistics.weekdays:
        if evidence.sufficient:
            metric = evidence.metrics[0]
            items.append(
                {
                    "evidence_id": evidence.id,
                    "metric": metric,
                    "label": team_info(metric).label,
                    "kind": "weekday_pattern",
                    "median_against_usual_by_weekday": {
                        day: change_text(metric, value)
                        for day, value in evidence.stats["median_deviation_by_weekday"].items()
                    },
                }
            )
    return items


def check_paragraph(
    paragraph: Paragraph, evidence: dict[str, Evidence], changed: set[str]
) -> list[str]:
    missing = [i for i in paragraph.evidence_ids if i not in evidence]
    if missing:
        return [f"cites evidence that does not exist: {', '.join(missing)}"]
    cited = [evidence[i] for i in paragraph.evidence_ids]
    reasons = []
    if insufficient := [e.id for e in cited if not e.sufficient]:
        reasons.append(f"cites evidence with too little data: {', '.join(insufficient)}")
    about = [e for e in cited if paragraph.metric in e.metrics]
    if not about:
        reasons.append(f"none of the cited evidence is about {paragraph.metric}")
    changes = [e for e in about if e.tool == "team_change" and e.sufficient]
    if paragraph.kind == "change":
        support = [e for e in changes if e.id in changed]
        if not support:
            reasons.append("describes a change the team statistics did not find")
        elif paragraph.direction is None:
            reasons.append("a change must state its direction")
        elif {e.stats["median_change"] > 0 for e in support} != {paragraph.direction == "up"}:
            reasons.append(f"the team's change does not point {paragraph.direction}")
        else:
            up, down = (
                bool(UP_WORDS.search(paragraph.text)),
                bool(DOWN_WORDS.search(paragraph.text)),
            )
            if (paragraph.direction == "up" and down and not up) or (
                paragraph.direction == "down" and up and not down
            ):
                reasons.append("the wording contradicts the stated direction")
    if paragraph.kind == "no_change":
        if any(e.id in changed for e in changes):
            reasons.append("says no change, but the team statistics found one")
        elif not changes:
            reasons.append("a no_change paragraph must cite the metric's team change")
    if paragraph.kind == "pattern" and not any(e.tool == "team_weekday" for e in about):
        reasons.append("a weekday pattern must cite weekday evidence about its metric")
    if INDIVIDUAL.search(paragraph.text):
        reasons.append("refers to individuals; describe the team only")
    return reasons + text_problems(paragraph.text, cited)


def _keys(narrative: TeamNarrative, statistics: TeamStatistics) -> list[str]:
    """Labels written where keys belong ("Time asleep" for sleep_minutes) are read as their keys;
    anything else unknown is a problem."""
    keys = {m for e in [*statistics.changes, *statistics.weekdays] for m in e.metrics}
    by_label = {team_info(m).label.lower(): m for m in keys}
    problems = []
    for i, paragraph in enumerate(narrative.paragraphs, start=1):
        if paragraph.metric in keys:
            continue
        if (key := by_label.get(paragraph.metric.strip().lower())) is not None:
            paragraph.metric = key
        else:
            problems.append(
                f"paragraph {i}: metric must be one of {', '.join(sorted(keys))} "
                f"(the key, not the label)"
            )
    return problems


def check(narrative: TeamNarrative, statistics: TeamStatistics) -> list[str]:
    evidence = {e.id: e for e in [*statistics.changes, *statistics.weekdays]}
    changed = {e.id for e in statistics.changed}
    problems = _keys(narrative, statistics)
    for i, paragraph in enumerate(narrative.paragraphs, start=1):
        problems += [
            f"paragraph {i}: {reason}" for reason in check_paragraph(paragraph, evidence, changed)
        ]
    covered = {i for p in narrative.paragraphs if p.kind == "change" for i in p.evidence_ids}
    if missed := [e for e in statistics.changed if e.id not in covered]:
        names = ", ".join(team_info(e.metrics[0]).label for e in missed)
        problems.append(f"leaves out changes the statistics found: {names}")
    every = list(evidence.values())
    headline = text_problems(narrative.headline, every)
    if INDIVIDUAL.search(narrative.headline):
        headline.append("refers to individuals; describe the team only")
    problems += [f"headline: {reason}" for reason in headline]
    return problems


def _parse(completion) -> tuple[TeamNarrative | None, str | None]:
    call = next((c for c in completion.tool_calls if c.name == WRITE), None)
    if call is None:
        return None, f"no {WRITE} call"
    try:
        return TeamNarrative.model_validate(call.arguments), None
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}" for e in error.errors()[:5]
        )
        return None, f"the report did not match its form: {details}"


def narrate(llm: LLM, statistics: TeamStatistics, cap_usd: float) -> Attempt:
    """One model call (and one repair round) for the report's prose; None-equivalent on failure."""
    budget = Budget(max_calls=MAX_CALLS, max_tool_calls=MAX_CALLS, max_cost_usd=cap_usd)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"The week of {statistics.week.start} to {statistics.week.end}, "
                f"{statistics.members} members.\n\n"
                + json.dumps(payload(statistics), ensure_ascii=False)
            ),
        },
    ]
    metrics = sorted({m for e in [*statistics.changes, *statistics.weekdays] for m in e.metrics})
    attempt = Attempt()
    for _ in range(MAX_CALLS):
        try:
            completion = llm.complete(messages, tools=[_tool(metrics)], budget=budget)
        except LLMError as error:
            attempt.problems.append(str(error))
            break
        attempt.cost_usd = budget.cost_usd
        narrative, problem = _parse(completion)
        problems = [problem] if problem else check(narrative, statistics)
        if not problems:
            attempt.narrated = Narrated(
                headline=narrative.headline,
                paragraphs=[p.model_dump() for p in narrative.paragraphs],
                cost_usd=budget.cost_usd,
            )
            return attempt
        attempt.problems = problems
        messages.append(completion.as_message())
        for call in completion.tool_calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(
                        {"problems": problems, "instruction": f"Fix these and call {WRITE} again."}
                    ),
                }
            )
        if not completion.tool_calls:
            messages.append({"role": "user", "content": f"Call {WRITE} with the report."})
    return attempt
