"""Execute a validated statistical request and render its result from the same evidence.

The model cannot turn an available median into an unavailable answer, choose a proxy metric,
or label a count with a different comparison here. More open-ended investigations retain the
expert loop. These descriptive answers make no inferential claims from sparse observations.
"""

import uuid
from collections.abc import Sequence
from datetime import date

import pandas as pd

from app.agent.agent import AgentResult
from app.agent.present import format_level, label
from app.agent.requests import Request
from app.agent.verifier import RUN_ADJUSTED, Claim, run_adjusted
from app.analysis.evidence import Evidence, ToolError, Window
from app.analysis.habits import goal_progress
from app.analysis.logs import food_entries
from app.analysis.tools import ADDITIVE, compare_windows, correlate, coverage, describe, trend

COMPARISONS = {">": "above", ">=": "at_least", "<": "below", "<=": "at_most", "==": "exactly"}


def _when(window: Window, today: date) -> str:
    """ "on Sun, Nov 8" or "from Mon, Nov 2 to Sun, Nov 8", with the year when it is not this
    one. Said in words, as a person reads it: the answer used to begin "2026-11-08 —"."""
    form = "%a, %b %-d" if window.start.year == window.end.year == today.year else "%a, %b %-d %Y"
    if window.start == window.end:
        return f"on {window.start.strftime(form)}"
    return f"from {window.start.strftime(form)} to {window.end.strftime(form)}"


def _first_up(text: str) -> str:
    return text[:1].upper() + text[1:]


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


SAID = {">": "above", ">=": "at or above", "<": "below", "<=": "at or below", "==": "exactly"}
STATISTIC = {
    "sum": "Total",
    "value": "",
    "mean": "Daily average",
    "describe": "Daily average",
    "median": "Median",
    "min": "Lowest",
    "max": "Highest",
}


