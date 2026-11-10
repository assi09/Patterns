"""Team statistics for a supervisor's weekly report (docs/teams.md): aggregates only.

Each member is compared with themselves: the week's mean against their own 28 days before, in
units of their own spread. Only those changes are pooled, never raw values from different people,
whose devices, baselines and habits differ. Nothing is reported from fewer than MIN_MEMBERS
people, and no member id or per-person value leaves this module except in `member_levels`, which
serves the named levels a member chose to share.

Deterministic: no language model is involved, and every number in a report comes from here.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy import stats

from app.analysis.day import with_scores
from app.analysis.evidence import Evidence, Window
from app.analysis.screen import FDR, benjamini_hochberg, without_low_wear

MIN_MEMBERS = 5  # no team figure is built from fewer people
WEEK_DAYS = 7
BASELINE_DAYS = 28
MIN_WEEK_DAYS = 4  # a member counts for a metric with at least this many days of the week
MIN_BASELINE_DAYS = 14  # and this many of the 28 days before

# What a team report covers: sleep, activity and the app's scores.
TEAM_METRICS = (
    "sleep_minutes",
    "bedtime_hour",
    "steps",
    "active_zone_minutes",
    "resting_hr",
    "hrv_ms",
    "recovery_score",
    "strain",
    "stress_score",
)
WEEKDAY_METRICS = ("sleep_minutes", "steps", "stress_score")
AREAS = {
    "sleep": ("sleep_minutes", "bedtime_hour"),
    "activity": ("steps", "active_zone_minutes"),
    "recovery": ("resting_hr", "hrv_ms", "recovery_score"),
    "load": ("strain",),
    "stress": ("stress_score",),
}
AREA_OF = {metric: area for area, metrics in AREAS.items() for metric in metrics}
SCAN_WEEKS = 4
SUSTAINED_WEEKS = 2  # changed this many weeks in a row before it counts as lasting
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

# The four weekly levels a member may share with their supervisor, by name.
LEVEL_METRICS = ("recovery_score", "sleep_minutes", "strain", "stress_score")
LEVEL_WEEKS = 4  # the usual range is the middle half of the person's previous weekly means


def week_of(day: date) -> Window:
    """The Monday-to-Sunday week that contains `day`."""
    start = day - timedelta(days=day.weekday())
    return Window(start=start, end=start + timedelta(days=WEEK_DAYS - 1))


def baseline_of(week: Window) -> Window:
    return Window(start=week.start - timedelta(days=BASELINE_DAYS), end=week.start - timedelta(1))


def prepare(frame: pd.DataFrame) -> pd.DataFrame:
    """A member's days with the app's scores, and activity left out on barely worn days."""
    return without_low_wear(with_scores(frame))


def _values(frame: pd.DataFrame, metric: str, window: Window) -> pd.Series:
    if metric not in frame.columns:
        return pd.Series(dtype=float)
    return frame[metric].loc[pd.Timestamp(window.start) : pd.Timestamp(window.end)].dropna()


@dataclass(frozen=True)
class MemberChange:
    change: float  # the week's mean minus the 28 days before, in the metric's units
    standardized: float  # the same, in units of the person's own spread over the 28 days


def member_change(
    frame: pd.DataFrame, metric: str, week: Window, baseline: Window | None = None
) -> MemberChange | None:
    """One member's change on one metric, or None with too little data either side."""
    recent, before = (
        _values(frame, metric, week),
        _values(frame, metric, baseline or baseline_of(week)),
    )
    if len(recent) < MIN_WEEK_DAYS or len(before) < MIN_BASELINE_DAYS:
        return None
    change = float(recent.mean() - before.mean())
    spread = float(before.std(ddof=1))
    if not np.isfinite(spread) or spread == 0:
        return None
    return MemberChange(change, change / spread)


def team_change(changes: list[MemberChange], metric: str, week: Window) -> Evidence:
    """Whether the team's changes are centred away from zero.

    A one-sample t-test on the standardized changes, so no one person's scale dominates; with 5
    people a rank test could never reach p < 0.05. The median change and the counts up and down
    are what the report shows. Not sufficient with fewer than MIN_MEMBERS people, and then the
    statistics are left out entirely, not just flagged.
    """
    n = len(changes)
    windows = (week, baseline_of(week))
    if n < MIN_MEMBERS:
        stats_ = {"members": n, "minimum_members": MIN_MEMBERS}
        return Evidence(
            tool="team_change",
            metrics=(metric,),
            windows=windows,
            n=n,
            sufficient=False,
            stats=stats_,
        )
    raw = np.array([c.change for c in changes])
    standardized = np.array([c.standardized for c in changes])
    result = stats.ttest_1samp(standardized, 0.0)
    p_value = float(result.pvalue) if np.isfinite(result.pvalue) else 1.0
    return Evidence(
        tool="team_change",
        metrics=(metric,),
        windows=windows,
        n=n,
        sufficient=True,
        stats={
            "members": n,
            "median_change": round(float(np.median(raw)), 2),
            "change_q1": round(float(np.quantile(raw, 0.25)), 2),
            "change_q3": round(float(np.quantile(raw, 0.75)), 2),
            "mean_standardized_change": round(float(standardized.mean()), 3),
            "members_up": int((raw > 0).sum()),
            "members_down": int((raw < 0).sum()),
            "p_value": round(p_value, 6),
        },
    )


