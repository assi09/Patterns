"""Which everyday habits this person's own data supports, for coaching (`habit_options`).

The agent may suggest only levers from this fixed, non-medical list, and only when the person's
own data supports them: the model words a suggestion but never invents one. Each lever is a
comparison of the target metric between two groups of the person's own days (earlier against later
bedtimes, regular against irregular ones, the morning after a hard day against other mornings,
more against less active days, days without a late meal or a stressful day against days with
one). The tests are corrected together for their number (Benjamini-Hochberg), so a lever is
"supported" only when the difference holds up after asking several questions at once, and goes the
helpful way.
"""

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from app.analysis.evidence import Evidence, ToolError, Window
from app.analysis.habits import (
    BETTER,
    HARD_QUANTILE,
    TAG_PREFIX,
    sleep_regularity,
    training_load,
)
from app.analysis.report import clock, format_value, info
from app.analysis.screen import benjamini_hochberg
from app.analysis.tools import _round, _two_sample, _values

ALPHA = 0.05
MIN_GROUP = 5
# What stands out in a routine: gaps below these are ordinary, so nothing is said about them.
MIN_DAYS_OPTIONS = 20
BEST_WORST_MINUTES = 30
WEEKEND_MINUTES = 45
SPREAD_MINUTES = 60
HIGH_EFFICIENCY = 88
QUIET_DAY_RATIO = 1.4
RECENT_DAYS = 7
RECENT_SPREADS = 0.5
MAX_OPTIONS = 4
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
REGULAR_MINUTES = 30
SLEEP = ("sleep_minutes", "sleep_efficiency", "deep_sleep_minutes", "awake_in_bed_minutes")
MORNING = ("recovery_score", "hrv_ms", "resting_hr", "stress_score")


@dataclass(frozen=True)
class _Test:
    lever: str
    label: str  # the habit, in plain words
    better_group: str  # the days the habit describes
    other_group: str
    better: pd.Series
    other: pd.Series


def _split(values: pd.Series, mask: pd.Series) -> tuple[pd.Series, pd.Series]:
    mask = mask.reindex(values.index).fillna(False).astype(bool)
    return values[mask], values[~mask]


def _tests(frame: pd.DataFrame, metric: str, values: pd.Series) -> tuple[list[_Test], float | None]:
    tests: list[_Test] = []
    split_at = None
    if "bedtime_hour" in frame.columns and metric != "bedtime_hour" and metric in SLEEP + MORNING:
        bed = frame["bedtime_hour"].reindex(values.index)
        if bed.notna().sum() >= 2 * MIN_GROUP:
            split_at = float(bed.median())
            early, late = _split(values, bed <= split_at)
            tests.append(
                _Test(
                    "earlier_bedtime",
                    f"being in bed by {clock(split_at)}",
                    f"nights in bed by {clock(split_at)}",
                    "later nights",
                    early,
                    late,
                )
            )
            regular, irregular = _split(values, (bed - split_at).abs() * 60 <= REGULAR_MINUTES)
            tests.append(
                _Test(
                    "regular_bedtime",
                    "a regular bedtime, within half an hour of your usual",
                    "nights near your usual bedtime",
                    "less regular nights",
                    regular,
                    irregular,
                )
            )
    if "strain" in frame.columns and metric in MORNING:
        strain = frame["strain"]
        hard_day = strain >= strain.quantile(HARD_QUANTILE)
        # The morning after: the target on day d against strain on day d - 1.
        after_hard = hard_day.shift(1).reindex(values.index)
        rest, hard = _split(values, after_hard == False)  # noqa: E712 (NaN is neither)
        hard = values[after_hard == True]  # noqa: E712
        tests.append(
            _Test(
                "rest_after_hard_day",
                "an easier day after your hardest training days",
                "mornings after an ordinary day",
                "mornings after a hard day",
                rest,
                hard,
            )
        )
    if "active_zone_minutes" in frame.columns and metric in SLEEP:
        azm = frame["active_zone_minutes"].reindex(values.index)
        if azm.notna().sum() >= 2 * MIN_GROUP:
            active, quiet = _split(values, azm >= azm.median())
            tests.append(
                _Test(
                    "active_days",
                    "more active days",
                    "your more active days",
                    "less active days",
                    active,
                    quiet,
                )
            )
    for tag, lever, label in (
        ("late_meal", "earlier_dinner", "an earlier dinner"),
        ("stress", "wind_down", "a wind-down routine on stressful days"),
    ):
        column = f"{TAG_PREFIX}{tag}"
        if column in frame.columns and metric in SLEEP + MORNING:
            flags = frame[column].reindex(values.index)
            without, with_tag = values[flags == 0], values[flags == 1]
            tests.append(
                _Test(
                    lever,
                    label,
                    f"days without {tag.replace('_', ' ')}",
                    "days with it",
                    without,
                    with_tag,
                )
            )
    return tests, split_at


