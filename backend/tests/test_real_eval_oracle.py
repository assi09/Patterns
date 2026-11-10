"""The answer key has to be right before it grades anything: known answers, over many seeds."""

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[2] / "eval"))

import oracle  # noqa: E402


def series(seed: int, days: int = 60, shift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    values = rng.normal(420, 40, days)
    values[-14:] += shift
    index = pd.date_range("2026-01-01", periods=days, name="date")
    return pd.DataFrame({"m": values, "n": rng.normal(0, 1, days)}, index=index)


def test_no_change_is_called_a_change_about_as_often_as_it_should_be():
    verdicts = [oracle.change(series(s), "m", series(s).index.max(), 14, 28) for s in range(400)]
    assert 0.02 < sum(v != "none" for v in verdicts) / len(verdicts) < 0.09


def test_a_large_change_is_found_in_the_right_direction():
    up = [
        oracle.change(series(s, shift=80), "m", series(s).index.max(), 14, 28) for s in range(100)
    ]
    down = [
        oracle.change(series(s, shift=-80), "m", series(s).index.max(), 14, 28) for s in range(100)
    ]
    assert sum(v == "up" for v in up) >= 90 and sum(v == "down" for v in down) >= 90


def test_too_little_data_gives_no_verdict():
    frame = series(1)
    frame.loc[frame.index[-14:], "m"] = np.nan
    assert oracle.change(frame, "m", frame.index.max(), 14, 28) is None


def test_unrelated_series_are_rarely_linked():
    found = [oracle.link(series(s), "m", "n") for s in range(400)]
    assert 0.02 < sum(v != "none" for v in found) / len(found) < 0.09


def test_a_lagged_link_is_found():
    frame = series(3)
    frame["n"] = frame["m"].shift(1) + np.random.default_rng(1).normal(0, 5, len(frame))
    assert oracle.link(frame, "m", "n", 1) == "positive"


def test_values_dates_and_averages():
    index = pd.date_range("2026-01-01", periods=3, name="date")
    frame = pd.DataFrame({"m": [1.0, np.nan, 5.0]}, index=index)
    assert oracle.day_value(frame, "m", date(2026, 1, 2)) is None
    assert oracle.mean_over(frame, "m", date(2026, 1, 1), date(2026, 1, 3)) == (3.0, 2)
    assert oracle.best_day(frame, "m", date(2026, 1, 1), date(2026, 1, 3)) == (
        date(2026, 1, 3),
        5.0,
    )
