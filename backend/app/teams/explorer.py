"""The weekly team metric explorer (docs/team-metrics.md): every metric the live sync supports,
for one finished week, browsed on request in the app and through MCP.

A week's figures describe the people in the team when its report was made, less any who have left
since; a week without a report has no such record and gets no figures (`roster_unavailable`).
Each figure is the median of eligible members' changes from their own 28 days before the week,
with the same coverage rules as the weekly report applied to each metric on its own: a team can
have a figure for time asleep and too few staged nights for REM. Figures are descriptive. None is
tested, none enters the weekly report or its briefing, and browsing never makes a headline.

A team week is computed once and stored (`TeamMetricWeek`), so the app and MCP read the same
evidence id, and a figure once shown does not change when more days sync later. Only live Google
Health data is read (`reports.SOURCE`); Takeout history never fills a live figure.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analysis.evidence import Evidence, Window
from app.analysis.team import (
    MIN_MEMBERS,
    baseline_of,
    member_raw_change,
    prepare,
    team_metric_change,
    week_of,
)
from app.db.daily import load_daily
from app.db.models import Team, TeamMembership, TeamMetricWeek, TeamReport
from app.teams import reports
from app.teams.memberships import overlap_problem


@dataclass(frozen=True)
class ExplorerMetric:
    key: str  # the daily column, as the live sync stores it (app/sync/daily.py)
    category: str
    subgroup: str
    label: str
    unit: str  # the unit of the change as shown
    zero: str  # when 0 is a real reading and when a day is missing instead
    note: str | None = None  # how Patterns derives it, when it is not read as is
    scale: float = 1.0  # stored units to shown units (bedtime: hours to minutes)


STAGED = (
    "Counted only on nights recorded with sleep stages; a night without stages is missing, never 0."
)
LEVEL = (
    "0 is real on a worn day with no minutes at this level; a day without activity data, or "
    "barely worn, is missing."
)
ZONE = (
    "0 is real on a worn day the heart rate never reached this zone; a day without zone data, or "
    "barely worn, is missing."
)
AZM_ZERO = (
    "0 when Google reports zero for the zone sums; a day whose roll-up carries no sum at all, or "
    "barely worn, is missing, so a day without zone minutes may count as missing, not 0."
)
TOTAL = "A day without data, or barely worn, is missing; 0 is not expected on a worn day."
NIGHTLY = "A day without a reading is missing; never 0."
SCORE = "Computed by Patterns on days with enough of its inputs; otherwise missing."

# Category, then subgroup, then metric, in the order the explorer lists them.
CATALOG: tuple[ExplorerMetric, ...] = (
    ExplorerMetric(
        "sleep_minutes",
        "Sleep",
        "Duration",
        "Time asleep",
        "min",
        "One value per night of main sleep; a night without a main sleep is missing.",
    ),
    ExplorerMetric(
        "time_in_bed",
        "Sleep",
        "Duration",
        "Time in bed",
        "min",
        "One value per night of main sleep; a night without a main sleep is missing.",
        "Patterns-calculated: the length of the main sleep session, from its start to its end.",
    ),
    ExplorerMetric(
        "bedtime_hour",
        "Sleep",
        "Timing",
        "Bedtime",
        "min",
        "One value per night of main sleep; a later bedtime is a positive change.",
        "Patterns-calculated: the main sleep session's start in local time.",
        scale=60.0,
    ),
    ExplorerMetric("deep_sleep_minutes", "Sleep", "Stages", "Deep sleep", "min", STAGED),
    ExplorerMetric("light_sleep_minutes", "Sleep", "Stages", "Light sleep", "min", STAGED),
    ExplorerMetric("rem_sleep_minutes", "Sleep", "Stages", "REM sleep", "min", STAGED),
    ExplorerMetric("awake_in_bed_minutes", "Sleep", "Stages", "Awake in bed", "min", STAGED),
    ExplorerMetric(
        "sleep_efficiency",
        "Sleep",
        "Efficiency",
        "Sleep efficiency",
        "percentage points",
        "Missing on a night without a main sleep or without minutes asleep.",
        "Patterns-calculated: minutes asleep ÷ time in bed × 100, rounded. The Google Health "
        "API gives no efficiency, so this is not Fitbit's own figure.",
    ),
    ExplorerMetric("steps", "Movement", "Totals", "Steps", "steps", TOTAL),
    ExplorerMetric("distance_km", "Movement", "Totals", "Distance", "km", TOTAL),
    ExplorerMetric(
        "calories",
        "Movement",
        "Totals",
        "Calories burned",
        "kcal",
        TOTAL,
        "Total calories, including the body's resting burn.",
    ),
    ExplorerMetric(
        "lightly_active_minutes", "Movement", "Activity intensity", "Light activity", "min", LEVEL
    ),
    ExplorerMetric(
        "moderately_active_minutes",
        "Movement",
        "Activity intensity",
        "Moderate activity",
        "min",
        LEVEL,
    ),
    ExplorerMetric(
        "very_active_minutes", "Movement", "Activity intensity", "Vigorous activity", "min", LEVEL
    ),
    ExplorerMetric(
        "hr_zone_light_minutes",
        "Heart",
        "Time in heart-rate zones",
        "Below fat burn zone",
        "min",
        ZONE,
        "Actual minutes in the zone, each counted once.",
    ),
    ExplorerMetric(
        "hr_zone_moderate_minutes",
        "Heart",
        "Time in heart-rate zones",
        "Fat burn zone",
        "min",
        ZONE,
        "Actual minutes in the zone, each counted once.",
    ),
    ExplorerMetric(
        "hr_zone_vigorous_minutes",
        "Heart",
        "Time in heart-rate zones",
        "Cardio zone",
        "min",
        ZONE,
        "Actual minutes in the zone, each counted once.",
    ),
    ExplorerMetric(
        "hr_zone_peak_minutes",
        "Heart",
        "Time in heart-rate zones",
        "Peak zone",
        "min",
        ZONE,
        "Actual minutes in the zone, each counted once.",
    ),
    ExplorerMetric(
        "active_zone_minutes",
        "Heart",
        "Active Zone Minutes",
        "Active Zone Minutes (weighted)",
        "min",
        AZM_ZERO,
        "Weighted: a fat burn minute counts once, a cardio or peak minute twice, so this is not "
        "the time spent in zones.",
    ),
    ExplorerMetric(
        "resting_hr", "Heart", "Resting and overnight", "Resting heart rate", "bpm", NIGHTLY
    ),
    ExplorerMetric(
        "hrv_ms", "Heart", "Resting and overnight", "Heart rate variability", "ms", NIGHTLY
    ),
    ExplorerMetric(
        "recovery_score",
        "Scores",
        "Patterns scores",
        "Recovery",
        "points",
        SCORE,
        "Patterns-calculated (0-100) from heart rate variability, resting heart rate and time "
        "asleep, each against the person's 28 days before.",
    ),
    ExplorerMetric(
        "strain",
        "Scores",
        "Patterns scores",
        "Strain",
        "points",
        SCORE,
        "Patterns-calculated (0-21) from time in heart-rate zones, or Active Zone Minutes on a "
        "day without zone data.",
    ),
    ExplorerMetric(
        "stress_score",
        "Scores",
        "Patterns scores",
        "Stress",
        "points",
        SCORE,
        "Patterns-calculated (0-100) from daytime heart rate while still, heart rate "
        "variability, resting heart rate and time asleep.",
    ),
)
BY_KEY = {m.key: m for m in CATALOG}

MEASURED = (
    "For each person, the week's average minus the average of their own 28 days before; the "
    "figure is the median of those changes."
)
METHOD = (
    "A person counts on this metric with at least 4 days of it in the week and 14 in the 28 days "
    "before; a figure needs at least 5 such people. Live Google Health data only."
)
LIMITS = (
    "Team aggregates from at least 5 people; no person's value is shown.",
    "A description of a change, not a test: browsing many metrics, some move by chance.",
    "Describes a change in readings; it does not establish a cause.",
    "Not part of the weekly briefing; looking at it here does not make it a headline.",
)


ROSTER_UNAVAILABLE = (
    "Unavailable: who belonged to the team that week is not on record. Figures describe the "
    "people in the team when the week's report was made, and this week has no report."
)


class NotFound(LookupError):
    """No such metric or evidence for this team's week; says no more than that."""


