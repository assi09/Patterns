"""More deterministic tools for the agent: regularity, training load, best and worst days, the
person's usual ranges, and their morning check-ins.

Like `tools.py`, nothing here calls a model: each function validates its input, raises `ToolError`,
and returns `Evidence` whose numbers the agent may quote.
"""

from datetime import date, timedelta

import pandas as pd

from app.analysis.day import USUAL_DAYS, usual_before
from app.analysis.evidence import Evidence, ToolError, Window
from app.analysis.tools import MIN_DAYS_COMPARE, WEEKEND, _round, _two_sample, _values

MIN_NIGHTS_REGULARITY = 7
MIN_GOAL_DAYS = 3
ACUTE_DAYS = 7  # training load: the last week against
CHRONIC_DAYS = 28  # the last four weeks
LOAD_BANDS = ((0.8, "lighter than usual"), (1.3, "steady"), (float("inf"), "heavier than usual"))
HARD_QUANTILE = 0.75  # a hard day is in the top quarter of strain
MAX_RANK = 5
# Which way is better, for "best" and "worst"; others take "highest" and "lowest" only.
BETTER = {
    "sleep_minutes": "up",
    "sleep_efficiency": "up",
    "deep_sleep_minutes": "up",
    "rem_sleep_minutes": "up",
    "recovery_score": "up",
    "hrv_ms": "up",
    "resting_hr": "down",
    "stress_score": "down",
    "steps": "up",
    "active_zone_minutes": "up",
    "awake_in_bed_minutes": "down",
}
USUAL_METRICS = (
    "sleep_minutes",
    "sleep_efficiency",
    "bedtime_hour",
    "recovery_score",
    "resting_hr",
    "hrv_ms",
    "steps",
    "active_zone_minutes",
    "strain",
    "stress_score",
)
CHECKIN_RATING = "checkin_rating"
TAG_PREFIX = "tag_"


def sleep_regularity(frame: pd.DataFrame, window: Window) -> Evidence:
    """How regular bedtimes and wake times are, and how much weekends shift them."""
    bed = _values(frame, "bedtime_hour", window)
    if len(bed) < MIN_NIGHTS_REGULARITY:
        return Evidence(
            tool="sleep_regularity",
            metrics=("bedtime_hour",),
            windows=(window,),
            n=len(bed),
            sufficient=False,
            stats={},
        )
    stats: dict = {
        "median": _round(bed.median(), 3),  # the typical bedtime, as a clock time
        "bedtime_spread_minutes": _round(bed.std() * 60, 1),
    }
    if "time_in_bed" in frame.columns:
        in_bed = frame.loc[bed.index, "time_in_bed"]
        wake = (bed + in_bed / 60).dropna()
        if len(wake) >= MIN_NIGHTS_REGULARITY:
            stats["wake_spread_minutes"] = _round(wake.std() * 60, 1)
    weekend = bed[bed.index.dayofweek.isin(WEEKEND)]
    weekday = bed[~bed.index.dayofweek.isin(WEEKEND)]
    if len(weekend) >= 2 and len(weekday) >= 3:
        stats["weekend_shift_minutes"] = _round((weekend.mean() - weekday.mean()) * 60, 1)
    return Evidence(
        tool="sleep_regularity",
        metrics=("bedtime_hour",),
        windows=(window,),
        n=len(bed),
        sufficient=True,
        stats=stats,
    )


def training_load(frame: pd.DataFrame, day: date) -> Evidence:
    """The last week's strain against the last four weeks', and recovery after hard days."""
    if "strain" not in frame.columns:
        raise ToolError("There is no strain data")
    chronic_window = Window(start=day - timedelta(days=CHRONIC_DAYS - 1), end=day)
    acute = _values(frame, "strain", Window(start=day - timedelta(days=ACUTE_DAYS - 1), end=day))
    chronic = _values(frame, "strain", chronic_window)
    stats: dict = {}
    sufficient = len(acute) >= 4 and len(chronic) >= MIN_DAYS_COMPARE * 2
    if sufficient:
        ratio = acute.mean() / chronic.mean() if chronic.mean() else None
        stats |= {
            "mean_recent": _round(acute.mean(), 2),
            "mean_baseline": _round(chronic.mean(), 2),
            "load_ratio": _round(ratio, 2) if ratio is not None else None,
            "band": next(name for limit, name in LOAD_BANDS if ratio is None or ratio < limit),
        }
    metrics: tuple[str, ...] = ("strain",)
    if "recovery_score" in frame.columns and sufficient:
        # The morning after a hard day against the morning after any other day, over 8 weeks.
        span = frame.loc[pd.Timestamp(day - timedelta(days=55)) : pd.Timestamp(day)]
        strain = span["strain"]
        next_recovery = span["recovery_score"].shift(-1)
        hard = strain >= strain.quantile(HARD_QUANTILE)
        after_hard = next_recovery[hard].dropna()
        after_other = next_recovery[~hard & strain.notna()].dropna()
        if len(after_hard) >= 5 and len(after_other) >= 5:
            metrics = ("strain", "recovery_score")
            test = _two_sample(after_hard, after_other)
            stats |= {
                "recovery_after_hard": _round(after_hard.mean(), 1),
                "recovery_after_other": _round(after_other.mean(), 1),
                "hard_days": len(after_hard),
                "difference": test["difference"],
                "cliffs_delta": test["cliffs_delta"],
                "p_value": test["p_value"],
            }
    return Evidence(
        tool="training_load",
        metrics=metrics,
        windows=(chronic_window,),
        n=len(chronic),
        sufficient=sufficient,
        stats=stats,
    )


