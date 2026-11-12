"""How often team alerts fire when nothing changed, and how soon they find a real change.

Run from the repository root: `PYTHONPATH=backend python eval/team_alert_check.py [--teams 60]`.
Free: made-up teams, no model. Each member is `app.synthetic` data with every metric (their own
level, spread and day-to-day carry-over), and each team is checked once a day for 30 days, as the
daily pass does. The same teams are judged by the old rule (real and held for four days) and the
new one (also big and broad enough: `worthwhile` in app/analysis/team.py), so the difference is the
rule alone. Prints rates; writes eval/results/team_alert_check_<date>.json.
"""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from statistics import median

from app.analysis import team
from app.synthetic import Step, generate

HERE = Path(__file__).parent
START = date(2026, 6, 1)
DAYS = 100  # 70 before the checks begin: a full baseline
CHECKS = 30
CHANGE_ON = START + timedelta(
    days=DAYS - CHECKS + 5
)  # a planted change starts on check day 5

SCENARIOS = {
    "nothing, 8 people": (8, ()),
    "nothing, 12 people": (12, ()),
    "nothing, 30 people": (30, ()),
    "sleep -60 min, 5 people": (5, (Step("sleep_minutes", CHANGE_ON, -60.0),)),
    "sleep -60 min, 8 people": (8, (Step("sleep_minutes", CHANGE_ON, -60.0),)),
    "sleep -60 min, 12 people": (12, (Step("sleep_minutes", CHANGE_ON, -60.0),)),
    "sleep -40 min, 8 people": (8, (Step("sleep_minutes", CHANGE_ON, -40.0),)),
    "resting HR +4, 8 people": (8, (Step("resting_hr", CHANGE_ON, 4.0),)),
    # Real but too small to matter: the old rule raises it in a large team.
    "sleep -12 min, 30 people": (30, (Step("sleep_minutes", CHANGE_ON, -12.0),)),
}


def run_team(size: int, effects, seed: int) -> dict:
    """Day of the first alert per metric under each rule, and the metrics raised."""
    frames = [
        team.prepare(generate(START, DAYS, effects, seed=seed * 100 + i).frame)
        for i in range(size)
    ]
    first_day = START + timedelta(days=DAYS - CHECKS)
    rolling = {}

    def day(end):
        if end not in rolling:
            rolling[end] = team._rolling(frames, end)
        return rolling[end]

    found = {"old": {}, "new": {}}
    for offset in range(CHECKS):
        end = first_day + timedelta(days=offset)
        days = [day(end - timedelta(days=back)) for back in range(team.ALERT_DAYS_HELD)]
        for metric, evidence in days[0].items():
            way = "up" if evidence.stats["mean_standardized_change"] > 0 else "down"
            if not all(
                metric in d
                and (d[metric].stats["mean_standardized_change"] > 0) == (way == "up")
                for d in days
            ):
                continue
            found["old"].setdefault((metric, way), offset)
            if team.worthwhile(metric, evidence.stats, way):
                found["new"].setdefault((metric, way), offset)
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--teams", type=int, default=60)
    args = parser.parse_args()
    results = {}
    for name, (size, effects) in SCENARIOS.items():
        planted = {(s.metric, "down" if s.delta < 0 else "up") for s in effects}
        rows = [run_team(size, effects, seed) for seed in range(args.teams)]
        summary = {"teams": args.teams, "size": size}
        for rule in ("old", "new"):
            any_alert = sum(1 for r in rows if r[rule])
            other = sum(1 for r in rows if set(r[rule]) - planted)
            hits = [r[rule][p] for r in rows for p in planted if p in r[rule]]
            summary[rule] = {
                "teams_with_any_alert": any_alert,
                "teams_with_an_unplanted_alert": other,
                "planted_found": len(hits) if planted else None,
                "median_day_found": median(hits) - 5
                if hits
                else None,  # days after it began
            }
        results[name] = summary
        print(f"{name:28} old {summary['old']}  new {summary['new']}")
    out = HERE / "results" / f"team_alert_check_{date.today().isoformat()}.json"
    out.write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
