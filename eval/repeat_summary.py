"""Rates over repeated runs of `agent_eval.py`: how often each turn passed, by area.

Run from the repository root after several runs: `python eval/repeat_summary.py r1 r2 r3`, using the
tags given to `agent_eval.py` (the date is today's).
"""

import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).parent / "results"
STAMP = datetime.now(UTC).date().isoformat()
runs = [
    [json.loads(line) for line in (HERE / f"agent_eval_{STAMP}_{tag}.jsonl").open()]
    for tag in sys.argv[1:]
]
turns = defaultdict(list)
for run in runs:
    for row in run:
        if "problems" in row:
            turns[(row["area"], row["name"], row.get("turn"), row["q"])].append(row)
areas = defaultdict(lambda: [0, 0])
flaky, failing = [], []
for key, rows in turns.items():
    passed = sum(not r["problems"] for r in rows)
    areas[key[0]][0] += passed
    areas[key[0]][1] += len(rows)
    if passed == 0:
        failing.append(key[3])
    elif passed < len(rows):
        flaky.append(f"{passed}/{len(rows)} {key[3]}")
rows = [r for run in runs for r in run if "cost" in r]
print(
    json.dumps(
        {
            "runs": len(runs),
            "pass_rate": round(
                sum(v[0] for v in areas.values()) / sum(v[1] for v in areas.values()), 3
            ),
            "by_area": {a: f"{v[0]}/{v[1]}" for a, v in sorted(areas.items())},
            "mean_cost": round(sum(r["cost"] for r in rows) / len(rows), 4),
            "mean_calls": round(sum(r["calls"] for r in rows) / len(rows), 2),
            "always_failed": failing,
            "sometimes_failed": flaky,
        },
        indent=1,
    )
)