def rank_days(frame: pd.DataFrame, metric: str, window: Window, order: str, count: int = 3):
    """The best, worst, highest or lowest days of a metric in a period."""
    if order not in ("best", "worst", "highest", "lowest"):
        raise ToolError("order must be best, worst, highest or lowest")
    if order in ("best", "worst") and metric not in BETTER:
        raise ToolError(f"{metric} has no better direction; ask for highest or lowest")
    count = max(1, min(count, MAX_RANK))
    values = _values(frame, metric, window)
    if order in ("highest", "lowest"):
        high_first = order == "highest"
    else:  # best and worst follow which way is better for the metric
        high_first = (order == "best") == (BETTER[metric] == "up")
    ranked = values.sort_values(ascending=not high_first).head(count)
    return Evidence(
        tool="rank_days",
        metrics=(metric,),
        windows=(window,),
        n=len(values),
        sufficient=len(values) >= count,
        stats={
            "order": order,
            "days": [
                {"day": d.date().isoformat(), "value": _round(v, 2)} for d, v in ranked.items()
            ],
        },
    )


def usual_ranges(frame: pd.DataFrame, day: date) -> Evidence:
    """The person's usual range for each main metric: the middle half of the 28 days before."""
    ranges = {}
    for metric in USUAL_METRICS:
        if metric not in frame.columns:
            continue
        usual = usual_before(frame, metric, day)
        if usual is not None:
            ranges[metric] = {"median": usual.median, "low": usual.low, "high": usual.high}
    return Evidence(
        tool="usual_ranges",
        metrics=tuple(ranges) or USUAL_METRICS[:1],
        windows=(Window(start=day - timedelta(days=USUAL_DAYS), end=day - timedelta(days=1)),),
        n=USUAL_DAYS,
        sufficient=bool(ranges),
        stats={"ranges": ranges},
    )


def with_checkins(
    frame: pd.DataFrame, checkins: list[tuple[date, int, list[str]]], tags
) -> pd.DataFrame:
    """The daily table with the morning check-in: its rating, and 1 or 0 per tag that day."""
    out = frame.copy()
    out[CHECKIN_RATING] = float("nan")
    for tag in tags:
        out[f"{TAG_PREFIX}{tag}"] = float("nan")
    for day, rating, chosen in checkins:
        stamp = pd.Timestamp(day)
        if stamp not in out.index:
            continue
        out.loc[stamp, CHECKIN_RATING] = rating
        for tag in tags:
            out.loc[stamp, f"{TAG_PREFIX}{tag}"] = 1.0 if tag in chosen else 0.0
    return out


def checkin_summary(frame: pd.DataFrame, window: Window) -> Evidence:
    """How the person said they felt over a period, and which tags they chose how often."""
    if CHECKIN_RATING not in frame.columns:
        raise ToolError("There are no morning check-ins")
    ratings = _values(frame, CHECKIN_RATING, window)
    tags = {
        column[len(TAG_PREFIX) :]: int(frame.loc[ratings.index, column].sum())
        for column in frame.columns
        if column.startswith(TAG_PREFIX)
    }
    return Evidence(
        tool="checkins",
        metrics=(CHECKIN_RATING,),
        windows=(window,),
        n=len(ratings),
        sufficient=len(ratings) >= 3,
        stats={"mean": _round(ratings.mean(), 2) if len(ratings) else None, "tag_days": tags},
    )


def tag_effect(frame: pd.DataFrame, tag: str, metric: str, window: Window) -> Evidence:
    """A metric on check-in days with a tag against check-in days without it (Mann-Whitney)."""
    column = f"{TAG_PREFIX}{tag}"
    if column not in frame.columns:
        raise ToolError(f"Unknown check-in tag {tag!r}")
    values = _values(frame, metric, window)
    flags = frame.loc[values.index, column]
    with_tag, without = values[flags == 1], values[flags == 0]
    sufficient = len(with_tag) >= 3 and len(without) >= 3
    stats: dict = {"tag": tag, "n_with": len(with_tag), "n_without": len(without)}
    if sufficient:
        test = _two_sample(with_tag, without)
        stats |= {
            "mean_with": _round(with_tag.mean(), 2),
            "mean_without": _round(without.mean(), 2),
            "difference": test["difference"],
            "cliffs_delta": test["cliffs_delta"],
            "p_value": test["p_value"],
        }
    return Evidence(
        tool="tag_effect",
        metrics=(metric,),
        windows=(window,),
        n=len(with_tag) + len(without),
        sufficient=sufficient,
        stats=stats,
    )


def goal_progress(
    frame: pd.DataFrame, metric: str, target: float, direction: str, window: Window
) -> Evidence:
    """How often a day met a target the person set, overall and over the last week of the period."""
    if direction not in ("at_least", "at_most"):
        raise ToolError("direction must be at_least or at_most")
    values = _values(frame, metric, window)
    met = values >= target if direction == "at_least" else values <= target
    last_week = met[met.index > pd.Timestamp(window.end - timedelta(days=7))]
    return Evidence(
        tool="goal_progress",
        metrics=(metric,),
        windows=(window,),
        n=len(values),
        sufficient=len(values) >= MIN_GOAL_DAYS,
        stats={
            "target": _round(target),
            "direction": direction,
            "days_met": int(met.sum()),
            "days_counted": len(values),
            "share_met": _round(met.mean()) if len(met) else None,
            "last_week_met": int(last_week.sum()),
            "last_week_counted": len(last_week),
            "mean": _round(values.mean()) if len(values) else None,
        },
    )
