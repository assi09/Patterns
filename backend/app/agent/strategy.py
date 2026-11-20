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
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

import pandas as pd

from app.agent.agent import DEFAULT_GUIDE, ExtraTool
from app.agent.experts import owner
from app.agent.llm import Budget
from app.agent.periods import asked_period
from app.agent.present import clock, label
from app.agent.strategy_types import DEFAULT_TYPE
from app.agent.tools import BUILT_FROM, TOOLS, Toolbox, evidence_payload
from app.agent.verifier import DAY_MONTH, ISO_DATE, MENTIONS, MONTH_DAY, MONTHS, run_adjusted
from app.agent.verifier import _significant as is_significant
from app.analysis.coaching import WEEKDAYS, habit_options, personal_options
from app.analysis.day import compare_day
from app.analysis.evidence import Evidence, ToolError, Window
from app.analysis.habits import BETTER
from app.analysis.screen import BASELINE_DAYS, NOT_SCREENED, screen_windows, without_low_wear
from app.analysis.tools import change_point, compare_windows, correlate, describe

EXPAND = "expand_tools"
YESTERDAY = re.compile(r"\byesterday\b", re.IGNORECASE)
SNAPSHOT_METRICS = (
    "sleep_minutes",
    "sleep_efficiency",
    "bedtime_hour",
    "time_in_bed",
    "recovery_score",
    "resting_hr",
    "hrv_ms",
    "steps",
    "strain",
    "stress_score",
)
# How a question names a metric outside the usual snapshot: the verifier's distinctive terms, and
# everyday words it leaves out because they are too loose for checking an answer.
ASKED_ABOUT = {
    **MENTIONS,
    "awake_in_bed_minutes": re.compile(r"\bawake\b|\btime awake\b", re.IGNORECASE),
    "resting_hr": re.compile(r"resting heart rate|\bRHR\b|\bresting HR\b", re.IGNORECASE),
    "steps": re.compile(r"\bsteps?\b|\bwalked\b", re.IGNORECASE),
}


def asked_metrics(question: str, metrics: list[str]) -> list[str]:
    """The metrics a question names, among those in scope."""
    return [m for m, pattern in ASKED_ABOUT.items() if m in metrics and pattern.search(question)]


# The metrics a coaching goal is about, by the expert that leads.
GOALS = {
    "sleep": ("sleep_efficiency", "sleep_minutes"),
    "recovery": ("recovery_score", "hrv_ms"),
    "activity": ("recovery_score", "steps"),
    "nutrition": ("sleep_efficiency", "recovery_score"),  # how eating shows up in their data
    None: ("sleep_efficiency", "recovery_score"),
}
COACHING_DAYS = 60
MIN_CONTEXT_DAYS = 14
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
ONE_THING = (
    "Answer exactly what was asked, in one or two friendly sentences; bring in another metric only "
    "if it explains the answer. If an earlier answer in the conversation already holds it, say it "
    "again from there and cite its evidence. "
)

