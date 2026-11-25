"""The sentences a supervisor reads for the team's observed figures, written by code.

"Median sleep last night: 7 h 10 min, based on 6 members." No model, no person, no change: what
changed from usual is the weekly report's job, once members have the history for it.
"""

from datetime import date, timedelta

from app.analysis.evidence import Evidence
from app.analysis.report import format_value

NAMES = {
    "sleep_minutes": "Median sleep",
    "resting_hr": "Median resting heart rate",
    "hrv_ms": "Median heart rate variability",
    "steps": "Median steps",
    "active_zone_minutes": "Median Active Zone Minutes",
}


def _when(kind: str, day: date, today: date) -> str:
    if kind == "date":
        return f"on {day:%b} {day.day}"
    if kind == "night":
        return "last night" if day == today else f"the night to {day:%a %b} {day.day}"
    return "yesterday" if day == today - timedelta(days=1) else f"on {day:%a %b} {day.day}"


def _value(metric: str, value: float) -> str:
    if metric == "sleep_minutes":
        minutes = round(value)
        return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"
    if metric == "steps":
        return f"{round(value):,}"
    if metric == "resting_hr":  # whole beats; a median of an even count can end in .5
        return f"{value:.1f}".removesuffix(".0") + " bpm"
    return format_value(metric, value)


def sentence(evidence: Evidence, today: date) -> str:
    metric = evidence.metrics[0]
    day = evidence.windows[0].end
    when = _when(evidence.stats["kind"], day, today)
    figure = _value(metric, evidence.stats["median"])
    return f"{NAMES[metric]} {when}: {figure}, based on {evidence.n} members."
