"""One day's values next to the person's usual range, and a metric's recent days.

Descriptive only: the usual range is the middle half of the 28 days before, not a test, so a
value outside it is "above usual", never a change or a finding (those come from the screen).
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.analysis.evidence import Evidence, ToolError, Window
from app.analysis.screen import without_low_wear

USUAL_DAYS = 28  # the weeks before the day that make up its usual range
MIN_USUAL_DAYS = 7  # fewer days with data and no usual range is given
RECENT_DAYS = 14  # the short trend line beside each value


@dataclass(frozen=True)
class Usual:
    median: float
    low: float  # 25th percentile
    high: float  # 75th percentile
    days: int  # days with data it was computed from


@dataclass(frozen=True)
class DayMetric:
    metric: str
    value: float | None
    usual: Usual | None
    recent: list[float | None]  # the RECENT_DAYS days ending with this one, oldest first


def usual(values: pd.Series) -> Usual | None:
    values = values.dropna()
    if len(values) < MIN_USUAL_DAYS:
        return None
    return Usual(
        median=round(float(values.median()), 2),
        low=round(float(values.quantile(0.25)), 2),
        high=round(float(values.quantile(0.75)), 2),
        days=len(values),
    )


def _value(value: object) -> float | None:
    return None if pd.isna(value) else round(float(value), 2)


# Our own recovery score: where last night's HRV, resting heart rate and time asleep sit among the
# person's previous 28 days, averaged with equal weights. Higher HRV and more sleep count up, a
# higher resting heart rate counts down. An estimate to compare with the morning check-in.
RECOVERY = "recovery_score"
RECOVERY_INPUTS = {"hrv_ms": 1, "resting_hr": -1, "sleep_minutes": 1}
MIN_RECOVERY_INPUTS = 2


def _beaten(frame: pd.DataFrame, day: date, signs: dict[str, int]) -> dict[str, float]:
    """Each input's share (0 to 100) of the 28 days before that the day beat; ties count half.

    A sign of -1 counts a lower value as beating the day before."""
    stamp = pd.Timestamp(day)
    if stamp not in frame.index:
        return {}
    before = frame.loc[stamp - pd.Timedelta(days=USUAL_DAYS) : stamp - pd.Timedelta(days=1)]
    parts = {}
    for metric, sign in signs.items():
        if metric not in frame.columns:
            continue
        value, usual_days = frame.loc[stamp, metric], before[metric].dropna()
        if pd.isna(value) or len(usual_days) < MIN_USUAL_DAYS:
            continue
        beaten = ((usual_days < value).sum() + 0.5 * (usual_days == value).sum()) / len(usual_days)
        parts[metric] = round(100 * (beaten if sign > 0 else 1 - beaten), 1)
    return parts


def recovery_parts(frame: pd.DataFrame, day: date) -> dict[str, float]:
    return _beaten(frame, day, RECOVERY_INPUTS)


def recovery_score(parts: dict[str, float]) -> float | None:
    if len(parts) < MIN_RECOVERY_INPUTS:
        return None
    return float(round(sum(parts.values()) / len(parts)))


# Strain (docs/scores.md): minutes in Fitbit's heart-rate zones, weighted by zone as in Edwards'
# TRIMP, on WHOOP's bounded 0-21 scale. Fitbit sets the zones from each wearer's heart-rate
# reserve, so no maximum heart rate is needed here. The light zone holds nearly all of a day's
# zone time (99% on our own data): everyday heart rate rather than exercise, so it counts little.
STRAIN = "strain"
STRAIN_MAX = 21
ZONE_WEIGHTS = {
    "hr_zone_light_minutes": 0.04,
    "hr_zone_moderate_minutes": 2,
    "hr_zone_vigorous_minutes": 3,
    "hr_zone_peak_minutes": 4,
}
STRAIN_SCALE = 200  # load at which strain reaches 21 x (1 - 1/e), about 13.3
# Without zone minutes, load is estimated from Active Zone Minutes (counted from the same zones)
# with the ratio between the two on the person's days that have both, or this one.
DEFAULT_LOAD_PER_AZM = 2.0
STRAIN_BANDS = ((18, "all_out"), (14, "high"), (10, "moderate"), (0, "light"))


@dataclass(frozen=True)
class StrainDay:
    score: float
    band: str
    load: float
    method: str  # "zones", or "active_zone_minutes" when estimated without zone minutes


def strain_from_load(load: float) -> float:
    return round(STRAIN_MAX * (1 - math.exp(-max(load, 0.0) / STRAIN_SCALE)), 1)


def strain_band(score: float) -> str:
    return next(band for low, band in STRAIN_BANDS if score >= low)


def _zone_load(frame: pd.DataFrame) -> pd.Series:
    """Weighted zone minutes; missing on days without zone data."""
    columns = [c for c in ZONE_WEIGHTS if c in frame.columns]
    if not columns:
        return pd.Series(float("nan"), index=frame.index)
    zones = frame[columns]
    load = sum(zones[c].fillna(0) * ZONE_WEIGHTS[c] for c in columns)
    return load.where(zones.notna().any(axis=1))


def strain_days(frame: pd.DataFrame) -> dict[pd.Timestamp, StrainDay]:
    zone_load = _zone_load(frame)
    azm = frame["active_zone_minutes"] if "active_zone_minutes" in frame.columns else None
    ratio = DEFAULT_LOAD_PER_AZM
    if azm is not None:
        both = zone_load.notna() & (azm > 0)
        if both.sum() >= MIN_USUAL_DAYS:
            ratio = float((zone_load[both] / azm[both]).median())
    days = {}
    for stamp in frame.index:
        load, method = zone_load.get(stamp), "zones"
        if pd.isna(load):
            if azm is None or pd.isna(azm.get(stamp)):
                continue
            load, method = float(azm[stamp]) * ratio, "active_zone_minutes"
        score = strain_from_load(float(load))
        days[stamp] = StrainDay(score, strain_band(score), round(float(load), 1), method)
    return days


# Stress (docs/scores.md): physical signs of stress, weighted toward the daytime so it does not
# repeat recovery. Each input is ranked against the 28 days before, as for recovery, so 50 is a
# typical day for this person; higher means more signs of stress.
STRESS = "stress_score"
#
# The daytime input is the heart rate while still and awake, above resting, beyond what the day's
# exercise explains: on our own data the raw value followed strain closely (rank correlation 0.6),
# so active days read as stressful. Each day it is compared with a line fitted on the 28 days
# before (heart rate against log zone load), and the distance from that line is the input.
STILL_HR = "still_hr_above_resting"  # stored by the sync
DAYTIME = "daytime_heart_rate"  # the adjusted input
STRESS_SIGNS = {DAYTIME: 1, "hrv_ms": -1, "resting_hr": 1, "sleep_minutes": -1}
STRESS_WEIGHTS = {DAYTIME: 0.6, "hrv_ms": 0.125, "resting_hr": 0.125, "sleep_minutes": 0.15}
MIN_STILL_MINUTES = 240  # a day needs 4 hours of still, awake wear for a stress score


def _daytime(frame: pd.DataFrame) -> pd.Series:
    if not {"still_minutes", STILL_HR} <= set(frame.columns):
        return pd.Series(float("nan"), index=frame.index)
    still = frame[STILL_HR].where(frame["still_minutes"] >= MIN_STILL_MINUTES)
    load = np.log1p(_zone_load(frame))
    adjusted = pd.Series(float("nan"), index=frame.index)
    for stamp in frame.index:
        if pd.isna(still[stamp]) or pd.isna(load[stamp]):
            continue
        window = slice(stamp - pd.Timedelta(days=USUAL_DAYS), stamp - pd.Timedelta(days=1))
        x, y = load.loc[window], still.loc[window]
        known = x.notna() & y.notna()
        if known.sum() < MIN_USUAL_DAYS:
            continue
        x, y = x[known].to_numpy(), y[known].to_numpy()
        slope = 0.0 if np.ptp(x) == 0 else float(np.polyfit(x, y, 1)[0])
        adjusted[stamp] = still[stamp] - (y.mean() + slope * (load[stamp] - x.mean()))
    return adjusted


def _with_daytime(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.assign(**{DAYTIME: _daytime(frame)})


def stress_parts(frame: pd.DataFrame, day: date) -> dict[str, float]:
    """Each input's share of the 28 days before that showed fewer signs of stress."""
    return _beaten(_with_daytime(frame), day, STRESS_SIGNS)