def habit_options(frame: pd.DataFrame, metric: str, window: Window) -> Evidence:
    """The levers from the list that this person's data supports for improving `metric`."""
    if metric not in BETTER:
        raise ToolError(f"{metric} has no better direction to coach towards")
    values = _values(frame, metric, window)
    tests, split_at = _tests(frame, metric, values)
    usable = [t for t in tests if len(t.better) >= MIN_GROUP and len(t.other) >= MIN_GROUP]
    results = [(t, _two_sample(t.better, t.other)) for t in usable]
    q_values = benjamini_hochberg([r["p_value"] for _, r in results]) if results else []
    up = BETTER[metric] == "up"
    levers = []
    for (test, result), q in zip(results, q_values, strict=True):
        helpful = (result["difference"] > 0) == up and result["difference"] != 0
        levers.append(
            {
                "lever": test.lever,
                "habit": test.label,
                "supported": bool(q < ALPHA and helpful),
                "q_value": _round(q, 4),
                "group": test.better_group,
                "other_group": test.other_group,
                "mean_with": _round(test.better.mean(), 2),
                "mean_without": _round(test.other.mean(), 2),
                "difference": result["difference"],
                "n_with": len(test.better),
                "n_without": len(test.other),
            }
        )
    levers.sort(key=lambda lever: (not lever["supported"], lever["q_value"]))
    uses_bedtime = split_at is not None and any(
        lever["lever"] in ("earlier_bedtime", "regular_bedtime") for lever in levers
    )
    stats: dict = {"supported": any(lever["supported"] for lever in levers), "levers": levers}
    if uses_bedtime:
        stats["split_at"] = _round(split_at, 3)  # a clock time, so answers may quote it
    return Evidence(
        tool="habit_options",
        metrics=(metric, "bedtime_hour") if uses_bedtime else (metric,),
        windows=(window,),
        n=len(values),
        sufficient=bool(levers),
        stats=stats,
    )


def _hours(minutes: float) -> str:
    whole = round(abs(minutes))
    return f"{whole // 60} h {whole % 60} min" if whole >= 60 else f"{whole} min"