def team_weekdays(frames: list[pd.DataFrame], metric: str, week: Window) -> Evidence:
    """Descriptive: how each weekday sits against each member's own mean over five weeks.

    The median across members of each weekday's deviation, for weekdays with at least
    MIN_MEMBERS members contributing. Not a test, so it describes and never claims a change.
    """
    span = Window(start=baseline_of(week).start, end=week.end)
    deviations: dict[str, list[float]] = {day: [] for day in WEEKDAYS}
    for frame in frames:
        values = _values(frame, metric, span)
        if len(values) < MIN_BASELINE_DAYS:
            continue
        by_day = (values - values.mean()).groupby(values.index.dayofweek).mean()
        for index, deviation in by_day.items():
            deviations[WEEKDAYS[index]].append(float(deviation))
    medians = {
        day: round(float(np.median(values)), 2)
        for day, values in deviations.items()
        if len(values) >= MIN_MEMBERS
    }
    members = min((len(v) for v in deviations.values()), default=0)
    return Evidence(
        tool="team_weekday",
        metrics=(metric,),
        windows=(span,),
        n=members,
        sufficient=len(medians) == len(WEEKDAYS),
        stats={"median_deviation_by_weekday": medians, "members": members, "descriptive": True},
    )


@dataclass(frozen=True)
class TeamStatistics:
    week: Window
    members: int  # active members asked for
    changes: list[Evidence]  # one per metric, adjusted for testing many metrics
    weekdays: list[Evidence]

    @property
    def changed(self) -> list[Evidence]:
        return [e for e in self.changes if e.sufficient and e.stats["p_value_adjusted"] < FDR]


def team_statistics(frames: list[pd.DataFrame], week: Window) -> TeamStatistics:
    """Every team figure for one week, from each active member's own days (in any order).

    Fewer than MIN_MEMBERS frames give no figures at all."""
    prepared = [prepare(frame) for frame in frames]
    if len(prepared) < MIN_MEMBERS:
        return TeamStatistics(week, len(prepared), [], [])
    changes = []
    for metric in TEAM_METRICS:
        found = [member_change(frame, metric, week) for frame in prepared]
        changes.append(team_change([c for c in found if c is not None], metric, week))
    tested = [e for e in changes if e.sufficient]
    adjusted = dict(
        zip(
            (e.id for e in tested),
            benjamini_hochberg([e.stats["p_value"] for e in tested]),
            strict=True,
        )
    )
    changes = [
        e.model_copy(
            update={
                "stats": {
                    **e.stats,
                    "p_value_adjusted": round(adjusted[e.id], 6),
                    "metrics_tested": len(tested),
                }
            }
        )
        if e.id in adjusted
        else e
        for e in changes
    ]
    weekdays = [team_weekdays(prepared, metric, week) for metric in WEEKDAY_METRICS]
    return TeamStatistics(week, len(prepared), changes, weekdays)


# Several weeks across every area, for the agent's Monday check


@dataclass(frozen=True)
class TeamScan:
    weeks: tuple[Window, ...]  # oldest first
    baseline: Window
    members: int
    metrics: list[Evidence]  # one per metric, "team_scan"; no figures below MIN_MEMBERS

    @property
    def lasting(self) -> list[Evidence]:
        return [e for e in self.metrics if e.stats.get("status") == "lasting"]

    @property
    def areas(self) -> dict[str, list[str]]:
        """The areas where something changed in the latest week, and which metrics."""
        moving: dict[str, list[str]] = {}
        for evidence in self.metrics:
            if evidence.stats.get("status") in ("lasting", "new"):
                moving.setdefault(evidence.stats["area"], []).append(evidence.metrics[0])
        return moving


def _week_ending(last: Window, back: int) -> Window:
    return _shift(last, -back)


