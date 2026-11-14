"""Deterministic analysis tools over a daily metrics table.

Tools never call a model. Each one validates its arguments, computes its statistics on the
non-missing days in the requested windows, and returns an `Evidence` record.
"""

import math

import numpy as np
import pandas as pd
from scipy import stats

from app.analysis.evidence import Evidence, ToolError, Window

MIN_DAYS_DESCRIBE = 3
MIN_DAYS_COMPARE = 7  # per window
MIN_DAYS_TREND = 14
MIN_DAYS_CORRELATE = 14
MIN_DAYS_SEGMENT = 7  # each side of a change point
MIN_DAYS_PER_GROUP = 6  # weekdays and weekend days each
MAX_LAG_DAYS = 14
PERMUTATIONS = 999  # for the change-point p-value; fixed seed so results are reproducible
WEEKEND = (5, 6)  # Saturday and Sunday (Monday is 0)
LOW_WEAR_MINUTES = 600  # under 10 hours of wear, activity totals are not representative


def _round(value: float, digits: int = 4) -> float | None:
    value = float(value)
    return None if math.isnan(value) else round(value, digits)


def _values(frame: pd.DataFrame, metric: str, window: Window) -> pd.Series:
    if metric not in frame.columns:
        raise ToolError(f"Unknown metric {metric!r}")
    rows = frame.loc[pd.Timestamp(window.start) : pd.Timestamp(window.end), metric]
    return rows.dropna()


# Metrics whose days add up to something a person would ask for: steps, minutes, calories.
ADDITIVE = frozenset(
    {
        "steps",
        "calories",
        "distance_km",
        "active_zone_minutes",
        "sedentary_minutes",
        "lightly_active_minutes",
        "moderately_active_minutes",
        "very_active_minutes",
    }
)


def describe(frame: pd.DataFrame, metric: str, window: Window) -> Evidence:
    """Summary statistics of one metric over one window."""
    values = _values(frame, metric, window)
    summary = {
        "mean": _round(values.mean()),
        "median": _round(values.median()),
        "sd": _round(values.std()),
        "min": _round(values.min()),
        "max": _round(values.max()),
        "missing_days": window.days - len(values),
    }
    if metric in ADDITIVE:  # "how many steps this week?" asks for the total, not the average
        summary["total"] = _round(values.sum())
    return Evidence(
        tool="describe",
        metrics=(metric,),
        windows=(window,),
        n=len(values),
        sufficient=len(values) >= MIN_DAYS_DESCRIBE,
        stats=summary,
    )


def coverage(frame: pd.DataFrame, window: Window) -> Evidence:
    """How complete each metric is over a window, and how many days had low wear time."""
    rows = frame.loc[pd.Timestamp(window.start) : pd.Timestamp(window.end)]
    present = {metric: int(rows[metric].notna().sum()) for metric in frame.columns}
    summary: dict = {
        "days": window.days,
        "fraction_present": {m: _round(count / window.days, 3) for m, count in present.items()},
    }
    if "wear_minutes" in frame.columns:
        low = rows.index[rows["wear_minutes"] < LOW_WEAR_MINUTES]
        summary["low_wear_days"] = [day.date().isoformat() for day in low]
    return Evidence(
        tool="coverage",
        metrics=tuple(frame.columns),
        windows=(window,),
        n=len(rows),
        sufficient=True,
        stats=summary,
    )


def _two_sample(a: pd.Series, b: pd.Series) -> dict:
    """Difference between two groups of days: means, Mann-Whitney U p-value and Cliff's delta."""
    summary = {
        "difference": _round(a.mean() - b.mean()),
        "pct_change": _round(100 * (a.mean() - b.mean()) / abs(b.mean()), 2)
        if len(b) and b.mean() != 0
        else None,
        "cliffs_delta": None,
        "p_value": None,
    }
    if len(a) and len(b):
        if np.ptp(np.concatenate([a, b])) == 0:
            summary["cliffs_delta"], summary["p_value"] = 0.0, 1.0
        else:
            u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
            summary["cliffs_delta"] = _round(2 * u / (len(a) * len(b)) - 1)
            summary["p_value"] = _round(p, 6)
    return summary


