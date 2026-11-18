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


def _span(window: Window) -> str:
    return (
        str(window.start) if window.start == window.end else f"{window.start} through {window.end}"
    )


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
            text = f"{_span(window)}: {stats['meals_logged']} confirmed food entries."
            totals = stats["totals"]
            names = {
                "energyKcal": ("energy consumed", "kcal"),
                "proteinG": ("protein", "g"),
                "carbohydrateG": ("carbohydrate", "g"),
                "fatG": ("fat", "g"),
            }
            for key, (name, unit) in names.items():
                if totals[key] is not None:
                    text += f" {name.capitalize()}: {totals[key]:g} {unit} in recorded entries."
            text += " Unlogged food and missing nutrient values are not included."
            say(text, record, "food_logs")
            if stats["names"]:
                statements.append("Recorded foods: " + ", ".join(stats["names"][:10]) + ".")
                if len(stats["names"]) > 10:
                    statements.append(
                        "The first ten are listed here; the count includes all entries."
                    )
            continue
        if op == "correlate":
            try:
                record = tested(index, part.metrics[-1])
            except ToolError:
                statements.append(
                    f"{_span(window)}: those two measurements are not both available."
                )
                continue
            result.evidence[record.id] = record
            stats = record.stats
            names = " and ".join(label(m) for m in part.metrics)
            if not record.sufficient or stats["rho"] is None:
                statements.append(
                    f"{_span(window)}: insufficient paired data to establish a "
                    f"relationship between {names}."
                )
            elif stats[RUN_ADJUSTED] < 0.05:
                positive = stats["rho"] > 0
                text = (
                    f"{_span(window)}: {names} tended to move "
                    f"{'together' if positive else 'in opposite directions'} "
                    f"(Spearman rho {stats['rho']:g}, adjusted p {stats[RUN_ADJUSTED]:g})."
                )
                say(text, record, part.metrics[-1], "association", "up" if positive else "down")
            else:
                say(
                    f"{_span(window)}: no clear association was detected between {names} "
                    f"(Spearman rho {stats['rho']:g}, adjusted p {stats[RUN_ADJUSTED]:g}). "
                    "That does not establish that no relationship exists.",
                    record,
                    part.metrics[-1],
                    "no_change",
                )
            statements.append("These observational data cannot establish or rule out a cause.")
            continue
        for metric in part.metrics:
            prefix = f"{_span(window)} — {label(metric)}"
            if metric not in frame:
                statements.append(
                    f"{prefix}: this measurement is not available; no other metric "
                    "has been substituted."
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
                            f"{prefix}: no recorded days to count; missing is not zero."
                        )
                        continue
                    # This is an observed count, not a population or change inference.
                    record = record.model_copy(update={"sufficient": True})
                    text = (
                        f"{prefix}: {s['days_met']} of {s['days_counted']} recorded days "
                        f"{part.comparison} {format_level(metric, part.threshold)}; "
                        f"{s['days_equal']} days exactly equal to the threshold."
                    )
                elif op == "coverage":
                    record = coverage(frame[[metric]], window)
                    text = (
                        f"{prefix}: {record.stats['fraction_present'][metric]:.1%} of "
                        "calendar days have recorded values."
                    )
                    say(text, record, metric, "data_quality")
                    continue
                elif op == "compare":
                    record = tested(index, metric)
                    s = record.stats
                    if not record.sufficient:
                        statements.append(
                            f"{prefix} versus {_span(windows[1])}: too few "
                            "observed days for a reliable change test."
                        )
                        result.evidence[record.id] = record
                        continue
                    changed = s[RUN_ADJUSTED] < 0.05
                    direction = "up" if s["difference"] > 0 else "down"
                    text = (
                        f"{prefix}: mean {format_level(metric, s['mean_recent'])}; "
                        f"{_span(windows[1])}: mean {format_level(metric, s['mean_baseline'])}. "
                        + (
                            f"A change {direction} was detected."
                            if changed
                            else "No clear change was detected; this is not proof of stability."
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
                        statements.append(f"{prefix}: too few observed days for a reliable trend.")
                        result.evidence[record.id] = record
                        continue
                    changed = s[RUN_ADJUSTED] < 0.05
                    direction = "up" if s["slope_per_day"] > 0 else "down"
                    text = f"{prefix}: " + (
                        f"a trend {direction} was detected."
                        if changed
                        else "no clear trend was detected."
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
                            f"{prefix}: a total is not meaningful for this metric; "
                            "please choose a mean, median or individual day."
                        )
                        continue
                    record = describe(frame, metric, window)
                    if not record.n:
                        result.evidence[record.id] = record
                        statements.append(
                            f"{prefix}: no recorded values in this period. Missing "
                            "values are not zero."
                        )
                        continue
                    record = record.model_copy(
                        update={"tool": "observed_summary", "sufficient": True}
                    )
                    key = {"sum": "total", "value": "mean", "describe": "mean"}.get(op, op)
                    statistic = {
                        "sum": "total",
                        "value": "recorded",
                        "mean": "daily average",
                        "describe": "daily average",
                    }.get(op, op)
                    days = "day" if record.n == 1 else "days"
                    text = (
                        f"{prefix}: {statistic} {format_level(metric, record.stats[key])} "
                        f"from {record.n} recorded {days}."
                    )
                    if record.n < window.days:
                        text += " Missing days were excluded."
                    if metric == "checkin_rating":
                        text += " This is the morning rating, not the recovery score."
                say(text, record, metric)
            except ToolError:
                statements.append(
                    f"{prefix}: that computation cannot be performed for these inputs."
                )
            finally:
                if record is not None:
                    result.evidence[record.id] = record
        # Always retain coverage limitations with activity observations; never call nonwear rest.
        if "wear_minutes" in frame and any(m in ADDITIVE for m in part.metrics):
            record = coverage(frame, window)
            result.evidence[record.id] = record
            if record.stats.get("low_wear_days"):
                say(
                    f"{_span(window)}: some days have low wear time. Recorded activity totals "
                    "may understate movement; a lower total alone does not establish "
                    "less activity.",
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