def team_scan(frames: list[pd.DataFrame], last: Window, weeks: int = SCAN_WEEKS) -> TeamScan:
    """Each metric, week by week, against one fixed baseline: the 28 days before the first week.

    A rolling baseline would absorb a lasting change and hide it after a few weeks. The groups are
    fixed (everyone with data), never chosen, so nobody can be isolated by comparing two of them.
    One correction covers every metric and week tested. "Lasting" means changed, the same way, in
    at least SUSTAINED_WEEKS weeks in a row up to the latest; one bad week is "new", not lasting.
    """
    span = tuple(_week_ending(last, back) for back in reversed(range(weeks)))
    baseline = baseline_of(span[0])
    prepared = [prepare(frame) for frame in frames]
    if len(prepared) < MIN_MEMBERS:
        return TeamScan(span, baseline, len(prepared), [])
    tested: list[tuple[str, int, Evidence]] = []
    for metric in TEAM_METRICS:
        for at, week in enumerate(span):
            found = [member_change(frame, metric, week, baseline) for frame in prepared]
            evidence = team_change([c for c in found if c is not None], metric, week)
            tested.append((metric, at, evidence))
    usable = [t for t in tested if t[2].sufficient]
    adjusted = dict(
        zip(
            ((m, at) for m, at, _ in usable),
            benjamini_hochberg([e.stats["p_value"] for _, _, e in usable]),
            strict=True,
        )
    )
    scanned = []
    for metric in TEAM_METRICS:
        rows, signs = [], []
        for at, week in enumerate(span):
            evidence = next(e for m, a, e in tested if m == metric and a == at)
            row: dict = {"start": week.start.isoformat(), "end": week.end.isoformat()}
            if evidence.sufficient:
                moved = adjusted[(metric, at)] < FDR
                sign = (1 if evidence.stats["mean_standardized_change"] > 0 else -1) if moved else 0
                row |= {
                    "members": evidence.stats["members"],
                    "median_change": evidence.stats["median_change"],
                    "members_up": evidence.stats["members_up"],
                    "members_down": evidence.stats["members_down"],
                    "changed": moved,
                    "direction": ("up" if sign > 0 else "down") if moved else None,
                }
            else:
                sign = 0
                row["enough_people"] = False
            rows.append(row)
            signs.append(sign)
        running = 0
        for sign in reversed(signs):
            if sign == 0 or sign != signs[-1]:
                break
            running += 1
        known = [row for row in rows if "members" in row]
        status = (
            "too_little_data"
            if not known
            else "lasting"
            if running >= SUSTAINED_WEEKS
            else "new"
            if running == 1
            else "steady"
        )
        scanned.append(
            Evidence(
                tool="team_scan",
                metrics=(metric,),
                windows=(Window(start=span[0].start, end=span[-1].end), baseline),
                n=min((row["members"] for row in known), default=0),
                sufficient=bool(known),
                stats={
                    "area": AREA_OF[metric],
                    "status": status,
                    "weeks_running": running,
                    "direction": ("up" if signs[-1] > 0 else "down") if running else None,
                    "metric_weeks_tested": len(usable),
                    "weeks": rows,
                },
            )
        )
    return TeamScan(span, baseline, len(prepared), scanned)


def team_participation(frames: list[pd.DataFrame], week: Window) -> Evidence | None:
    """How many members have enough days this week, as a count. None below the floor of people."""
    if len(frames) < MIN_MEMBERS:
        return None
    active = sum(
        any(len(_values(frame, m, week)) >= MIN_WEEK_DAYS for m in ("sleep_minutes", "steps"))
        for frame in frames
    )
    return Evidence(
        tool="team_participation",
        metrics=(),
        windows=(week,),
        n=len(frames),
        sufficient=True,
        stats={"members": len(frames), "with_enough_data": int(active)},
    )


# Named levels, only for a member who chose to share them


@dataclass(frozen=True)
class Level:
    mean: float | None  # the week's mean; None with fewer than MIN_WEEK_DAYS days
    level: str | None  # "below", "usual" or "above" the person's own usual; None without one


def member_levels(frame: pd.DataFrame, week: Window) -> dict[str, Level]:
    """The week's recovery, sleep, strain and stress against the person's own previous weeks.

    "Usual" is the middle half of the means of their previous LEVEL_WEEKS weeks, as Today's usual
    range is for days; at least three earlier weeks with enough days are needed for one.
    """
    prepared = prepare(frame)
    levels = {}
    for metric in LEVEL_METRICS:
        mean = _week_mean(prepared, metric, week)
        earlier = [
            m
            for back in range(1, LEVEL_WEEKS + 1)
            if (m := _week_mean(prepared, metric, _shift(week, -back))) is not None
        ]
        level = None
        if mean is not None and len(earlier) >= 3:
            low, high = np.quantile(earlier, [0.25, 0.75])
            level = "above" if mean > high else "below" if mean < low else "usual"
        levels[metric] = Level(None if mean is None else round(mean, 2), level)
    return levels


def _shift(week: Window, weeks: int) -> Window:
    offset = timedelta(days=WEEK_DAYS * weeks)
    return Window(start=week.start + offset, end=week.end + offset)


def _week_mean(frame: pd.DataFrame, metric: str, week: Window) -> float | None:
    values = _values(frame, metric, week)
    return float(values.mean()) if len(values) >= MIN_WEEK_DAYS else None
