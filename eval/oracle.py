"""The answer key: deliberately plain pandas and SciPy, sharing nothing with `app/analysis`.

If the agent's tools and this disagree, one of them is wrong. The tests here use a two-sided
Mann-Whitney U and a Spearman correlation at 0.05, and report only what a person would check.
"""

import pandas as pd
from scipy import stats

ALPHA = 0.05
MIN_POINTS = 7


def day_value(frame: pd.DataFrame, metric: str, day) -> float | None:
    value = frame[metric].get(pd.Timestamp(day))
    return None if value is None or pd.isna(value) else float(value)


def mean_over(frame: pd.DataFrame, metric: str, start, end) -> tuple[float | None, int]:
    values = frame.loc[pd.Timestamp(start) : pd.Timestamp(end), metric].dropna()
    return (float(values.mean()) if len(values) else None), len(values)


def best_day(frame: pd.DataFrame, metric: str, start, end, highest: bool = True):
    values = frame.loc[pd.Timestamp(start) : pd.Timestamp(end), metric].dropna()
    if values.empty:
        return None, None
    at = values.idxmax() if highest else values.idxmin()
    return at.date(), float(values[at])


def _verdict(first: pd.Series, second: pd.Series) -> str | None:
    """ "up" if `first` is significantly above `second`, "down" below, "none" neither."""
    if len(first) < MIN_POINTS or len(second) < MIN_POINTS:
        return None
    if stats.mannwhitneyu(first, second, alternative="two-sided").pvalue >= ALPHA:
        return "none"
    return "up" if first.median() > second.median() else "down"


def change(frame: pd.DataFrame, metric: str, end, days: int, baseline: int) -> str | None:
    end = pd.Timestamp(end)
    recent_start = end - pd.Timedelta(days=days - 1)
    recent = frame.loc[recent_start:end, metric].dropna()
    before = frame.loc[
        recent_start - pd.Timedelta(days=baseline) : recent_start - pd.Timedelta(days=1), metric
    ].dropna()
    return _verdict(recent, before)


def weekend_gap(frame: pd.DataFrame, metric: str) -> str | None:
    values = frame[metric].dropna()
    weekend = values.index.dayofweek >= 5
    return _verdict(values[weekend], values[~weekend])


def link(frame: pd.DataFrame, driver: str, target: str, lag: int = 0) -> str | None:
    pairs = pd.DataFrame({"x": frame[driver].shift(lag), "y": frame[target]}).dropna()
    if len(pairs) < 14 or pairs["x"].nunique() < 3 or pairs["y"].nunique() < 3:
        return None
    rho, p = stats.spearmanr(pairs["x"], pairs["y"])
    if pd.isna(p) or p >= ALPHA:
        return "none"
    return "positive" if rho > 0 else "negative"
