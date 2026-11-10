"""What is worth a smart alarm: deterministic detectors over the person's own daily data.

Code decides *whether* something deserves an alarm; the agent only explains it afterwards. Each
detector returns candidates carrying the Evidence they rest on, so every alarm links to its
numbers like any answer. Only the direction that reads as a worse day counts (less sleep, lower
HRV or recovery, a higher resting heart rate or stress score): an alarm is for something that
went wrong, not for good news. Days the tracker was barely worn never trigger anything.

- **day**: last night or today far outside the person's usual range (the middle half of the 28
  days before): past its edge by 1.5 times its width (Tukey's rule for outliers), or by a floor
  per metric when the range is narrow.
- **streak**: the same metric past the worse edge of its usual range by half its width, three
  days or more in a row.

The thresholds were tuned on calm synthetic people, where noise alone should rarely raise one
(see `tests/test_alarm_detect.py`).
- **finding**: a significant change in the last 14 days against the 28 before (the screen, with
  its false-discovery correction).
- **data**: no new data for two days, or Google needs reconnecting.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from app.analysis.day import compare_day
from app.analysis.evidence import Evidence
from app.analysis.screen import MIN_EFFECT, screen
from app.analysis.tools import LOW_WEAR_MINUTES, ToolError

KINDS = ("day", "streak", "finding", "data")
# metric -> (the worse direction, the smallest gap beyond the usual range worth an alarm)
WATCHED = {
    "sleep_minutes": ("down", 30.0),
    "sleep_efficiency": ("down", 3.0),
    "recovery_score": ("down", 10.0),
    "hrv_ms": ("down", 5.0),
    "resting_hr": ("up", 3.0),
    "stress_score": ("up", 10.0),
}
SENSITIVITY = {"fewer": 1.5, "normal": 1.0, "more": 0.6}  # multiplies the margins
DAY_SPREADS = 1.5  # how many widths of the usual range past its edge a single day must be
STREAK_SPREADS = 0.5  # the same for each day of a streak
STREAK_DAYS = 3
STALE_DAYS = 2
FRESH_DAYS = 1  # a "day" alarm is about last night or today, not an older day


@dataclass(frozen=True)
class Candidate:
    kind: str
    metric: str | None
    day: date
    direction: str | None  # "up" or "down"
    severity: float  # 1 is just over the threshold; candidates are sent strongest first
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def key(self) -> str:
        """What the cooldown is kept by: the same kind of alarm about the same metric."""
        return f"{self.kind}:{self.metric or '-'}"


def _worn(frame: pd.DataFrame, day: date) -> bool:
    if "wear_minutes" not in frame.columns:
        return True
    value = (
        frame.loc[pd.Timestamp(day), "wear_minutes"] if pd.Timestamp(day) in frame.index else None
    )
    return value is None or pd.isna(value) or value >= LOW_WEAR_MINUTES


def _compare(frame: pd.DataFrame, metric: str, day: date) -> Evidence | None:
    try:
        evidence = compare_day(frame, metric, day)
    except ToolError:
        return None
    return evidence if "position" in evidence.stats else None


def _beyond(evidence: Evidence, direction: str) -> float:
    """How far the day sits past the worse edge of its usual range (negative: inside it)."""
    stats = evidence.stats
    if direction == "down":
        return stats["usual_low"] - stats["value"]
    return stats["value"] - stats["usual_high"]


def detect_day(frame: pd.DataFrame, today: date, sensitivity: str = "normal") -> list[Candidate]:
    if frame.empty:
        return []
    day = frame.index.max().date()
    if (today - day).days > FRESH_DAYS or not _worn(frame, day):
        return []
    found = []
    for metric, (direction, floor) in WATCHED.items():
        evidence = _compare(frame, metric, day)
        if evidence is None:
            continue
        spread = evidence.stats["usual_high"] - evidence.stats["usual_low"]
        margin = max(DAY_SPREADS * spread, floor) * SENSITIVITY[sensitivity]
        beyond = _beyond(evidence, direction)
        if beyond >= margin:
            found.append(Candidate("day", metric, day, direction, beyond / margin, [evidence]))
    return found


def detect_streak(frame: pd.DataFrame, today: date, sensitivity: str = "normal") -> list[Candidate]:
    if frame.empty:
        return []
    last = frame.index.max().date()
    if (today - last).days > FRESH_DAYS:
        return []
    found = []
    for metric, (direction, _) in WATCHED.items():
        run: list[Evidence] = []
        day = last
        while True:
            evidence = _compare(frame, metric, day) if _worn(frame, day) else None
            if evidence is None:
                break
            spread = evidence.stats["usual_high"] - evidence.stats["usual_low"]
            if _beyond(evidence, direction) < STREAK_SPREADS * spread * SENSITIVITY[sensitivity]:
                break
            run.append(evidence)
            day -= timedelta(days=1)
        if len(run) >= STREAK_DAYS:
            found.append(
                Candidate(
                    "streak", metric, last, direction, len(run) / STREAK_DAYS, run[:STREAK_DAYS]
                )
            )
    return found


def detect_finding(frame: pd.DataFrame, today: date) -> list[Candidate]:
    if frame.empty or (today - frame.index.max().date()).days > FRESH_DAYS:
        return []
    result = screen(frame)
    found = []
    for change in result.changes:
        if change.metric not in WATCHED:
            continue
        direction = "up" if change.evidence.stats["cliffs_delta"] > 0 else "down"
        if direction != WATCHED[change.metric][0]:
            continue
        severity = abs(change.evidence.stats["cliffs_delta"]) / MIN_EFFECT
        found.append(
            Candidate(
                "finding", change.metric, result.recent.end, direction, severity, [change.evidence]
            )
        )
    return found


def detect_data(frame: pd.DataFrame, today: date, reconnect_needed: bool) -> list[Candidate]:
    if reconnect_needed:
        return [Candidate("data", "reconnect", today, None, 1.0)]
    last = frame.index.max().date() if not frame.empty else None
    if last is None or (today - last).days >= STALE_DAYS:
        return [Candidate("data", "stale", today, None, 1.0)]
    return []


def detect(
    frame: pd.DataFrame,
    today: date,
    *,
    sensitivity: str = "normal",
    reconnect_needed: bool = False,
    kinds: tuple[str, ...] = KINDS,
) -> list[Candidate]:
    """Every candidate, strongest first; one per metric, so a bad night is not also its streak."""
    candidates: list[Candidate] = []
    if "day" in kinds:
        candidates += detect_day(frame, today, sensitivity)
    if "streak" in kinds:
        candidates += detect_streak(frame, today, sensitivity)
    if "finding" in kinds:
        candidates += detect_finding(frame, today)
    if "data" in kinds:
        candidates += detect_data(frame, today, reconnect_needed)
    best: dict[str, Candidate] = {}
    for candidate in sorted(candidates, key=lambda c: c.severity, reverse=True):
        best.setdefault(candidate.metric or candidate.kind, candidate)
    return sorted(best.values(), key=lambda c: c.severity, reverse=True)
