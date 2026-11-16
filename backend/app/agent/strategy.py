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
from app.agent.llm import Budget
from app.agent.present import clock, label
from app.agent.strategy_types import DEFAULT_TYPE
from app.agent.tools import TOOLS, Toolbox, evidence_payload
from app.agent.verifier import DAY_MONTH, ISO_DATE, MENTIONS, MONTH_DAY, MONTHS, run_adjusted
from app.agent.verifier import _significant as is_significant
from app.analysis.coaching import WEEKDAYS, habit_options, personal_options
from app.analysis.day import compare_day
from app.analysis.evidence import Evidence, ToolError, Window
from app.analysis.habits import BETTER
from app.analysis.tools import change_point, compare_windows, correlate

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
        "the day's date in the answer, and give each value with the usual range as shown under "
        "display ('6 h 10 min, against your usual 6 h 50 min to 7 h 40 min'). "
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
        "as they ask for up to five, as claims of kind suggestion: first what tested as supported, "
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
    frame: pd.DataFrame, metrics: list[str], day: date | None = None
) -> tuple[list[Evidence], str]:
    """One day (the latest, unless given) against the usual range for the main metrics in scope,
    as evidence."""
    if frame.empty:
        return [], ""
    name = "the day asked about" if day else "the latest day"
    day = day or frame.index.max().date()
    found = []
    for metric in SNAPSHOT_METRICS:
        if metric not in metrics:
            continue
        try:
            evidence = compare_day(frame, metric, day)
        except ToolError:
            continue
        if "position" in evidence.stats:
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
) -> tuple[list[Evidence], str]:
    """habit_options and personal_options on the goal's metrics over the last 60 days, run before
    the model starts."""
    if frame.empty:
        return [], ""
    end = frame.index.max().date()
    window = Window(start=end - timedelta(days=COACHING_DAYS - 1), end=end)
    found, lines, stands_out = [], [], []
    for metric in GOALS.get(expert, GOALS[None]):
        if metric not in metrics or metric not in frame.columns:
            continue
        try:
            evidence = _fitting(habit_options(frame, metric, window), skip_levers, skip_options)
        except ToolError:
            continue
        found.append(evidence)
        supported = [lever["habit"] for lever in evidence.stats["levers"] if lever["supported"]]
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
