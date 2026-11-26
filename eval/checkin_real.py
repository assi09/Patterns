"""The check-in rule (`app.teams.checkin.detect`, checkin-v1) on real people. Free, no model.

Run from the repository root: `PYTHONPATH=backend:eval python eval/checkin_real.py`.
PMData (16 people) and LifeSnaps (the 30 drawn for the evaluation, plus everyone else with enough
data, reported apart) from the git-ignored `data/eval/`. Prints counts; writes
eval/results/checkin_real_<date>.json. No person's values are kept.

Fixed before the first run (docs/plan.md, "What the real-data run can and cannot measure"):

- **A person-week** is a check on day `d` of the person's data, every 7 days from 35 days after
  their first day, with the data cut at `d` as a sync would leave it. The rule looks at the 7 days
  ending `d` against the 28 before.
- **Eligible**: at least `MIN_WORN` worn days of the 7, and at least `MIN_SIGNALS` signals with
  `MIN_BASELINE` values in the 28 days before; on any other week the rule cannot fire.
- **Firing on ordinary weeks**: alerts per eligible person-week, as the data is. These weeks are
  unlabelled, so an alert is reported as an alert, not called false.
- **Observable** (added 2026-11-26, after the first run): an eligible week where time asleep and
  resting heart rate each have a reading on at least `DAYS_FAR` worn days. Detection is reported
  over all eligible weeks (end to end) and over observable weeks, so a change missed for lack of
  readings is told apart from one missed with the readings there.
- **Detection**: on eligible weeks that did not fire, a sustained change is planted on all 7 days
  (time asleep down and resting heart rate up, by four sizes), the app's scores recomputed from
  the changed inputs, and the rule run again. Also time asleep alone, to show what one signal does.
- **Wear time**: neither dataset records it. PMData counts a day as worn when it has Fitbit's
  activity minutes; LifeSnaps counts every day. Production counts only Google's recorded wear
  time, so eligibility there can only be lower.
"""

import json
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import real_data
from app.analysis.day import with_scores
from app.teams import checkin

HERE = Path(__file__).parent
FIRST_CHECK = (
    35  # days after the person's first day: 28 for the usual range, 7 for the week
)
SIZES = [
    (30, 3),
    (60, 5),
    (90, 8),
    (120, 10),
]  # minutes less asleep, beats more resting HR
SLEEP_ONLY = 120


def eligible(frame: pd.DataFrame, today: date) -> bool:
    recent = pd.date_range(today - timedelta(days=checkin.WINDOW_DAYS - 1), today)
    if int(checkin._worn(frame, recent).sum()) < checkin.MIN_WORN:
        return False
    start = recent[0] - pd.Timedelta(days=checkin.BASELINE_DAYS)
    end = recent[0] - pd.Timedelta(days=1)
    usable = sum(
        metric in frame
        and frame[metric].loc[start:end].notna().sum() >= checkin.MIN_BASELINE
        for metric in checkin.SIGNALS
    )
    return usable >= checkin.MIN_SIGNALS


def planted(frame: pd.DataFrame, today: date, sleep: float, rhr: float) -> pd.DataFrame:
    """The raw inputs with a sustained change on the 7 days, scores recomputed from them."""
    days = pd.date_range(today - timedelta(days=checkin.WINDOW_DAYS - 1), today)
    changed = (
        frame.copy()
    )  # raw inputs: the scores are added below, from the changed values
    if "sleep_minutes" in changed:
        changed.loc[days, "sleep_minutes"] = (
            changed.loc[days, "sleep_minutes"] - sleep
        ).clip(0)
    if rhr and "resting_hr" in changed:
        changed.loc[days, "resting_hr"] = changed.loc[days, "resting_hr"] + rhr
    return with_scores(changed)


def single_signals(frame: pd.DataFrame, today: date) -> list[str]:
    """The signals that meet the rule on their own (as if one were enough), for diagnosis."""
    kept = checkin.MIN_SIGNALS
    checkin.MIN_SIGNALS = 1
    try:
        return [e.metrics[0] for e in checkin.detect(frame, today)]
    finally:
        checkin.MIN_SIGNALS = kept


def observable(frame: pd.DataFrame, today: date) -> bool:
    """Whether the planted change can be seen at all: time asleep and resting heart rate each have
    a reading on at least `DAYS_FAR` of the week's worn days, the most the rule asks of a signal.
    A week that fails this can only be missed for lack of readings, whatever the margins."""
    days = pd.date_range(today - timedelta(days=checkin.WINDOW_DAYS - 1), today)
    worn = checkin._worn(frame, days)
    return all(
        metric in frame
        and int(frame[metric].reindex(days)[worn].notna().sum()) >= checkin.DAYS_FAR
        for metric in ("sleep_minutes", "resting_hr")
    )