def personal_options(frame: pd.DataFrame, metric: str, window: Window) -> Evidence:
    """What stands out in this person's own routine for improving `metric`, for when no habit
    tests as supported. These are descriptions, not tested effects, so a suggestion built on one
    is something worth trying, never something that works. Nothing ordinary is reported, so an
    empty result means there is nothing specific to say, not that a generic tip should fill in."""
    if metric not in BETTER:
        raise ToolError(f"{metric} has no better direction to coach towards")
    values = _values(frame, metric, window)
    options: list[dict] = []
    stats: dict = {}
    metrics = [metric]
    name = info(metric).label.lower()
    enough = len(values) >= MIN_DAYS_OPTIONS
    about_nights = metric in SLEEP + MORNING

    if about_nights and enough and "bedtime_hour" in frame.columns:
        ranked = values.sort_values(ascending=BETTER[metric] != "up")
        quarter = len(ranked) // 4
        bed = frame["bedtime_hour"]
        best = bed.reindex(ranked.index[:quarter]).mean()
        worst = bed.reindex(ranked.index[-quarter:]).mean()
        if pd.notna(best) and pd.notna(worst) and abs(best - worst) * 60 >= BEST_WORST_MINUTES:
            stats |= {"best_bedtime": _round(best, 3), "worst_bedtime": _round(worst, 3)}
            stats["days_compared"] = quarter
            metrics.append("bedtime_hour")
            options.append(
                {
                    "key": "best_nights",
                    "note": f"on your best {quarter} days for {name} your bedtime averaged "
                    f"{clock(best)}, and on your worst {quarter} it averaged {clock(worst)}",
                    "try": f"going to bed nearer {clock(best)}",
                }
            )
    if about_nights and enough and "bedtime_hour" in frame.columns:
        routine = sleep_regularity(frame, window).stats
        shift = routine.get("weekend_shift_minutes")
        spread = routine.get("bedtime_spread_minutes")
        if shift is not None and abs(shift) >= WEEKEND_MINUTES:
            way = "later" if shift > 0 else "earlier"
            stats["weekend_shift_minutes"] = shift
            metrics.append("bedtime_hour")
            options.append(
                {
                    "key": "weekend_shift",
                    "note": f"your weekend bedtimes run {_hours(shift)} {way} than weekdays",
                    "try": "pulling the weekend bedtime part of the way back",
                }
            )
        elif spread is not None and spread >= SPREAD_MINUTES:
            stats["bedtime_spread_minutes"] = spread
            metrics.append("bedtime_hour")
            options.append(
                {
                    "key": "bedtime_spread",
                    "note": f"your bedtime moves by about {_hours(spread)} from night to night",
                    "try": "picking one bedtime for the nights you control",
                }
            )
    if metric == "sleep_minutes" and enough and {"time_in_bed", "sleep_efficiency"} <= set(frame):
        in_bed = frame["time_in_bed"].reindex(values.index).mean()
        efficiency = frame["sleep_efficiency"].reindex(values.index).mean()
        if pd.notna(in_bed) and pd.notna(efficiency) and efficiency >= HIGH_EFFICIENCY:
            stats |= {"time_in_bed_minutes": _round(in_bed, 0), "efficiency": _round(efficiency, 1)}
            metrics += ["sleep_efficiency", "time_in_bed"]
            options.append(
                {
                    "key": "time_in_bed",
                    "note": f"you are asleep for {_round(efficiency, 1)}% of your time in bed, "
                    f"so the limit is the {_hours(in_bed)} you spend there",
                    "try": "giving yourself more time in bed rather than sleeping better in it",
                }
            )
    if "strain" in frame.columns and (metric in MORNING or metric == "strain"):
        load = training_load(frame, window.end).stats
        if load.get("band") == "heavier than usual":
            stats |= {"mean_recent": load["mean_recent"], "mean_baseline": load["mean_baseline"]}
            metrics.append("strain")
            options.append(
                {
                    "key": "heavy_week",
                    "note": f"your strain this week averaged {load['mean_recent']}, against "
                    f"{load['mean_baseline']} over the last four weeks",
                    "try": "keeping the next day or two easier",
                }
            )
    if metric in ("steps", "active_zone_minutes") and enough:
        by_day = values.groupby(values.index.dayofweek).mean()
        low, high = by_day.idxmin(), by_day.idxmax()
        if by_day[low] > 0 and by_day[high] / by_day[low] >= QUIET_DAY_RATIO:
            stats |= {
                "quiet_day_mean": _round(by_day[low], 0),
                "busy_day_mean": _round(by_day[high], 0),
            }
            options.append(
                {
                    "key": "quiet_day",
                    "note": f"{WEEKDAYS[low]} is your quietest day at "
                    f"{format_value(metric, by_day[low])}, and {WEEKDAYS[high]} your busiest at "
                    f"{format_value(metric, by_day[high])}",
                    "try": f"adding a little to {WEEKDAYS[low]}",
                }
            )
    recent = values[values.index > pd.Timestamp(window.end - timedelta(days=RECENT_DAYS))]
    before = values[values.index <= pd.Timestamp(window.end - timedelta(days=RECENT_DAYS))]
    if len(recent) >= 4 and len(before) >= MIN_GROUP and before.std() > 0:
        gap = recent.mean() - before.mean()
        worse = gap < 0 if BETTER[metric] == "up" else gap > 0
        if worse and abs(gap) >= RECENT_SPREADS * before.std():
            stats |= {
                "last_week_mean": _round(recent.mean(), 2),
                "before_mean": _round(before.mean(), 2),
            }
            options.append(
                {
                    "key": "recent_dip",
                    "note": f"your {name} averaged {format_value(metric, recent.mean())} over the "
                    f"last week, against {format_value(metric, before.mean())} before",
                    "try": "",
                }
            )
    stats["options"] = options[:MAX_OPTIONS]
    return Evidence(
        tool="personal_options",
        metrics=tuple(dict.fromkeys(metrics)),
        windows=(window,),
        n=len(values),
        sufficient=bool(options),
        stats=stats,
    )
