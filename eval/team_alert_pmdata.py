"""Team alerts on real people: PMData's 16 people as one team. Free, no model.

Run from the repository root: `PYTHONPATH=backend:eval python eval/team_alert_pmdata.py`.
Each day from 70 days after the data starts to its end is a daily check, as in production. Counts
the alerts raised by the old rule (real, held four days) and the new one (also big and broad
enough), as they are, and with a 60-minute drop in time asleep planted for everyone from a fixed
day. Prints counts; writes eval/results/team_alert_pmdata_<date>.json. Nothing personal is kept.
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import real_data
from app.analysis import team

HERE = Path(__file__).parent


def checks(frames, first, last):
    prepared = [team.prepare(f) for f in frames]
    rolling, raised = {}, {"old": {}, "new": {}}

    def day(end):
        if end not in rolling:
            rolling[end] = team._rolling(prepared, end)
        return rolling[end]

    end = first
    while end <= last:
        days = [day(end - timedelta(days=b)) for b in range(team.ALERT_DAYS_HELD)]
        for metric, evidence in days[0].items():
            way = "up" if evidence.stats["mean_standardized_change"] > 0 else "down"
            if all(
                metric in d
                and (d[metric].stats["mean_standardized_change"] > 0) == (way == "up")
                for d in days
            ):
                raised["old"].setdefault((metric, way), end.isoformat())
                if team.worthwhile(metric, evidence.stats, way):
                    raised["new"].setdefault((metric, way), end.isoformat())
        end += timedelta(days=1)
    return {
        rule: {f"{m} {w}": d for (m, w), d in found.items()}
        for rule, found in raised.items()
    }


def main():
    people = real_data.load_pmdata()
    frames = list(people.values())
    start = min(f.index.min() for f in frames).date()
    last = max(f.index.max() for f in frames).date()
    first = start + timedelta(days=70)
    planted_on = first + timedelta(days=21)
    as_is = checks(frames, first, last)
    dropped = []
    for frame in frames:
        changed = frame.copy()
        after = changed.index >= pd.Timestamp(planted_on)
        changed.loc[after, "sleep_minutes"] = changed.loc[after, "sleep_minutes"] - 60
        dropped.append(changed)
    planted = checks(dropped, first, last)
    result = {
        "people": len(frames),
        "days_checked": (last - first).days + 1,
        "planted_on": planted_on.isoformat(),
        "as_is": as_is,
        "sleep_down_60": planted,
    }
    out = HERE / "results" / f"team_alert_pmdata_{date.today().isoformat()}.json"
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