def stress_score(parts: dict[str, float]) -> float | None:
    """The weighted mean of the parts; none without the daytime input, which carries the score."""
    if DAYTIME not in parts:
        return None
    weight = sum(STRESS_WEIGHTS[name] for name in parts)
    return float(round(sum(STRESS_WEIGHTS[name] * value for name, value in parts.items()) / weight))


SCORES = (RECOVERY, STRAIN, STRESS)


def with_scores(frame: pd.DataFrame) -> pd.DataFrame:
    """The frame with recovery, strain and stress as three more daily metrics."""
    if set(SCORES) <= set(frame.columns):
        return frame
    shared = _with_daytime(frame)
    strain = strain_days(frame)
    columns = {
        RECOVERY: [recovery_score(recovery_parts(frame, s.date())) for s in frame.index],
        STRAIN: [strain[s].score if s in strain else None for s in frame.index],
        STRESS: [stress_score(_beaten(shared, s.date(), STRESS_SIGNS)) for s in frame.index],
    }
    return frame.assign(
        **{
            name: pd.Series(values, index=frame.index, dtype=float)
            for name, values in columns.items()
        }
    )


def day_summary(frame: pd.DataFrame, day: date) -> list[DayMetric]:
    """Every metric on `day`, with its usual range from the USUAL_DAYS days before it.

    Activity totals on low-wear days are left out of the usual range and the trend line (as in
    the screen), but the day's own value is shown as it is; the caller flags a low-wear day.
    """
    frame = with_scores(frame)
    cleaned = without_low_wear(frame)
    stamp = pd.Timestamp(day)
    before = cleaned.loc[stamp - pd.Timedelta(days=USUAL_DAYS) : stamp - pd.Timedelta(days=1)]
    recent_index = pd.date_range(stamp - pd.Timedelta(days=RECENT_DAYS - 1), stamp)
    recent = cleaned.reindex(recent_index)
    row = frame.loc[stamp] if stamp in frame.index else None
    return [
        DayMetric(
            metric=metric,
            value=_value(row[metric]) if row is not None else None,
            usual=usual(before[metric]),
            recent=[_value(v) for v in recent[metric]],
        )
        for metric in frame.columns
    ]