def run(name: str, people: dict[str, pd.DataFrame]) -> dict:
    weeks = eligible_weeks = fired = 0
    people_eligible, people_fired = set(), set()
    signals: dict[str, int] = {}
    found = {f"{s}min_{r}bpm": [0, 0] for s, r in SIZES} | {
        f"sleep_only_{SLEEP_ONLY}min": [0, 0]
    }
    largest_by_signal: dict[str, int] = {}  # which signals clear the bar on their own
    seen = {k: [0, 0] for k in found}  # the same, among observable weeks only
    seen_by_signal: dict[str, int] = {}
    for pid, raw in people.items():
        scored = with_scores(raw)
        first = raw.index.min().date()
        today = first + timedelta(days=FIRST_CHECK)
        last = raw.index.max().date()
        while today <= last:
            cut = scored.loc[: pd.Timestamp(today)]
            weeks += 1
            if eligible(cut, today):
                eligible_weeks += 1
                people_eligible.add(pid)
                alert = checkin.detect(cut, today)
                if alert:
                    fired += 1
                    people_fired.add(pid)
                    key = "+".join(sorted(e.metrics[0] for e in alert))
                    signals[key] = signals.get(key, 0) + 1
                else:
                    raw_cut = raw.loc[: pd.Timestamp(today)]
                    visible = observable(cut, today)
                    tallies = [found, seen] if visible else [found]
                    for s, r in SIZES:
                        hit = bool(checkin.detect(planted(raw_cut, today, s, r), today))
                        for tally in tallies:
                            tally[f"{s}min_{r}bpm"][0] += hit
                            tally[f"{s}min_{r}bpm"][1] += 1
                    s, r = SIZES[-1]
                    for metric in single_signals(planted(raw_cut, today, s, r), today):
                        largest_by_signal[metric] = largest_by_signal.get(metric, 0) + 1
                        if visible:
                            seen_by_signal[metric] = seen_by_signal.get(metric, 0) + 1
                    hit = bool(
                        checkin.detect(planted(raw_cut, today, SLEEP_ONLY, 0), today)
                    )
                    for tally in tallies:
                        tally[f"sleep_only_{SLEEP_ONLY}min"][0] += hit
                        tally[f"sleep_only_{SLEEP_ONLY}min"][1] += 1
            today += timedelta(days=7)
    return {
        "dataset": name,
        "people": len(people),
        "people_with_an_eligible_week": len(people_eligible),
        "person_weeks": weeks,
        "eligible_person_weeks": eligible_weeks,
        "alerts_on_ordinary_weeks": fired,
        "alert_rate_per_eligible_week": round(fired / eligible_weeks, 4)
        if eligible_weeks
        else None,
        "people_with_an_alert": len(people_fired),
        "alert_signals": signals,
        "largest_change_signals_alone": largest_by_signal,
        "planted_detection": {
            k: {"found": hit, "of": n, "rate": round(hit / n, 3) if n else None}
            for k, (hit, n) in found.items()
        },
        # Weeks where sleep and resting heart rate each had a reading on at least 5 worn days.
        "observable_weeks": seen[f"{SIZES[-1][0]}min_{SIZES[-1][1]}bpm"][1],
        "observable_signals_alone_at_largest": seen_by_signal,
        "planted_detection_observable": {
            k: {"found": hit, "of": n, "rate": round(hit / n, 3) if n else None}
            for k, (hit, n) in seen.items()
        },
    }


def main() -> None:
    lifesnaps = real_data.load_lifesnaps()
    chosen = real_data.choose_lifesnaps(lifesnaps)
    others = {k: v for k, v in lifesnaps.items() if k not in chosen}
    results = [
        run("pmdata", real_data.load_pmdata()),
        run("lifesnaps_evaluation_30", chosen),
        run("lifesnaps_others", others),
    ]
    out = {
        "rule": checkin.RULE,
        "commit": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            cwd=HERE,
        ).stdout.strip(),
        "command": "PYTHONPATH=backend:eval python eval/checkin_real.py (from the repository root)",
        "ran": date.today().isoformat(),
        "wear": "PMData: a day with activity minutes; LifeSnaps: every day (no wear time recorded)",
        "results": results,
    }
    path = HERE / "results" / f"checkin_real_{date.today().isoformat()}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
