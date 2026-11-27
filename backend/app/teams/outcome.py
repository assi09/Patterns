"""What followed an ended team change: one of four outcomes against a stated reference.

A change is measured against the 28 days before it started. It is usually started right after a
report shows a drop, and then an ordinary rebound from that drop reads as an improvement
(docs/change-memory.md, step 0: 39 to 84% of simulated do-nothing changes). So every result says
so. A comparison chosen before the outcome is seen (the 28 days before a linked finding's first
flagged week) is part of the change-memory plan, not built here.

Nothing here says "better", "worse", "worked" or "returned to baseline": "no clear difference
detected" is not evidence of no difference, and no comparison can tell how much the change itself
contributed. Deterministic, like every number in a report.
"""

from datetime import date, timedelta

from app.analysis.evidence import Evidence, Window
from app.analysis.report import change_text
from app.analysis.screen import FDR
from app.analysis.team import MIN_MEMBERS, member_change, prepare, team_change, team_info
from app.db.models import TeamAction

OUTCOMES = {
    "above": "above the reference level",
    "below": "below the reference level",
    "no_clear_difference": "no clear difference detected",
    "insufficient_data": "insufficient data",
}
BEFORE_CHANGE = "before_the_change"
REFERENCES = {BEFORE_CHANGE: "the 28 days before the change started"}
CONTRIBUTION = (
    "An observation during the change: it cannot show how much the change itself contributed."
)
REBOUND = (
    "This is compared with the 28 days just before the change. If the team had just dipped, an "
    "ordinary rebound can look like an improvement."
)
REFERENCE_DAYS = 28
# How a change's result is computed, said once so the outcome card and its evidence record agree.
MEASURED = (
    "For each person, the average during the change minus the person's own average over the 28 "
    "days before the change started (the baseline dates); the team figure is the median across "
    "people."
)
METHOD = (
    "A one-sample t-test of whether the team's changes, each in units of the person's own spread "
    f"over the baseline days, are centred away from zero. The result is above or below the "
    f"reference level when this one test gives p < {FDR} and the median difference is not zero, "
    "with no correction across metrics; otherwise no clear difference detected. With fewer than "
    f"{MIN_MEMBERS} people with data it is insufficient data, and no figure is computed."
)


def reference(action: TeamAction) -> Window:
    """The comparison days: the 28 before the change started."""
    start = action.starts_on
    return Window(start=start - timedelta(days=REFERENCE_DAYS), end=start - timedelta(1))


def measure(frames: list, action: TeamAction) -> Evidence:
    """The team's metric during the change against its reference, as for a weekly change."""
    window = Window(start=action.starts_on, end=action.ends_on)
    base = reference(action)
    changes = [member_change(prepare(f), action.metric, window, base) for f in frames]
    return team_change([c for c in changes if c is not None], action.metric, window, base)


def outcome_of(record: dict) -> str:
    """The same test as before (p < FDR, a non-zero median), named without a judgement."""
    if not record.get("sufficient"):
        return "insufficient_data"
    stats = record["stats"]
    median = stats.get("median_change") or 0
    if stats.get("p_value", 1.0) >= FDR or median == 0:
        return "no_clear_difference"
    return "above" if median > 0 else "below"


def _day(value: str) -> str:
    return f"{date.fromisoformat(value):%b %-d, %Y}"


def describe(action: TeamAction, evidence: Evidence | dict) -> dict:
    """The outcome of a measured change, for the app and MCP: no person, no free text."""
    record = evidence.model_dump(mode="json") if isinstance(evidence, Evidence) else evidence
    windows = record.get("windows") or []
    during, base = (windows + [None, None])[:2]
    kind = BEFORE_CHANGE  # a stored record keeps its own dates, read from the record
    outcome = outcome_of(record)
    stats = record.get("stats") or {}
    metric = action.metric
    label = team_info(metric).label
    against = (
        f"against {_day(base['start'])} to {_day(base['end'])} ({REFERENCES[kind]})"
        if base
        else f"against {REFERENCES[kind]}"
    )
    out = {
        "outcome": outcome,
        "label": OUTCOMES[outcome],
        "method": METHOD,
        "metric": metric,
        "metric_label": label,
        "during": during,
        "reference": {"kind": kind, "label": REFERENCES[kind], **(base or {})},
        "contributors": stats.get("members", 0),
        "minimum": MIN_MEMBERS,
        "evidence_id": record.get("id"),
        "caveats": [CONTRIBUTION, REBOUND],
    }
    if outcome == "insufficient_data":
        out["text"] = (
            f"{label}: insufficient data ({stats.get('members', 0)} people with data; "
            f"{MIN_MEMBERS} needed)."
        )
        return out
    difference = change_text(metric, stats["median_change"])
    out |= {
        "difference": difference,
        "higher": stats["members_up"],
        "lower": stats["members_down"],
    }
    out["text"] = (
        f"{label}: {OUTCOMES[outcome]} during the change, median difference {difference} "
        f"{against}; {stats['members']} people with data."
    )
    return out
