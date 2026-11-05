"""The agent's explanation of a smart alarm, checked like any answer, with the template as fallback.

A detector decided the alarm; the expert that owns its metric now looks at what went with it (the
bedtime before a short night, training before a rise in resting heart rate) in one quick run, with
the alarm's evidence given so it can cite it. Its summary passed the verifier (every number from
evidence, no causes, no overstatement) and the advice guard inside that run; a reply that did not,
or a run that failed, leaves the template. Data alarms (no new data, reconnect) need no
explanation. Each run's cost is kept on the alarm.

Advice only when it is needed and specific: on a problem that has lasted (a streak, a two-week
change), never one bad day, and only when the person's own data has something to point at. The
explanation also knows what they chose to keep, so it can fit what is going on in their life.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from app.agent.experts import Depth, ask_expert, available, owner
from app.agent.guard import Guard
from app.agent.llm import LLM, LLMError
from app.agent.verifier import MEDICAL
from app.analysis.coaching import habit_options, personal_options
from app.analysis.evidence import Evidence, ToolError, Window
from app.analysis.habits import BETTER

logger = logging.getLogger(__name__)

MAX_BODY = 400  # what the inbox holds
ADVISED_KINDS = ("streak", "finding")
ADVICE_DAYS = 60
QUESTION = (
    "Patterns raised this alert from the person's data: {title}. {body} "
    "In two or three short sentences, say what the data shows around it, for example the bedtime "
    "or training before it, or how long it has been going on, citing evidence. Lead with the "
    "alert itself. Never diagnose or say what caused it. {advice}"
)
NO_ADVICE = "Describe only; give no advice."
ADVICE = (
    "End with one thing they could try, worded as an option and said as worth trying, built on "
    "what their own data shows here: {options}. Fit it to what the context says is going on in "
    "their life. No general tips."
)


def specific_advice(frame: pd.DataFrame, metric: str, today) -> tuple[list[Evidence], str]:
    """What this person's own data says they could try about `metric`, if anything."""
    if metric not in BETTER or metric not in frame.columns or frame.empty:
        return [], ""
    end = frame.index.max().date()
    window = Window(start=end - timedelta(days=ADVICE_DAYS - 1), end=end)
    try:
        tested = habit_options(frame, metric, window)
        routine = personal_options(frame, metric, window)
    except ToolError:
        return [], ""
    habits = [lever["habit"] for lever in tested.stats["levers"] if lever["supported"]]
    if habits:
        return [tested], "; ".join(f"{habit} goes with better days" for habit in habits[:1])
    found = [option for option in routine.stats["options"] if option["try"]]
    if not found:
        return [], ""
    return [routine], f"{found[0]['note']}, so {found[0]['try']}"


@dataclass(frozen=True)
class Explanation:
    body: str
    written_by: str  # the expert, or "template"
    cost_usd: float


def explain(
    llm: LLM | None,
    frame: pd.DataFrame,
    *,
    kind: str,
    metric: str | None,
    title: str,
    body: str,
    evidence: list[Evidence],
    today,
    guard: Guard | None = None,
    context: str = "",
) -> Explanation:
    """The expert's explanation when it passes; the template body otherwise."""
    fallback = Explanation(body, "template", 0.0)
    expert = owner(metric) if metric else None
    if llm is None or kind == "data" or expert is None or not available(expert, frame):
        return fallback
    extra, options = specific_advice(frame, metric, today) if kind in ADVISED_KINDS else ([], "")
    advice = ADVICE.format(options=options) if options else NO_ADVICE
    cited = [*evidence, *extra]
    try:
        result = ask_expert(
            llm,
            frame,
            expert.name,
            QUESTION.format(title=title, body=body, advice=advice),
            depth=Depth.QUICK,
            today=today,
            context=context,
            evidence={e.id: e for e in cited},
            owners={e.id: expert.name for e in cited},
            guard=guard,
        )
    except LLMError as error:
        logger.warning("Explaining an alarm failed: %s", error)
        return fallback
    cost = result.budget.cost_usd
    text = result.summary.strip()
    checks = [step for step in result.trace if step.get("type") == "verify"]
    # A summary that failed its last check was replaced by the joined claims: the template reads
    # better than that.
    rejected = bool(checks and checks[-1].get("summary_problems"))
    if result.stop_reason != "submitted" or not text or rejected or MEDICAL.search(text):
        return Explanation(body, "template", cost)
    if len(text) > MAX_BODY:
        return Explanation(body, "template", cost)
    return Explanation(text, expert.name, cost)