STRATEGIES: dict[str, Strategy] = {
    "day": Strategy(
        tools=("compare_day", "usual_ranges", "coverage"),
        guide="How to work: the snapshot below already compares one day with the usual range, as "
        "evidence you may cite. Answer from it if it covers the day asked about; otherwise use "
        "compare_day for that day. A day said relative to an earlier answer ('the day before "
        "that', 'the next day') counts from the day that answer was about, not from today. Name "
        "the day's date in the answer. Lead with the value asked about and its usual range as "
        "shown under display ('6 h 10 min, against your usual 6 h 50 min to 7 h 40 min'). Then, "
        "only if another figure in the snapshot explains it (a late bedtime for a short night), "
        "give that one in a few words; leave the rest out unless they asked. "
        + ONE_THING
        + "No hypotheses. Then call submit_findings.",
        budget=Budget(max_calls=6, max_tool_calls=5, max_cost_usd=0.02),
        snapshot=True,
        memory=False,
    ),
    "lookup": Strategy(
        tools=(
            "describe",
            "rank_days",
            "usual_ranges",
            "compare_day",
            "coverage",
            "checkins",
            "goal_progress",
        ),
        guide="How to work: answer the value asked for with the fewest tool calls (the snapshot "
        "below may already cover it), and state the figure as shown under display. 'How many' "
        "over a period ('steps this week') is the total, with the daily average after it. "
        "Asked for a total or sum, lead with the total (describe's total), never only the "
        "average; asked for an average, median, highest or lowest, give that one. Over the whole "
        "history, use describe over every day there is data and say the dates. "
        + ONE_THING
        + "No hypotheses. Then call submit_findings.",
        budget=Budget(max_calls=6, max_tool_calls=5, max_cost_usd=0.02),
        snapshot=True,
    ),
    "change": Strategy(
        tools=("compare_windows", "change_point", "trend", "coverage", "describe", "compare_day"),
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
        "tag_effect) and check coverage, unless an earlier answer already holds it: then say it "
        "again and cite its evidence. 'Hard training' is the strain metric, whatever the tags "
        "say. When it links two areas, use correlate with one as the "
        "driver and the other as the target; a night is dated by the morning it ends, so a day's "
        "effect on that night's sleep is max_lag 1. No hypotheses needed. Then call "
        "submit_findings.",
        budget=Budget(max_calls=6, max_tool_calls=6, max_cost_usd=0.02),
        deepens=True,
    ),
    "coaching": Strategy(
        tools=(
            "habit_options",
            "goal_progress",
            "sleep_regularity",
            "training_load",
            "correlate",
            "tag_effect",
            "coverage",
        ),
        guide="How to work: below are the habits tested on this person's days and what stands out "
        "in their own routine, as evidence you may cite. Give one or two suggestions, or as many "
        "as they ask for up to five, as claims of kind suggestion, each with option set to the "
        "key of the lever or option it offers and offering only the habit its evidence tested: "
        "first what tested as supported, "
        "then what stands out, said as worth trying, not as something proven. Use everything "
        "different below before stopping, and never the same point twice. Each must use their own "
        "numbers, say concretely what to do (the passages below say how: cite the one you use "
        "as well as their own evidence), and fit what the "
        "profile says is going on in their life. Several suggestions go in the summary one per "
        "line, each starting with '- '. Start with the advice: with fewer than they asked for, "
        "give those and say in a few words that this is what their data points to so far, never "
        "what you cannot do. Each suggestion joins something about this person (their numbers or "
        "what they told you, cited) with how to act on it (a passage, cited). What they told you "
        "comes first: it decides what fits. Keep to the subject asked about: advice on eating is "
        "about eating, not bedtimes. For a particular moment or situation, call "
        "knowledge_lookup. With nothing about this person below, give the most useful guidance "
        "from the passages as claims of kind guidance, say plainly that it is general, and ask "
        "the one question that would make it personal. No hypotheses. Then call submit_findings.",
        budget=Budget(max_calls=6, max_tool_calls=5, max_cost_usd=0.025),
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
        toolbox.tools = {k: v for k, v in TOOLS.items() if k not in toolbox.withheld}
        budget.max_calls += 3
        budget.max_tool_calls += 5
        budget.max_cost_usd += 0.01
        step = {"expanded": True, "reason": reason}
        trace.append({"type": "expand", **step})
        return json.dumps(
            {"tools": sorted(toolbox.tools), "note": "More tools are available."}
        ), step

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


DAY_BEFORE_YESTERDAY = re.compile(r"\bday before yesterday\b", re.IGNORECASE)


LATEST = re.compile(r"\b(?:last night|today|tonight|this morning)\b", re.IGNORECASE)


def asked_day(question: str, today, frame: pd.DataFrame) -> date | None:
    """The day a question is about, when the data has it: a date it names ("Monday Nov 9"), the
    day before yesterday, or yesterday. "Today's" row is the latest one, so without this a
    question about yesterday gets today's numbers, and one about Nov 9 got yesterday's snapshot."""
    if today is None:
        return None
    current = today.date() if isinstance(today, datetime) else today
    day = named_day(question, current)
    # "Last night and yesterday's steps": two days; the snapshot keeps the latest, and the
    # other day gets its own compare_day. Snapping both to yesterday answered the wrong night.
    if day is None and LATEST.search(question):
        return None
    if day is None and DAY_BEFORE_YESTERDAY.search(question):
        day = current - timedelta(days=2)
    elif day is None and YESTERDAY.search(question):
        day = current - timedelta(days=1)
    return day if day is not None and pd.Timestamp(day) in frame.index else None


def snapshot(
    frame: pd.DataFrame, metrics: list[str], day: date | None = None, question: str = ""
) -> tuple[list[Evidence], str]:
    """One day (the latest, unless given) against the usual range for the metrics the question
    names, first, then the main metrics in scope, as evidence. Without the named ones, "my deep
    sleep today" got time asleep and efficiency: deep sleep had no evidence, so the verifier
    rightly sent back every sentence about it (PHIA's questions on real people, 2026-11-16)."""
    if frame.empty:
        return [], ""
    name = "the day asked about" if day else "the latest day"
    day = day or frame.index.max().date()
    found = []
    named = asked_metrics(question, metrics)
    for metric in dict.fromkeys([*named, *SNAPSHOT_METRICS]):
        if metric not in metrics:
            continue
        try:
            evidence = compare_day(frame, metric, day)
        except ToolError:
            continue
        # A named metric is shown with its value even when the usual range is too thin to place it.
        if "position" in evidence.stats or (metric in named and evidence.sufficient):
            found.append(evidence)
    if not found:
        return [], ""
    lines = []
    for e in found:
        shown = evidence_payload(e)["display"]
        where = (
            f", usual {shown.get('usual_low', '')} to {shown.get('usual_high', '')}, "
            f"{e.stats['position']} the usual range"
            if "position" in e.stats
            else ", too few earlier days for a usual range"
        )
        lines.append(
            f"- {label(e.metrics[0])} (evidence_id {e.id}): {shown.get('value', '')}{where}"
        )
    header = f"Snapshot of {name} ({day:%A} {day.isoformat()}; sleep is the night ending that "
    header += "morning), computed:\n"
    return found, header + "\n".join(lines)


def _fitting(record: Evidence, levers: frozenset[str], options: frozenset[str]) -> Evidence:
    """Without the habits that do not fit how this person lives."""
    stats = dict(record.stats)
    if "levers" in stats:
        stats["levers"] = [lever for lever in stats["levers"] if lever["lever"] not in levers]
        stats["supported"] = any(lever["supported"] for lever in stats["levers"])
    if "options" in stats:
        stats["options"] = [o for o in stats["options"] if o["key"] not in options]
    return record.model_copy(update={"stats": stats, "sufficient": record.sufficient})


def coaching_evidence(
    frame: pd.DataFrame,
    expert: str | None,
    metrics: list[str],
    skip_levers: frozenset[str] = frozenset(),
    skip_options: frozenset[str] = frozenset(),
    window: Window | None = None,
    goals: tuple[str, ...] = (),
) -> tuple[list[Evidence], str]:
    """habit_options and personal_options on the goal's metrics over the last 60 days, or over the
    days the request named ("my short sleep in September" is September), run before the model
    starts."""
    if frame.empty:
        return [], ""
    if window is None:
        end = frame.index.max().date()
        window = Window(start=end - timedelta(days=COACHING_DAYS - 1), end=end)
    found, lines, stands_out = [], [], []
    # The metrics an investigation names are its goals, whichever area it was routed to.
    for metric in goals or GOALS.get(expert, GOALS[None]):
        if metric not in metrics or metric not in frame.columns:
            continue
        try:
            evidence = _fitting(habit_options(frame, metric, window), skip_levers, skip_options)
        except ToolError:
            continue
        found.append(evidence)
        # A "watch" lever is a pattern seen on their days, not a habit tested: named as one.
        watch = " (a pattern to watch, not a tested habit)"
        supported = [
            lever["habit"] + (watch if lever.get("permits") == "watch" else "")
            for lever in evidence.stats["levers"]
            if lever["supported"]
        ]
        lines.append(
            f"- {label(metric)} (evidence_id {evidence.id}): "
            + (f"supported: {'; '.join(supported)}" if supported else "no habit clearly supported")
        )
        routine = _fitting(personal_options(frame, metric, window), skip_levers, skip_options)
        if routine.sufficient and routine.stats["options"]:
            found.append(routine)
            stands_out.append(
                f"- {label(metric)} (evidence_id {routine.id}): "
                + "; ".join(
                    option["note"] + (f" (could try {option['try']})" if option["try"] else "")
                    for option in routine.stats["options"]
                )
            )
    if not found:
        return [], ""
    text = "Habits tested on this person's own days (habit_options):\n" + "\n".join(lines)
    if stands_out:
        text += (
            "\n\nWhat stands out in their own routine (personal_options; described, not tested):\n"
            + "\n".join(stands_out)
        )
    return found, text


def eating_context(
    frame: pd.DataFrame, skip: frozenset[str] = frozenset()
) -> tuple[list[Evidence], str]:
    """What the rest of their data says about the days they eat around, for someone who has logged
    no food: when they train hardest and when they go to bed."""
    if frame.empty:
        return [], ""
    end = frame.index.max().date()
    window = Window(start=end - timedelta(days=COACHING_DAYS - 1), end=end)
    recent = frame.loc[pd.Timestamp(window.start) : pd.Timestamp(window.end)]
    options, stats, metrics = [], {}, []
    if "strain" in recent and recent["strain"].notna().sum() >= MIN_CONTEXT_DAYS:
        strain = recent["strain"].dropna()
        hard = strain[strain >= strain.quantile(0.75)]
        days = hard.groupby(hard.index.dayofweek).size()
        busiest = WEEKDAYS[int(days.idxmax())]
        stats |= {"hard_days": len(hard), "hard_days_on_busiest": int(days.max())}
        metrics.append("strain")
        options.append(
            {
                "key": "training_days",
                "note": f"your {len(hard)} hardest training days were most often on {busiest}s",
                "try": "planning what you eat around those days",
            }
        )
    bed = recent["bedtime_hour"].notna().sum() if "bedtime_hour" in recent else 0
    if "usual_bedtime" not in skip and bed >= MIN_CONTEXT_DAYS:
        usual = float(recent["bedtime_hour"].median())
        stats["median"] = round(usual, 3)
        metrics.append("bedtime_hour")
        options.append(
            {
                "key": "usual_bedtime",
                "note": f"your usual bedtime is around {clock(usual)}",
                "try": "timing your last meal around that",
            }
        )
    if not options:
        return [], ""
    stats["options"] = options
    record = Evidence(
        tool="personal_options",
        metrics=tuple(metrics),
        windows=(window,),
        n=len(recent),
        sufficient=True,
        stats=stats,
    )
    notes = "; ".join(o["note"] + f" (could try {o['try']})" for o in options)
    return [record], f"What their days look like (evidence_id {record.id}): {notes}"


# What links two areas, as (driver, target, lag): a night is dated by the morning it ends, so a
# day's training reaches that night's sleep at lag 1, and last night's sleep today's recovery at 0.
CROSS_AREA = {
    frozenset(("sleep", "activity")): (
        ("strain", "sleep_minutes", 1),
        ("strain", "sleep_efficiency", 1),
        ("active_zone_minutes", "sleep_efficiency", 1),
    ),
    frozenset(("recovery", "sleep")): (
        # HRV and resting heart rate, not the recovery score: that is built partly from sleep, so
        # sleep would always appear to explain it.
        ("sleep_minutes", "hrv_ms", 0),
        ("sleep_minutes", "resting_hr", 0),
        ("sleep_efficiency", "hrv_ms", 0),
        ("bedtime_hour", "hrv_ms", 0),
    ),
    frozenset(("recovery", "activity")): (
        ("strain", "hrv_ms", 1),
        ("strain", "resting_hr", 1),
        ("active_zone_minutes", "resting_hr", 1),
    ),
}
CROSS_DAYS = 90
CROSS_AREA_GUIDE = (
    "How to work: the question links two areas, and the tests below show whether they go together "
    "over the months. If it asks why something changed, also compare before and after with "
    "compare_windows or change_point on the metric and on the possible cause: a link alone is no "
    "reason, so name a cause only if it changed too, and otherwise say nothing explains it yet. "
    "Answer in one or two friendly sentences: an association claim where a test shows a link, a "
    "no_change claim where it does not, each with metric set to the target of that test and "
    "citing that test. Write 'went with', never 'because'. Then call submit_findings."
)


def cross_area_evidence(
    frame: pd.DataFrame, lead: str | None, others: Sequence[str]
) -> tuple[list[Evidence], str]:
    """A question linking two areas, tested by code before the model starts: the same few tests
    for everyone, so it is cheap, and a verdict does not depend on how many the model tried."""
    if frame.empty or lead is None:
        return [], ""
    end = frame.index.max().date()
    window = Window(start=end - timedelta(days=CROSS_DAYS - 1), end=end)
    pairs = [p for other in others for p in CROSS_AREA.get(frozenset((lead, other)), ())]
    found = []
    for driver, target, lag in pairs:
        if driver in frame.columns and target in frame.columns:
            try:
                record = correlate(frame, driver, target, window, lag)
            except ToolError:
                continue
            if record.sufficient:
                found.append(record)
    found = run_adjusted(found)
    if not found:
        return [], ""
    lines = []
    for record in found:
        driver, target = record.metrics[:2]
        rho = record.stats.get("rho") or 0
        way = "higher" if rho > 0 else "lower"
        verdict = f"went with {way} {label(target)}" if is_significant(record) else "no clear link"
        lines.append(f"- {label(driver)} and {label(target)} (evidence_id {record.id}): {verdict}")
    return found, (
        "Already tested across these areas over the last 90 days; answer from these first:\n"
        + "\n".join(lines)
    )


PREMISE_WORSE = re.compile(
    r"\b(?:worse|worsen\w*|declin\w*|bad|poor\w*|suffer\w*|struggl\w*)\b", re.IGNORECASE
)
PREMISE_BETTER = re.compile(r"\b(?:better|improv\w*)\b", re.IGNORECASE)
PREMISE_DOWN = re.compile(
    r"\b(?:drop\w*|fall\w*|fell|lower|less|fewer|down|shorter|decreas\w*)\b", re.IGNORECASE
)
PREMISE_UP = re.compile(r"\b(?:ris\w*|rose|higher|more|up|longer|increas\w*)\b", re.IGNORECASE)
PREMISE_METRICS = {
    "sleep": ("sleep_efficiency", "sleep_minutes"),
    "recovery": ("recovery_score", "hrv_ms"),
    "activity": ("steps", "strain"),
    None: ("sleep_minutes", "recovery_score", "steps"),
}
PREMISE_RECENT, PREMISE_BASELINE = 14, 28
PREMISE_SEARCH = 70  # days searched for when a change began; the last 42 may hold its start
MIN_PREMISE_DAYS = 7
# "Why", or a change over time: "which one is higher?" and "does X go with worse Y?" assume nothing.
ASSUMES_A_CHANGE = re.compile(
    r"^\s*(?:why|how come)\b|\b(?:lately|recently|these days|getting|gotten|has been|have been)\b",
    re.IGNORECASE,
)
DENIES = re.compile(
    r"\b(?:no clear|hasn'?t|haven'?t|has not|have not|isn'?t|is not|aren'?t|didn'?t|did not|"
    r"doesn'?t|does not|steady|stable|about the same|not really|not actually)\b",
    re.IGNORECASE,
)
PREMISE_GUIDE = (
    "How to work: they assume something changed, and the check below shows it has not. Say that "
    "first and kindly: it should reassure them. Use a no_change claim citing that check, with its "
    "numbers. Do not explain a change that did not happen; ask what made them feel that way, or "
    "offer what to look at instead. No hypotheses. Then call submit_findings."
)


# The everyday drivers a change could follow, each tested by code over the same days. Left to
# itself the agent checked sleep for a resting heart rate raised by training and never looked at
# activity, and named a cause in half the cases with none (docs/evaluation.md, 2026-11-10).
CAUSE_CANDIDATES = (
    "sleep_minutes",
    "bedtime_hour",
    "time_in_bed",
    "steps",
    "active_zone_minutes",
    "very_active_minutes",
    "strain",
    "sedentary_minutes",
)
CAUSES_GUIDE = (
    "The possible causes above were tested by code over the same days as the change. Explain the "
    "change only with a candidate marked 'a clear change' in that period, as 'went with', never "
    "'caused', with an association or change claim citing its evidence_id. If none moved, say "
    "plainly that nothing in their data explains it yet, as a no_change claim citing those "
    "tests, and do not reach for one that did not move."
)


def _related(metric: str, other: str) -> bool:
    """One is a score built from the other, or both feed one score: their moving together says
    nothing about a cause."""
    for score, inputs in BUILT_FROM.items():
        if (metric == score and other in inputs) or (other == score and metric in inputs):
            return True
    return False


# How big a change is, from |Cliff's delta| (Romano et al. 2006).
SIZES = ((0.47, "large"), (0.33, "medium"), (0.15, "small"), (0.0, "very small"))
MIN_OVERVIEW_DAYS = 5  # a shorter span than this compares too few days to say anything
MEDIUM, ALPHA = 0.33, 0.05
BROAD_GUIDE = (
    "How to work: the overview below compares every metric they have over the period, already "
    "corrected for testing them all at once, and ranks the clear changes by size. Answer from it "
    "and cite its evidence_ids. Lead with the clear changes in that order, across areas, not only "
    "one area; call a change the biggest, the main or the most only if it is first in the list. "
    "Say in one sentence which areas showed no clear change (not that they held steady: no clear "
    "change does not show they stayed the same), backing it with a no_change claim on one of that "
    "area's listed metrics. If nothing changed clearly, open with that ('Nothing has changed "
    "clearly over Oct 5 to Oct 18') and only then, if at all, a possible change with a hedge in "
    "the same sentence. Never write about the method (how many metrics or comparisons were "
    "tested, corrections). Look "
    "closer with compare_windows, change_point or trend only at a change the overview lists. A "
    "feeling they describe (tired, drained, stressed, off) is not something the watch measures: "
    "never say it is caused by or because of anything. Give the clear changes that could bear on "
    "it as possible contributors ('your time asleep is down, which can add to feeling tired'), "
    "most relevant first, and if their check-ins changed, say so. No hypotheses. Then call "
    "submit_findings."
)


def size_of(delta: float) -> str:
    return next(word for bound, word in SIZES if abs(delta) >= bound)


def overview_evidence(
    frame: pd.DataFrame,
    question: str,
    today: date | None,
    window: Window | None = None,
    baseline: Window | None = None,
) -> tuple[list[Evidence], str]:
    """Every metric compared over the period a broad question means (the last 14 days against the
    28 before when it names none), corrected for testing them all at once, the clear changes
    ranked by size: what changed most is code's to find, not the model's to pick (2026-11-18:
    asked "what changed most this month?", the agent compared four sleep metrics and named one
    that ranked fourth of eighteen, while two others had changed clearly)."""
    if frame.empty:
        return [], ""
    cleaned = without_low_wear(frame)
    if window is not None:
        # Days the request named, resolved by code, are the days answered: never swapped for the
        # latest data (Sept 1-3 and Dec 1-14 were answered with October, Codex's review).
        return _named_overview(cleaned, window, baseline)
    # The period phrase in the question, if any.
    asked = asked_period(question, today) if today else None
    last = min(asked[1], cleaned.index.max().date()) if asked else None
    # The period they named, if their data covers enough of it; otherwise their latest data (data
    # that stopped before the period would compare nothing).
    if asked and last and (last - asked[0]).days + 1 >= MIN_OVERVIEW_DAYS:
        recent = Window(start=asked[0], end=last)
        baseline_end = recent.start - timedelta(days=1)
        baseline = Window(start=baseline_end - timedelta(days=BASELINE_DAYS - 1), end=baseline_end)
    else:
        recent, baseline = screen_windows(cleaned)
    return _compared(cleaned, recent, baseline)


def _named_overview(
    frame: pd.DataFrame, window: Window, baseline: Window | None
) -> tuple[list[Evidence], str]:
    """Every metric over exactly the named days: compared with the days before them (or with the
    second named period) when there are enough, else described; days with no data at all say so."""
    if frame.empty:
        return [], ""
    first, last = frame.index.min().date(), frame.index.max().date()
    start, end = max(window.start, first), min(window.end, last)
    if start > end:
        return [], (
            f"The person asked about {window.start} to {window.end}; their data has no days "
            f"in it (it runs from {first} to {last}). Say so plainly; describe no other days."
        )
    recent = Window(start=start, end=end)
    if baseline is None and (end - start).days + 1 >= MIN_OVERVIEW_DAYS:
        before = recent.start - timedelta(days=1)
        baseline = Window(start=before - timedelta(days=BASELINE_DAYS - 1), end=before)
    if baseline is not None:
        records, text = _compared(frame, recent, baseline)
        if records:
            return records, text
    described = []
    for metric in frame.columns:
        if metric in NOT_SCREENED:
            continue
        try:
            record = describe(frame, metric, recent)
        except ToolError:
            continue
        if record.n:
            described.append(record)
    if not described:
        return [], (
            f"The person asked about {window.start} to {window.end}; no metric has data on "
            "those days. Say so plainly; describe no other days."
        )
    lines = [
        f"- {label(e.metrics[0])} (evidence_id {e.id}): "
        f"{evidence_payload(e)['display'].get('mean', '')} on average"
        for e in described
    ]
    return described, (
        f"Too few days ({recent.start} to {recent.end}) to test a change: what each metric was on "
        "exactly those days (describe), nothing outside them:\n" + "\n".join(lines)
    )


def _compared(frame: pd.DataFrame, recent: Window, baseline: Window) -> tuple[list[Evidence], str]:
    cleaned = frame
    tests = []
    for metric in cleaned.columns:
        if metric in NOT_SCREENED:
            continue
        try:
            record = compare_windows(cleaned, metric, recent, baseline)
        except ToolError:
            continue
        if record.sufficient:
            tests.append(record)
    if not tests:
        return [], ""
    tests = [
        e.model_copy(update={"stats": {**e.stats, "overview": True}}) for e in run_adjusted(tests)
    ]
    clear = sorted(
        (e for e in tests if is_significant(e)),
        key=lambda e: abs(e.stats.get("cliffs_delta") or 0),
        reverse=True,
    )
    ranks = {e.id: i for i, e in enumerate(clear, 1)}
    tests = [
        e.model_copy(update={"stats": {**e.stats, "overview_rank": ranks[e.id]}})
        if e.id in ranks
        else e
        for e in tests
    ]
    by_id = {e.id: e for e in tests}
    lines = []
    for e in clear:
        shown = evidence_payload(by_id[e.id])["display"]
        direction = "up" if (e.stats.get("difference") or 0) > 0 else "down"
        lines.append(
            f"{ranks[e.id]}. {label(e.metrics[0])} ({_area(e.metrics[0])}, evidence_id {e.id}): "
            f"{direction}, {shown.get('mean_recent', '')} against {shown.get('mean_baseline', '')}"
            f", a {size_of(e.stats.get('cliffs_delta') or 0)} change"
        )
    # A possible change: a medium or larger effect, significant on its own but not once every
    # metric's test is counted; worth naming with a hedge, never as a finding.
    possible = sorted(
        (
            e
            for e in tests
            if e.id not in ranks
            and (e.stats.get("p_value") or 1) < ALPHA
            and abs(e.stats.get("cliffs_delta") or 0) >= MEDIUM
        ),
        key=lambda e: abs(e.stats.get("cliffs_delta") or 0),
        reverse=True,
    )
    hedge = {e.id for e in possible}
    tests = [
        e.model_copy(update={"stats": {**e.stats, "overview_possible": True}})
        if e.id in hedge
        else e
        for e in tests
    ]
    steady: dict[str, list[str]] = {}
    for e in tests:
        if e.id not in ranks and e.id not in hedge:
            steady.setdefault(_area(e.metrics[0]), []).append(
                f"{label(e.metrics[0])} (evidence_id {e.id})"
            )
    head = (
        f"Overview: all {len(tests)} metrics with data compared, {recent.start:%b %-d} to "
        f"{recent.end:%b %-d} against {baseline.start:%b %-d} to {baseline.end:%b %-d}, corrected "
        "for testing them all at once."
    )
    parts = [head]
    if lines:
        parts.append("Clear changes, largest first:\n" + "\n".join(lines))
    else:
        parts.append("Clear changes: none.")
    if possible:
        parts.append(
            f"Possible changes, not clear once all {len(tests)} tests are counted (name one only "
            "with a hedge in the same sentence, such as 'though with this many checks that could "
            "be normal variation'), largest first:\n"
            + "\n".join(
                f"- {label(e.metrics[0])} ({_area(e.metrics[0])}, evidence_id {e.id}): "
                f"{'up' if (e.stats.get('difference') or 0) > 0 else 'down'}, "
                f"{evidence_payload(e)['display'].get('mean_recent', '')} against "
                f"{evidence_payload(e)['display'].get('mean_baseline', '')}"
                for e in possible
            )
        )
    if steady:
        parts.append(
            "No clear change (cite one of these to say an area showed no clear change): "
            + "; ".join(f"{area}: {', '.join(names)}" for area, names in sorted(steady.items()))
            + "."
        )
    return tests, "\n".join(parts)


def _area(metric: str) -> str:
    """The area a metric belongs to, by the expert who owns it."""
    found = owner(metric)
    return found.name if found else "other"


def candidate_causes(frame: pd.DataFrame, premise: "Premise") -> tuple[list[Evidence], str]:
    """Each everyday driver before and after the change the premise check confirmed, over the same
    windows, corrected for how many were tested: what explains it is code's to find, the
    wording the model's."""
    moved = [
        record for record in premise.evidence if is_significant(record) and len(record.windows) == 2
    ]
    if not moved:
        return [], ""
    target, recent = moved[0].metrics[0], moved[0].windows[0]
    tests = []
    for metric in CAUSE_CANDIDATES:
        if metric == target or metric not in frame.columns or _related(metric, target):
            continue
        # From the candidate's own change point: a cause often starts a few days before its
        # effect, and over the target's windows that start sat in the baseline and was missed.
        own_recent, own_baseline = _premise_windows(frame, metric, recent.end)
        try:
            record = compare_windows(frame, metric, own_recent, own_baseline)
        except ToolError:
            continue
        if record.sufficient:
            tests.append(record)
    if not tests:
        return [], ""
    tests = run_adjusted(tests)
    lines = []
    for record in tests:
        shown = evidence_payload(record)["display"]
        verdict = "a clear change" if is_significant(record) else "no clear change"
        lines.append(
            f"- {label(record.metrics[0])} (evidence_id {record.id}): since "
            f"{record.windows[0].start:%b %-d} {shown.get('mean_recent', '')} against "
            f"{shown.get('mean_baseline', '')}: {verdict}"
        )
    head = (
        f"Possible causes of the change since {recent.start:%b %-d}, each tested from when it "
        "changed, against the 28 days before:\n"
    )
    return tests, head + "\n".join(lines) + "\n" + CAUSES_GUIDE


@dataclass(frozen=True)
class Premise:
    holds: bool
    evidence: list[Evidence]
    text: str


def _assumed_direction(question: str, metric: str) -> str | None:
    """Which way the question assumes `metric` has moved, or None if it assumes nothing."""
    good_is_up = BETTER.get(metric, "up") == "up"
    if PREMISE_WORSE.search(question):
        return "down" if good_is_up else "up"
    if PREMISE_BETTER.search(question):
        return "up" if good_is_up else "down"
    if PREMISE_DOWN.search(question):
        return "down"
    if PREMISE_UP.search(question):
        return "up"
    return None


def _premise_windows(frame: pd.DataFrame, metric: str, end: date) -> tuple[Window, Window]:
    """The last 14 days against the 28 before, unless the metric clearly shifted on a day in the
    last six weeks: then from that day on against the 28 days before it. With a fixed 14 days, a
    change that began three weeks ago had a week of itself in the baseline and was missed."""
    recent = Window(start=end - timedelta(days=PREMISE_RECENT - 1), end=end)
    try:
        found = change_point(
            frame, metric, Window(start=end - timedelta(days=PREMISE_SEARCH - 1), end=end)
        )
    except ToolError:
        found = None
    if found is not None and found.sufficient and is_significant(found):
        start = date.fromisoformat(found.stats["change_date"])
        if (end - start).days + 1 >= MIN_PREMISE_DAYS and (end - start).days < PREMISE_SEARCH - 28:
            recent = Window(start=start, end=end)
    baseline = Window(
        start=recent.start - timedelta(days=PREMISE_BASELINE), end=recent.start - timedelta(days=1)
    )
    return recent, baseline


# "Around Aug 15": people name the day something started, so a week mostly after it.
NAMED_DAY_BEFORE, NAMED_DAY_AFTER = 1, 5


def named_day(question: str, end: date) -> date | None:
    """The day a question names ("around August 15", "15 Aug", "2026-08-15"), in the latest year
    that puts it on or before `end`; None if it names none, or more than one."""
    found: set[date] = set()
    for year, month, day in ISO_DATE.findall(question):
        try:
            found.add(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    pairs = [(MONTHS[m.lower()], int(d)) for m, d in MONTH_DAY.findall(question)]
    pairs += [(MONTHS[m.lower()], int(d)) for d, m in DAY_MONTH.findall(question)]
    for month, day in pairs:
        for year in (end.year, end.year - 1):
            try:
                candidate = date(year, month, day)
            except ValueError:
                break
            if candidate <= end:
                found.add(candidate)
                break
    return found.pop() if len(found) == 1 else None


def check_premise(frame: pd.DataFrame, question: str, lead: str | None) -> Premise | None:
    """Whether what the question takes for granted is true: "why is my sleep worse?" may rest on
    nothing, and an answer that goes along with it invents a problem. Tested before the model."""
    if frame.empty or not ASSUMES_A_CHANGE.search(question):
        return None
    named = [m for m, pattern in MENTIONS.items() if pattern.search(question)]
    metrics = [m for m in named or PREMISE_METRICS.get(lead, ()) if m in frame.columns]
    end = frame.index.max().date()
    # "Why did my sleep drop around Aug 15?" is about Aug 15, not the latest weeks.
    day = named_day(question, end)
    tests = []
    for metric in metrics[:3]:
        if _assumed_direction(question, metric) is None:
            continue
        if day is not None:
            recent = Window(
                start=day - timedelta(days=NAMED_DAY_BEFORE),
                end=min(end, day + timedelta(days=NAMED_DAY_AFTER)),
            )
            baseline = Window(
                start=recent.start - timedelta(days=PREMISE_BASELINE),
                end=recent.start - timedelta(days=1),
            )
        else:
            recent, baseline = _premise_windows(frame, metric, end)
        try:
            record = compare_windows(frame, metric, recent, baseline)
        except ToolError:
            continue
        if record.sufficient:
            tests.append(record)
    if not tests:
        return None
    tests = run_adjusted(tests)

    def moved(record: Evidence) -> bool:
        metric = record.metrics[0]
        change = record.stats["mean_recent"] - record.stats["mean_baseline"]
        wanted = _assumed_direction(question, metric)
        return is_significant(record) and (change > 0) == (wanted == "up")

    holds = any(moved(record) for record in tests)
    lines = []
    for record in tests:
        shown = evidence_payload(record)["display"]
        lines.append(
            f"- {label(record.metrics[0])} (evidence_id {record.id}): "
            f"{record.windows[0].start:%b %-d} to {record.windows[0].end:%b %-d} "
            f"{shown.get('mean_recent', '')}, the 28 days before {shown.get('mean_baseline', '')}"
            f": {'a clear change' if moved(record) else 'no clear change that way'}"
        )
    verdict = "It holds." if holds else "It does not hold: nothing shows this change."
    period = (
        f" They ask about {day:%b %-d}: look at the days around it, not the latest weeks."
        if day is not None
        else ""
    )
    return Premise(
        holds,
        tests,
        f"Checked what the question assumes.{period} {verdict}\n" + "\n".join(lines),
    )


FIGURE = re.compile(r"\d")
A_PERIOD = re.compile(r"\b\d+\s*(?:days?|nights?|weeks?|months?|years?)\b", re.IGNORECASE)
UNSTATED = ("data_quality", "guidance")  # what needs no figure of its own


def figures_check(claims: list, summary: str) -> list[str]:
    """An answer about their data says its figures: "less than usual" or "held steady" alone made
    the person ask again (2026-11-14). The verifier already holds every number to the evidence."""
    undated = ISO_DATE.sub(" ", MONTH_DAY.sub(" ", DAY_MONTH.sub(" ", summary)))  # "Nov 14"
    undated = A_PERIOD.sub(" ", undated)  # "over the last 3 months" is no figure either
    if any(c.kind not in UNSTATED for c in claims) and not FIGURE.search(undated):
        return [
            "give the figures themselves in the summary, as shown under display: a day's value "
            "and its usual range ('6 h 10 min, against your usual 6 h 50 min to 7 h 40 min'), or "
            "the two averages compared ('7 h 2 min on weekends, 7 h 10 min on weekdays')"
        ]
    return []


def premise_answer_check(claims: list, summary: str) -> list[str]:
    """When the premise is false, the answer has to open by saying so."""
    opening = re.split(r"(?<=[.!?])\s", summary.strip(), maxsplit=1)[0]
    if DENIES.search(opening):
        return []
    return ["open by saying the change they assume is not in their data, kindly, then go on"]
