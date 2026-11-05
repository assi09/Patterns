"""How metrics read for people: names, units and formatted values.

Presentation only. The daily table, the evidence and the database keep their raw units; this module
turns them into what a person reads ("time asleep", "7 h 12 min", "23:30", "Aug 15"), both for the
model writing findings and for checking that what it wrote matches the evidence. Names follow the
app's labels in `mobile/src/lib/format.ts`.
"""

from dataclasses import dataclass
from datetime import date

from app.analysis.evidence import Evidence


@dataclass(frozen=True)
class MetricInfo:
    label: str
    unit: str  # minutes, clock, count, kcal, km, bpm, ms, breaths, percent, celsius, score, load


METRICS: dict[str, MetricInfo] = {
    "steps": MetricInfo("steps", "count"),
    "checkin_rating": MetricInfo("morning check-in rating", "score"),
    "calories": MetricInfo("calories burned", "kcal"),
    "distance_km": MetricInfo("distance", "km"),
    "active_zone_minutes": MetricInfo("Active Zone Minutes", "minutes"),
    "cardio_load": MetricInfo("cardio load", "load"),
    "resting_hr": MetricInfo("resting heart rate", "bpm"),
    "hrv_ms": MetricInfo("heart rate variability (HRV)", "ms"),
    "respiratory_rate": MetricInfo("breathing rate", "breaths"),
    "readiness": MetricInfo("readiness", "score"),
    "skin_temp_variation_c": MetricInfo("skin temperature compared with your usual", "celsius"),
    "sedentary_minutes": MetricInfo("sedentary time", "minutes"),
    "lightly_active_minutes": MetricInfo("light activity", "minutes"),
    "moderately_active_minutes": MetricInfo("moderate activity", "minutes"),
    "very_active_minutes": MetricInfo("vigorous activity", "minutes"),
    "wear_minutes": MetricInfo("wear time", "minutes"),
    "sleep_minutes": MetricInfo("time asleep", "minutes"),
    "time_in_bed": MetricInfo("time in bed", "minutes"),
    "sleep_efficiency": MetricInfo("sleep efficiency", "percent"),
    "sleep_score": MetricInfo("sleep score", "score"),
    "deep_sleep_minutes": MetricInfo("deep sleep", "minutes"),
    "light_sleep_minutes": MetricInfo("light sleep", "minutes"),
    "rem_sleep_minutes": MetricInfo("REM sleep", "minutes"),
    "awake_in_bed_minutes": MetricInfo("time awake in bed", "minutes"),
    "bedtime_hour": MetricInfo("bedtime", "clock"),
    "recovery_score": MetricInfo("recovery score", "score"),
    "strain": MetricInfo("strain", "score"),
    "stress_score": MetricInfo("stress score", "score"),
    "hr_zone_light_minutes": MetricInfo("time in the light heart-rate zone", "minutes"),
    "hr_zone_moderate_minutes": MetricInfo("time in the fat-burn heart-rate zone", "minutes"),
    "hr_zone_vigorous_minutes": MetricInfo("time in the cardio heart-rate zone", "minutes"),
    "hr_zone_peak_minutes": MetricInfo("time in the peak heart-rate zone", "minutes"),
    "still_minutes": MetricInfo("time still while awake", "minutes"),
    "still_hr_above_resting": MetricInfo("heart rate while still, above resting", "bpm"),
}

# Statistics that are a level of the metric, and ones that are a difference between levels.
LEVEL_KEYS = (
    "mean",
    "median",
    "min",
    "max",
    "mean_recent",
    "mean_baseline",
    "mean_before",
    "mean_after",
    "mean_weekend",
    "mean_weekday",
    "value",
    "usual_median",
    "usual_low",
    "usual_high",
)
CHANGE_KEYS = ("difference", "change_over_window")

SUFFIXES = {
    "count": "",
    "kcal": " kcal",
    "km": " km",
    "bpm": " bpm",
    "ms": " ms",
    "breaths": " breaths a minute",
    "percent": "%",
    "celsius": " °C",
    "score": "",
    "load": "",
}


def label(metric: str) -> str:
    info = METRICS.get(metric)
    return info.label if info else metric.replace("_", " ")