def compute(frames: list, week: Window) -> dict[str, Evidence]:
    """Every catalogue metric's evidence for `week`, from members' live daily frames."""
    prepared = [prepare(frame) for frame in frames]
    out = {}
    for metric in CATALOG:
        changes = [member_raw_change(frame, metric.key, week) for frame in prepared]
        out[metric.key] = team_metric_change(
            [c for c in changes if c is not None], metric.key, week
        )
    return out


def roster_cutoff(db: Session, team: Team, week: Window) -> datetime | None:
    """When the week's report was made: who belonged to the team then is who the week's figures
    describe. None without a report, when that roster is not on record."""
    return db.scalar(
        select(TeamReport.created_at).where(
            TeamReport.team_id == team.id, TeamReport.week_start == week.start
        )
    )


def historical_roster(db: Session, team: Team, cutoff: datetime) -> tuple[int, list[uuid.UUID]]:
    """How many people were in the team at `cutoff`, and those of them still in it now.

    Membership rows keep their join and leave times (a rejoin is a new row), so who belonged at a
    past moment is on record. Someone who joined after the cutoff is never counted, however much
    earlier data they bring; someone who has left since is left out of a new snapshot."""
    rows = db.execute(
        select(TeamMembership.user_id, TeamMembership.joined_at, TeamMembership.left_at).where(
            TeamMembership.team_id == team.id
        )
    ).all()
    then = {u for u, joined, left in rows if joined <= cutoff and (left is None or left > cutoff)}
    still = {u for u, _, left in rows if left is None}
    return len(then), sorted(then & still)