def series(
    frame: pd.DataFrame, metric: str, end: date, days: int
) -> list[tuple[date, float | None]]:
    """The metric's daily values for the `days` days ending on `end`; gaps stay as None."""
    cleaned = without_low_wear(with_scores(frame) if metric in SCORES else frame)
    index = pd.date_range(pd.Timestamp(end) - pd.Timedelta(days=days - 1), pd.Timestamp(end))
    values = cleaned[metric].reindex(index)
    return [(stamp.date(), _value(value)) for stamp, value in values.items()]


def usual_before(frame: pd.DataFrame, metric: str, day: date) -> Usual | None:
    cleaned = without_low_wear(with_scores(frame) if metric in SCORES else frame)
    stamp = pd.Timestamp(day)
    return usual(
        cleaned[metric].loc[stamp - timedelta(days=USUAL_DAYS) : stamp - timedelta(days=1)]
    )


def compare_day(frame: pd.DataFrame, metric: str, day: date) -> Evidence:
    """One day's value against the person's usual range: the middle half of the 28 days before.

    Descriptive, like the Today screen: "above usual" says where the day sits, not that anything
    changed. Sufficient with a value that day, so the value can be stated; a position against the
    usual range needs MIN_USUAL_DAYS days before it as well, and is absent without them. With no
    value that day, `latest_day_with_value` says which earlier day has one: real data has gaps.
    """
    if metric not in frame.columns:
        raise ToolError(f"Unknown metric {metric!r}")
    stamp = pd.Timestamp(day)
    if stamp not in frame.index:
        raise ToolError(f"There is no data for {day.isoformat()}")
    value = _value(frame.loc[stamp, metric])
    window = Window(start=day - timedelta(days=USUAL_DAYS), end=day - timedelta(days=1))
    range_ = usual_before(frame, metric, day)
    stats: dict = {"value": value, "usual_days": range_.days if range_ else 0}
    if range_:
        stats |= {"usual_median": range_.median, "usual_low": range_.low, "usual_high": range_.high}
    if value is not None and range_:
        stats["position"] = (
            "above" if value > range_.high else "below" if value < range_.low else "within"
        )
    if value is None:
        earlier = frame[metric].loc[:stamp].dropna()
        if not earlier.empty:
            stats["latest_day_with_value"] = earlier.index.max().date().isoformat()
    return Evidence(
        tool="compare_day",
        metrics=(metric,),
        windows=(Window(start=day, end=day), window),
        n=stats["usual_days"],
        sufficient=value is not None,
        stats=stats,
    )
