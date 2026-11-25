"""The team's meeting load from its members' calendars, under the team rules (docs/teams.md).

Deterministic, like every team figure. Each member is compared with their own usual week (the 28
days before, scaled to seven), only changes and per-person weekly totals are pooled, and nothing
is reported from fewer than MIN_MEMBERS people. Members who never connected a calendar are left
out, not counted as free. The week ahead is what is already planned, reported the same way.
"""

from datetime import timedelta

import numpy as np
import pandas as pd

from app.analysis.evidence import Evidence, Window
from app.analysis.team import BASELINE_DAYS, MIN_BASELINE_DAYS, MIN_MEMBERS, WEEK_DAYS

# metric -> (what a supervisor reads, its unit)
LOAD = {
    "meeting_minutes": ("Time in meetings", "min"),
    "after_hours_minutes": ("Meetings after hours", "min"),
    "back_to_back": ("Back-to-back meetings", "count"),
    "meetings": ("Meetings", "count"),
    "focus_minutes": ("Focus time", "min"),
}
CHANGE_SHARE = 0.10  # a member counts as up or down when their week moved by 10% of their usual
MIN_CHANGE = {"min": 30.0, "count": 1.0}  # and by at least this much


def _week_total(frame: pd.DataFrame, metric: str, window: Window) -> float | None:
    days = frame[metric].loc[pd.Timestamp(window.start) : pd.Timestamp(window.end)].dropna()
    return float(days.sum()) if len(days) == window.days else None  # a calendar week is whole


def _usual_week(frame: pd.DataFrame, metric: str, before: Window) -> float | None:
    days = frame[metric].loc[pd.Timestamp(before.start) : pd.Timestamp(before.end)].dropna()
    return float(days.mean() * WEEK_DAYS) if len(days) >= MIN_BASELINE_DAYS else None


def team_load(frames: list[pd.DataFrame], week: Window) -> list[Evidence]:
    """One record per metric in LOAD for the week, each from at least MIN_MEMBERS people or
    marked insufficient with its count only. `frames` are members' google_calendar tables."""
    before = Window(
        start=week.start - timedelta(days=BASELINE_DAYS), end=week.start - timedelta(days=1)
    )
    ahead = Window(start=week.end + timedelta(days=1), end=week.end + timedelta(days=WEEK_DAYS))
    found = []
    for metric, (label, unit) in LOAD.items():
        totals, changes, moved, planned = [], [], [], []
        for frame in frames:
            if metric not in frame.columns:
                continue
            total, usual = _week_total(frame, metric, week), _usual_week(frame, metric, before)
            if total is None or usual is None:
                continue
            totals.append(total)
            changes.append(total - usual)
            moved.append(max(MIN_CHANGE[unit], CHANGE_SHARE * usual))  # what counts as a change
            following = _week_total(frame, metric, ahead)
            if following is not None:
                planned.append(following)
        n = len(totals)
        stats: dict = {"label": label, "unit": unit, "members": n, "minimum": MIN_MEMBERS}
        if n >= MIN_MEMBERS:
            stats |= {
                "median_week": round(float(np.median(totals)), 1),
                "q1_week": round(float(np.percentile(totals, 25)), 1),
                "q3_week": round(float(np.percentile(totals, 75)), 1),
                "median_change": round(float(np.median(changes)), 1),
                "members_up": sum(c >= t for c, t in zip(changes, moved, strict=True)),
                "members_down": sum(c <= -t for c, t in zip(changes, moved, strict=True)),
            }
            if len(planned) >= MIN_MEMBERS:
                stats |= {
                    "planned_members": len(planned),
                    "median_planned": round(float(np.median(planned)), 1),
                }
        found.append(
            Evidence(
                tool="team_calendar_load",
                metrics=(metric,),
                windows=(before, week),
                n=n,
                sufficient=n >= MIN_MEMBERS,
                stats=stats,
            )
        )
    return found