def week_figures(db: Session, team: Team, week: Window, now: datetime) -> TeamMetricWeek | None:
    """The team's stored figures for a finished `week`, made now if they were not made yet,
    from the people in the team when the week's report was made, less any who have left since.
    None when that roster is not on record (no report for the week). The caller checks the week
    is over and the team is not paused."""
    found = _stored(db, team, week)
    if found is not None:
        return found
    cutoff = roster_cutoff(db, team, week)
    if cutoff is None:
        return None
    belonged, eligible = historical_roster(db, team, cutoff)
    # The same days the report reads, and nothing after the week's last day.
    start, end = week.start - timedelta(days=reports.HISTORY_DAYS), week.end + timedelta(days=1)
    frames = [
        frame
        for user_id in eligible
        if not (frame := load_daily(db, user_id, reports.SOURCE, start, end)).empty
    ]
    row = TeamMetricWeek(
        team_id=team.id,
        week_start=week.start,
        members_total=belonged,
        members_with_data=len(frames),
        results={k: e.model_dump(mode="json") for k, e in compute(frames, week).items()},
        made_at=now,
    )
    try:
        with db.begin_nested():  # a request racing this one may store the week first
            db.add(row)
    except IntegrityError:
        return _stored(db, team, week)
    return row


def _span(window: Window) -> dict:
    return {"start": window.start.isoformat(), "end": window.end.isoformat()}


def weeks_offered(db: Session, team: Team, today: date) -> list[str]:
    """Weeks to choose from, newest first: the last full week, and every week with a report or
    stored figures."""
    latest = reports.last_full_week(today).start
    starts = {latest}
    for model in (TeamReport, TeamMetricWeek):
        starts |= set(db.scalars(select(model.week_start).where(model.team_id == team.id)))
    return [s.isoformat() for s in sorted(starts, reverse=True) if s <= latest]


def _state(record: dict) -> str:
    if record["sufficient"]:
        return "figure"
    return "below_minimum" if record["n"] else "no_data"


def _why(metric: ExplorerMetric, record: dict) -> str | None:
    n = record["n"]
    if record["sufficient"]:
        return None
    if n:
        return (
            f"Withheld: {n} of the {MIN_MEMBERS} people needed had enough {metric.label.lower()} "
            "data for this week and the 28 days before."
        )
    return (
        f"Unavailable: no one had enough synced {metric.label.lower()} data for this week and "
        "the 28 days before."
    )


def _change(metric: ExplorerMetric, raw: float) -> dict:
    value = raw * metric.scale
    value = round(value) if metric.scale != 1.0 or abs(value) >= 10 else round(value, 1)
    shown = f"{value:+,}" if isinstance(value, int) else f"{value:+,.1f}"
    return {"value": value, "unit": metric.unit, "text": f"{shown} {metric.unit}"}


def _row(metric: ExplorerMetric, record: dict) -> dict:
    out = {
        "metric": metric.key,
        "label": metric.label,
        "unit": metric.unit,
        "state": _state(record),
        "evidence_id": record["id"],
        "contributors": record["n"],
        "change": None,
        "withheld": _why(metric, record),
    }
    if record["sufficient"]:
        out["change"] = _change(metric, record["stats"]["median_change"])
    return out