def compare_windows(frame: pd.DataFrame, metric: str, recent: Window, baseline: Window) -> Evidence:
    """Whether a metric differs between two non-overlapping windows.

    Uses a two-sided Mann-Whitney U test, which assumes no particular distribution, and reports
    Cliff's delta as the effect size (-1..1, share of pairs where recent > baseline minus the
    reverse).
    """
    if recent.start <= baseline.end and baseline.start <= recent.end:
        raise ToolError("recent and baseline windows overlap")
    a, b = _values(frame, metric, recent), _values(frame, metric, baseline)
    sufficient = min(len(a), len(b)) >= MIN_DAYS_COMPARE
    summary = {
        "mean_recent": _round(a.mean()),
        "mean_baseline": _round(b.mean()),
        "n_recent": len(a),
        "n_baseline": len(b),
        **_two_sample(a, b),
    }
    return Evidence(
        tool="compare_windows",
        metrics=(metric,),
        windows=(recent, baseline),
        n=len(a) + len(b),
        sufficient=sufficient,
        stats=summary,
    )


def trend(frame: pd.DataFrame, metric: str, window: Window) -> Evidence:
    """Whether a metric drifts steadily over a window.

    The slope is the Theil-Sen estimate (median of pairwise slopes, robust to outliers) in units
    per day, with its 95% interval; the p-value is from Kendall's tau against time.
    """
    values = _values(frame, metric, window)
    summary = {
        "slope_per_day": None,
        "slope_low": None,
        "slope_high": None,
        "change_over_window": None,
        "kendall_tau": None,
        "p_value": None,
    }
    if len(values) >= 2:
        days = ((values.index - pd.Timestamp(window.start)).days).to_numpy(dtype=float)
        if np.ptp(values) == 0:
            slope, low, high, tau, p = 0.0, 0.0, 0.0, 0.0, 1.0
        else:
            slope, _, low, high = stats.theilslopes(values, days)
            tau, p = stats.kendalltau(days, values)
        summary.update(
            slope_per_day=_round(slope),
            slope_low=_round(low),
            slope_high=_round(high),
            change_over_window=_round(slope * (window.days - 1)),
            kendall_tau=_round(tau),
            p_value=_round(p, 6),
        )
    return Evidence(
        tool="trend",
        metrics=(metric,),
        windows=(window,),
        n=len(values),
        sufficient=len(values) >= MIN_DAYS_TREND,
        stats=summary,
    )


def correlate(
    frame: pd.DataFrame, driver: str, target: str, window: Window, max_lag: int = 0
) -> Evidence:
    """Whether `target` moves with `driver` on the same day or up to `max_lag` days later.

    Spearman correlation is computed at every lag from 0 to `max_lag` and the strongest is
    reported. Because several lags are tried, its p-value is Bonferroni-adjusted for the number of
    lags tested. Correlation alone does not show that the driver causes the change.
    """
    if driver == target:
        raise ToolError("driver and target must be different metrics")
    if not 0 <= max_lag <= MAX_LAG_DAYS:
        raise ToolError(f"max_lag must be between 0 and {MAX_LAG_DAYS}")
    for metric in (driver, target):
        if metric not in frame.columns:
            raise ToolError(f"Unknown metric {metric!r}")

    rows = slice(pd.Timestamp(window.start), pd.Timestamp(window.end))
    by_lag = {}
    for lag in range(max_lag + 1):
        # Shift on the full table so a lagged driver can come from just before the window.
        pairs = pd.concat([frame[driver].shift(lag), frame[target]], axis=1).loc[rows].dropna()
        if len(pairs) < 3 or pairs.nunique().min() < 2:
            continue
        rho, p = stats.spearmanr(pairs.iloc[:, 0], pairs.iloc[:, 1])
        by_lag[lag] = (float(rho), float(p), len(pairs))

    summary: dict = {
        "lags_tested": max_lag + 1,
        # String keys, as JSON has them, so stored evidence equals what the tool returned.
        "rho_by_lag": {str(lag): _round(rho) for lag, (rho, _, _) in by_lag.items()},
        "best_lag": None,
        "rho": None,
        "p_value": None,
        "p_value_adjusted": None,
    }
    n = 0
    if by_lag:
        best = max(by_lag, key=lambda lag: abs(by_lag[lag][0]))
        rho, p, n = by_lag[best]
        summary.update(
            best_lag=best,
            rho=_round(rho),
            p_value=_round(p, 6),
            p_value_adjusted=_round(min(1.0, p * (max_lag + 1)), 6),
        )
    return Evidence(
        tool="correlate",
        metrics=(driver, target),
        windows=(window,),
        n=n,
        sufficient=n >= MIN_DAYS_CORRELATE,
        stats=summary,
    )