def duration(minutes: float) -> str:
    """45 -> "45 min", 432 -> "7 h 12 min"."""
    total = round(abs(minutes))
    hours, rest = divmod(total, 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def clock(hours: float) -> str:
    """A time of day from hours relative to midnight: -0.5 -> "23:30", 1.25 -> "01:15"."""
    minutes = round((hours % 24) * 60) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _number(value: float) -> str:
    digits = 0 if abs(value) >= 100 else 1
    text = f"{value:,.{digits}f}"
    return text[:-2] if text.endswith(".0") else text


def format_level(metric: str, value: float) -> str:
    unit = METRICS[metric].unit if metric in METRICS else "count"
    if unit == "minutes":
        return duration(value)
    if unit == "clock":
        return clock(value)
    return _number(value) + SUFFIXES.get(unit, "")


def format_change(metric: str, value: float) -> str:
    """The size of a difference, without its sign: the wording carries the direction."""
    unit = METRICS[metric].unit if metric in METRICS else "count"
    if unit == "minutes":
        return duration(value)
    if unit == "clock":
        return duration(value * 60)  # a bedtime shift reads as minutes
    return _number(abs(value)) + SUFFIXES.get(unit, "")


def short_date(day: date | str) -> str:
    day = date.fromisoformat(day) if isinstance(day, str) else day
    return f"{day:%b} {day.day}"


def display(evidence: Evidence) -> dict[str, str]:
    """The evidence's values as a person would read them, for the model to quote."""
    if len(evidence.metrics) != 1:
        shown: dict[str, str] = {}
    else:
        metric = evidence.metrics[0]
        shown = {
            key: format_level(metric, value)
            for key, value in evidence.stats.items()
            if key in LEVEL_KEYS and value is not None
        }
        shown |= {
            key: format_change(metric, value)
            for key, value in evidence.stats.items()
            if key in CHANGE_KEYS and value is not None
        }
        if (pct := evidence.stats.get("pct_change")) is not None:
            shown["pct_change"] = f"{abs(pct):.0f}%"
    shown |= _extra_display(evidence)
    if change_date := evidence.stats.get("change_date"):
        shown["change_date"] = short_date(change_date)
    shown["windows"] = ", ".join(
        f"{short_date(w.start)} to {short_date(w.end)}" for w in evidence.windows
    )
    return shown


def _extra_display(evidence: Evidence) -> dict[str, str]:
    """Readable values for the tools whose results are not a single metric's levels."""
    stats, shown = evidence.stats, {}
    metric = evidence.metrics[0] if evidence.metrics else ""
    if evidence.tool == "habit_options":
        if (split := stats.get("split_at")) is not None:
            shown["split_at"] = clock(split)
        shown["levers"] = "; ".join(
            f"{lever['habit']} ({'supported' if lever['supported'] else 'not supported'}): "
            f"{lever['group']} {format_level(metric, lever['mean_with'])}, "
            f"{lever['other_group']} {format_level(metric, lever['mean_without'])}"
            for lever in stats.get("levers", [])
            if lever.get("mean_with") is not None and lever.get("mean_without") is not None
        )
    elif evidence.tool == "personal_options":
        shown["options"] = "; ".join(option["note"] for option in stats.get("options", []))
    elif evidence.tool == "sleep_regularity":
        if (median := stats.get("median")) is not None:
            shown["median"] = clock(median)
        for key in ("bedtime_spread_minutes", "wake_spread_minutes"):
            if stats.get(key) is not None:
                shown[key] = duration(stats[key])
        if (shift := stats.get("weekend_shift_minutes")) is not None:
            shown["weekend_shift_minutes"] = (
                f"{duration(shift)} {'later' if shift > 0 else 'earlier'} on weekends"
            )
    elif evidence.tool == "rank_days":
        shown["days"] = ", ".join(
            f"{short_date(d['day'])}: {format_level(metric, d['value'])}"
            for d in stats.get("days", [])
        )
    elif evidence.tool == "usual_ranges":
        shown["ranges"] = "; ".join(
            f"{label(m)} {format_level(m, r['low'])} to {format_level(m, r['high'])}"
            for m, r in stats.get("ranges", {}).items()
        )
    elif evidence.tool == "tag_effect" and stats.get("mean_with") is not None:
        tag = str(stats.get("tag", "")).replace("_", " ")
        shown["with_tag"] = f"{format_level(metric, stats['mean_with'])} on days with {tag}"
        shown["without_tag"] = f"{format_level(metric, stats['mean_without'])} on days without"
    return shown


def column(name: str) -> str:
    """The metric a name refers to: a column name as it is, or what people call it ("bedtime")."""
    if name in METRICS:
        return name
    wanted = name.strip().lower()
    return next((m for m, info in METRICS.items() if info.label.lower() == wanted), name)


def metric_list(metrics: list[str] | tuple[str, ...]) -> str:
    """How the task names the metrics: the tool name with what people call it."""
    return ", ".join(f"{m} ({label(m)})" for m in metrics)