def execute(
    request: Request, frame: pd.DataFrame, today: date, *, food_logs: Sequence[dict] = (), zone=None
) -> AgentResult:
    result = AgentResult(run_id=uuid.uuid4().hex[:12], stop_reason="requested")
    statements = []

    def say(text: str, record: Evidence, metric: str, kind="value", direction=None):
        result.evidence[record.id] = record
        result.claims.append(
            Claim(
                text=text, kind=kind, evidence_ids=[record.id], metric=metric, direction=direction
            )
        )
        statements.append(text)

    def _span(window: Window) -> str:
        return _when(window, today)

    first = frame.index.min().date() if not frame.empty else today
    last = frame.index.max().date() if not frame.empty else today
    tests, errors = {}, {}
    # Make the statistical family before interpreting any test. A multi-metric request must
    # not silently multiply its opportunity to report a false positive.
    for index, part in enumerate(request.parts):
        windows = part.windows or [Window(start=first, end=last)]
        for metric in part.metrics[-1:] if part.operation == "correlate" else part.metrics:
            key = index, metric
            try:
                if part.operation == "correlate":
                    tests[key] = correlate(frame, *part.metrics, windows[0], max_lag=part.max_lag)
                elif part.operation == "compare":
                    tests[key] = compare_windows(frame, metric, *windows)
                elif part.operation == "trend":
                    tests[key] = trend(frame, metric, windows[0])
            except ToolError as error:
                errors[key] = error
    corrected = {e.id: e for e in run_adjusted(list(tests.values()))}
    tests = {key: corrected[e.id] for key, e in tests.items()}

    def tested(index, metric):
        if (index, metric) in errors:
            raise errors[index, metric]
        return tests[index, metric]

    for index, part in enumerate(request.parts):
        windows = part.windows or [Window(start=first, end=last)]
        window = windows[0]
        op = part.operation
        if op == "food" or part.metrics == ["food_logs"]:
            # Logged food is not restricted to the wearable export's dates.
            if part.history:
                window = Window(start=date(1970, 1, 1), end=today)
            record = food_entries(food_logs, window, zone, part.meal_type)
            stats = record.stats
            entries = stats["meals_logged"]
            text = (
                f"{_first_up(_span(window))} you logged {entries} "
                f"{'entry' if entries == 1 else 'entries'}."
            )
            totals = stats["totals"]
            names = {
                "energyKcal": ("energy consumed", "kcal"),
                "proteinG": ("protein", "g"),
                "carbohydrateG": ("carbohydrate", "g"),
                "fatG": ("fat", "g"),
            }
            for key, (name, unit) in names.items():
                if totals[key] is not None:
                    text += f" {name.capitalize()}: {totals[key]:,g} {unit}."
            text += " Only what you logged is counted, and missing nutrient values aren't guessed."
            say(text, record, "food_logs")
            if stats["names"]:
                statements.append("Foods: " + ", ".join(stats["names"][:10]) + ".")
                if len(stats["names"]) > 10:
                    statements.append("Those are the first ten; the count includes them all.")
            continue
        if op == "correlate":
            try:
                record = tested(index, part.metrics[-1])
            except ToolError:
                statements.append(
                    f"{_first_up(_span(window))}, those two aren't both in your data, so I "
                    "can't compare them."
                )
                continue
            result.evidence[record.id] = record
            stats = record.stats
            names = " and ".join(label(m) for m in part.metrics)
            if stats["rho"] is None and stats.get("paired_days") == 0:
                statements.append(
                    f"{_first_up(_span(window))}, {names} were never recorded on the same "
                    "days, so whether they go together can't be told."
                )
            elif (
                stats["rho"] is None
                and stats.get("paired_days", 0) >= 3
                and not stats.get("both_vary", True)
            ):
                statements.append(
                    f"{_first_up(_span(window))}, one of {names} didn't change at all, so "
                    "whether they go together can't be told from these days."
                )
            elif not record.sufficient or stats["rho"] is None:
                statements.append(
                    f"{_first_up(_span(window))}, there aren't enough days with both {names} "
                    "to say whether they go together."
                )
            elif stats[RUN_ADJUSTED] < 0.05:
                positive = stats["rho"] > 0
                text = (
                    f"{_first_up(_span(window))}, {names} tended to move "
                    f"{'together' if positive else 'in opposite directions'} "
                    f"(correlation {stats['rho']:g})."
                )
                say(text, record, part.metrics[-1], "association", "up" if positive else "down")
            else:
                say(
                    f"{_first_up(_span(window))}, {names} showed no clear link "
                    f"(correlation {stats['rho']:g}). That doesn't mean there is none, only "
                    "that your data doesn't show one.",
                    record,
                    part.metrics[-1],
                    "no_change",
                )
            if record.sufficient and stats["rho"] is not None:
                statements.append(
                    "Data like this shows what goes together; it can't establish or rule out "
                    "a cause."
                )
            elif request.kind == "causality":  # they asked about a cause: answer that too
                statements.append(
                    "Without a link to look at, your data can't say whether one affects the other."
                )
            continue
        if op == "coverage" and len(part.metrics) > 1 and all(m in frame for m in part.metrics):
            together = coverage(frame[list(part.metrics)], window)
            labels = [label(m) for m in part.metrics]
            names = (
                f"both {labels[0]} and {labels[1]}"
                if len(labels) == 2
                else f"all of {', '.join(labels[:-1])} and {labels[-1]}"
            )
            say(
                f"{_first_up(_span(window))}, {_days(together.stats['days_all_present'])} had "
                f"{names} recorded.",
                together,
                part.metrics[0],
                "data_quality",
            )
        for metric in part.metrics:
            name, when = label(metric), _span(window)
            if metric not in frame:
                statements.append(
                    f"Your data doesn't include {name}, so I haven't used another measure in "
                    "its place."
                )
                continue
            record = None
            try:
                if op == "count":
                    record = goal_progress(
                        frame, metric, part.threshold, COMPARISONS[part.comparison], window
                    )
                    s = record.stats
                    if not s["days_counted"]:
                        statements.append(
                            f"There's no {name} recorded {when}, so there's nothing to count "
                            "(missing days aren't counted as zero)."
                        )
                        continue
                    # This is an observed count, not a population or change inference.
                    record = record.model_copy(update={"sufficient": True})
                    level = format_level(metric, part.threshold)
                    text = (
                        f"{_first_up(when)}, {s['days_met']} of {_days(s['days_counted'])} "
                        f"with data had {name} {SAID[part.comparison]} {level}"
                    )
                    if part.comparison != "==":
                        text += f"; {_days(s['days_equal'])} exactly at {level}"
                    text += "."
                elif op == "coverage":
                    # Counted, not a share alone: "how many HRV days were recorded?"
                    record = coverage(frame[[metric]], window)
                    have = record.stats["days_present"][metric]
                    text = (
                        f"{_first_up(name)} was recorded on {have} of {_days(window.days)} "
                        f"{when}; {_days(window.days - have)} have no reading."
                    )
                    say(text, record, metric, "data_quality")
                    continue
                elif op == "compare":
                    record = tested(index, metric)
                    s = record.stats
                    if not record.sufficient:
                        statements.append(
                            f"There are too few days with {name} {when} and "
                            f"{_span(windows[1])} to tell whether it changed."
                        )
                        result.evidence[record.id] = record
                        continue
                    changed = s[RUN_ADJUSTED] < 0.05
                    direction = "up" if s["difference"] > 0 else "down"
                    text = (
                        f"{_first_up(name)} averaged {format_level(metric, s['mean_recent'])} "
                        f"{when}, against {format_level(metric, s['mean_baseline'])} "
                        f"{_span(windows[1])}. "
                        + (
                            f"That's a clear {'rise' if direction == 'up' else 'drop'}."
                            if changed
                            else "That's no clear change, though it doesn't prove it stayed "
                            "the same."
                        )
                    )
                    say(
                        text,
                        record,
                        metric,
                        "change" if changed else "no_change",
                        direction if changed else None,
                    )
                    continue
                elif op == "trend":
                    record = tested(index, metric)
                    s = record.stats
                    if not record.sufficient:
                        statements.append(
                            f"There are too few days with {name} {when} to see a trend."
                        )
                        result.evidence[record.id] = record
                        continue
                    changed = s[RUN_ADJUSTED] < 0.05
                    direction = "up" if s["slope_per_day"] > 0 else "down"
                    text = f"{_first_up(when)}, {name} " + (
                        f"trended {'upward' if direction == 'up' else 'downward'}."
                        if changed
                        else "showed no clear trend."
                    )
                    say(
                        text,
                        record,
                        metric,
                        "change" if changed else "no_change",
                        direction if changed else None,
                    )
                    continue
                else:
                    if op == "sum" and metric not in ADDITIVE:
                        statements.append(
                            f"A total doesn't make sense for {name}. I can give the daily "
                            "average, the median or a single day instead."
                        )
                        continue
                    record = describe(frame, metric, window)
                    if not record.n:
                        result.evidence[record.id] = record
                        statements.append(
                            f"There's no {name} recorded {when}. Missing days aren't counted "
                            "as zero."
                        )
                        continue
                    record = record.model_copy(
                        update={"tool": "observed_summary", "sufficient": True}
                    )
                    key = {"sum": "total", "value": "mean", "describe": "mean"}.get(op, op)
                    statistic = STATISTIC.get(op, op.capitalize())
                    if op == "value" and window.days > 1:  # one reading per day, over several
                        statistic = "Daily average"
                    value = format_level(metric, record.stats[key])
                    what = f"{statistic} {name}" if statistic else _first_up(name)
                    text = f"{what} {when}: {value}"
                    if window.days > 1:
                        text += f", from {_days(record.n)} with data"
                    text += "."
                    if record.n < window.days and window.days > 1:
                        text += " Missing days were left out, not counted as zero."
                    if metric == "checkin_rating":
                        text += " That's your morning check-in rating, not your recovery score."
                say(text, record, metric)
            except ToolError:
                statements.append(f"I couldn't work out {name} {when} from your data.")
            finally:
                if record is not None:
                    result.evidence[record.id] = record
        # Always retain coverage limitations with activity observations; never call nonwear rest.
        if "wear_minutes" in frame and any(m in ADDITIVE for m in part.metrics):
            record = coverage(frame, window)
            result.evidence[record.id] = record
            if record.stats.get("low_wear_days"):
                say(
                    f"Some days {_span(window)} had low wear time, so activity totals may "
                    "undercount how much you moved; a lower total alone doesn't mean you "
                    "moved less.",
                    record,
                    part.metrics[0],
                    "data_quality",
                )
    result.trace.extend(
        {
            "type": "tool",
            "name": e.tool,
            "evidence_id": e.id,
            "metrics": list(e.metrics),
            "windows": [w.model_dump(mode="json") for w in e.windows],
        }
        for e in result.evidence.values()
    )
    result.budget.tool_calls = len(result.evidence)
    result.summary = "\n\n".join(statements)
    return result