def _unavailable_then(week: Window, as_of: date) -> dict:
    return {
        "state": "not_available_then",
        "week": _span(week),
        "message": f"These figures were not available by {as_of.isoformat()}.",
    }


def metrics_view(
    db: Session,
    team: Team,
    week: date | None,
    now: datetime,
    as_of: date | None = None,
    today: date | None = None,
) -> dict:
    """The explorer's list for one week, grouped by category and subgroup, each metric with its
    change or why it has none. The same dict for the app and MCP. `today` is the supervisor's
    own date when it differs from `now`'s; `as_of` limits it to figures stored by that day."""
    today = today or now.date()
    asked = week_of(week) if week is not None else reports.last_full_week(today)
    head = {
        "team_id": str(team.id),
        "week": _span(asked),
        "baseline": _span(baseline_of(asked)),
        "weeks": weeks_offered(db, team, today),
        "minimum_members": MIN_MEMBERS,
    }
    if asked.start > reports.last_full_week(today).start:
        return head | {"state": "week_not_over", "message": "This week is not over yet."}
    if paused := overlap_problem(db, team):
        return head | {"state": "paused", "message": paused}
    if as_of is not None and as_of < today:
        # Only figures stored by then: making them now would read days synced since.
        stored = _stored(db, team, asked)
        if stored is None or stored.made_at.date() > as_of:
            return head | _unavailable_then(asked, as_of)
        row = stored
    else:
        row = week_figures(db, team, asked, now)
        if row is None:
            return head | {"state": "roster_unavailable", "message": ROSTER_UNAVAILABLE}
    categories: list[dict] = []
    for metric in CATALOG:
        if not categories or categories[-1]["name"] != metric.category:
            categories.append({"name": metric.category, "subgroups": []})
        groups = categories[-1]["subgroups"]
        if not groups or groups[-1]["name"] != metric.subgroup:
            groups.append({"name": metric.subgroup, "metrics": []})
        groups[-1]["metrics"].append(_row(metric, row.results[metric.key]))
    return head | {
        "state": "ready",
        "made_on": row.made_at.date().isoformat(),
        "roster": row.members_total,
        "members_with_data": row.members_with_data,
        "categories": categories,
    }


def _stored(db: Session, team: Team, week: Window) -> TeamMetricWeek | None:
    return db.scalar(
        select(TeamMetricWeek).where(
            TeamMetricWeek.team_id == team.id, TeamMetricWeek.week_start == week.start
        )
    )


def metric_view(
    db: Session,
    team: Team,
    week: date | None,
    metric: str,
    now: datetime,
    as_of: date | None = None,
    today: date | None = None,
) -> dict:
    """One metric's evidence for one week: what was measured, its dates, method, the team figure
    and its coverage, and its limits. NotFound for an unknown metric. The same dict for both."""
    info = BY_KEY.get(metric)
    if info is None:
        raise NotFound
    listed = metrics_view(db, team, week, now, as_of, today)
    if listed["state"] != "ready":
        return listed | {"metric": metric, "label": info.label}
    asked = week_of(date.fromisoformat(listed["week"]["start"]))
    record = _stored(db, team, asked).results[metric]
    out = {
        "state": _state(record),
        "evidence_id": record["id"],
        "team_id": listed["team_id"],
        "metric": metric,
        "label": info.label,
        "category": info.category,
        "subgroup": info.subgroup,
        "unit": info.unit,
        "week": listed["week"],
        "baseline": listed["baseline"],
        "made_on": listed["made_on"],
        "figure_label": "Median change from each person's own previous 28 days",
        "change": None,
        "higher": None,
        "lower": None,
        "unchanged": None,
        "coverage": {
            "contributors": record["n"],
            "minimum": MIN_MEMBERS,
            "roster": listed["roster"],
            "with_any_data": listed["members_with_data"],
        },
        "withheld": _why(info, record),
        "measured": MEASURED,
        "method": METHOD,
        "zero_and_missing": info.zero,
        "derivation": info.note,
        "source": "Google Health live sync",
        "limitations": list(LIMITS),
    }
    if record["sufficient"]:
        stats = record["stats"]
        out |= {
            "change": _change(info, stats["median_change"]),
            "higher": stats["members_up"],
            "lower": stats["members_down"],
            "unchanged": stats["members_unchanged"],
        }
    return out