def _split_statistics(values: np.ndarray, min_segment: int) -> np.ndarray:
    """For each series (row), the largest standardized mean shift over all allowed split points."""
    n = values.shape[-1]
    sums = np.cumsum(values, axis=-1)
    k = np.arange(min_segment, n - min_segment + 1)  # size of the first segment
    before = sums[..., k - 1] / k
    after = (sums[..., -1:] - sums[..., k - 1]) / (n - k)
    scale = np.sqrt(1 / k + 1 / (n - k))
    return np.abs(after - before) / scale


def change_point(frame: pd.DataFrame, metric: str, window: Window) -> Evidence:
    """The day a metric most likely shifted to a new level within a window, if it did.

    Every split leaving at least a week on each side is tried, and the one with the largest
    standardized difference in means is reported. Trying many splits makes an ordinary test far
    too optimistic, so the p-value comes from a permutation test of the whole search: the same
    search on shuffled data, which keeps the false-positive rate at the stated level.
    """
    values = _values(frame, metric, window)
    n = len(values)
    summary: dict = {
        "change_date": None,
        "mean_before": None,
        "mean_after": None,
        "n_before": None,
        "n_after": None,
        "difference": None,
        "pct_change": None,
        "p_value": None,
    }
    if n >= 2 * MIN_DAYS_SEGMENT:
        data = values.to_numpy(dtype=float)
        observed = _split_statistics(data, MIN_DAYS_SEGMENT)
        best = int(np.argmax(observed))
        split = MIN_DAYS_SEGMENT + best
        before, after = values.iloc[:split], values.iloc[split:]
        if np.ptp(data) == 0:
            p_value = 1.0
        else:
            rng = np.random.default_rng(0)
            shuffled = rng.permuted(np.tile(data, (PERMUTATIONS, 1)), axis=1)
            null = _split_statistics(shuffled, MIN_DAYS_SEGMENT).max(axis=1)
            p_value = (1 + int((null >= observed[best] - 1e-12).sum())) / (PERMUTATIONS + 1)
        summary.update(
            change_date=values.index[split].date().isoformat(),
            mean_before=_round(before.mean()),
            mean_after=_round(after.mean()),
            n_before=len(before),
            n_after=len(after),
            difference=_round(after.mean() - before.mean()),
            pct_change=_round(100 * (after.mean() - before.mean()) / abs(before.mean()), 2)
            if before.mean() != 0
            else None,
            p_value=_round(p_value, 6),
        )
    return Evidence(
        tool="change_point",
        metrics=(metric,),
        windows=(window,),
        n=n,
        sufficient=n >= 2 * MIN_DAYS_SEGMENT,
        stats=summary,
    )


def weekday_split(frame: pd.DataFrame, metric: str, window: Window) -> Evidence:
    """Whether a metric differs on weekend days from weekdays (Mann-Whitney U, Cliff's delta)."""
    values = _values(frame, metric, window)
    weekend = values.index.dayofweek.isin(WEEKEND)
    a, b = values[weekend], values[~weekend]
    return Evidence(
        tool="weekday_split",
        metrics=(metric,),
        windows=(window,),
        n=len(values),
        sufficient=min(len(a), len(b)) >= MIN_DAYS_PER_GROUP,
        stats={
            "mean_weekend": _round(a.mean()),
            "mean_weekday": _round(b.mean()),
            "n_weekend": len(a),
            "n_weekday": len(b),
            **_two_sample(a, b),
        },
    )
