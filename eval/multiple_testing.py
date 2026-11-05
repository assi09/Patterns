"""What correcting a run's own tests together costs and buys, on synthetic people. Free: no model.

Each simulated run is the battery of tests an agent typically makes when asked about sleep
(window comparisons, change points, correlations with possible drivers, weekday splits), on a
person with nothing planted (any significant test is a false positive) or with a planted change
(bedtime 1 h later and sleep shorter from day 45, sleep following bedtime). For each way of
deciding significance it reports how often a run finds something false, and how often it finds
what was planted. Run from the repository root: `PYTHONPATH=backend python eval/multiple_testing.py`.
"""

import sys
from datetime import date, timedelta

from app.analysis import tools
from app.analysis.evidence import Window
from app.analysis.screen import benjamini_hochberg
from app.synthetic import Coupling, Step, generate

ALPHA = 0.05
START, DAYS, CHANGE = date(2026, 7, 1), 60, 45
SEEDS = int(sys.argv[1]) if len(sys.argv) > 1 else 200


def w(a: int, b: int) -> Window:
    return Window(start=START + timedelta(a), end=START + timedelta(b))


def battery(frame):
    recent, baseline, whole = w(CHANGE, DAYS - 1), w(0, CHANGE - 1), w(0, DAYS - 1)
    tests = []
    for m in ("sleep_minutes", "bedtime_hour", "time_in_bed", "sleep_efficiency",
              "deep_sleep_minutes", "awake_in_bed_minutes"):
        tests.append(tools.compare_windows(frame, m, recent, baseline))
    for m in ("sleep_minutes", "bedtime_hour", "sleep_efficiency"):
        tests.append(tools.change_point(frame, m, whole))
    for driver in ("bedtime_hour", "steps", "active_zone_minutes", "resting_hr", "very_active_minutes"):
        tests.append(tools.correlate(frame, driver, "sleep_minutes", whole, 2))
    for m in ("sleep_minutes", "bedtime_hour"):
        tests.append(tools.weekday_split(frame, m, whole))
    return tests


def base_p(e) -> float:
    p = e.stats.get("p_value_adjusted", e.stats.get("p_value"))  # correlations: lags corrected
    return 1.0 if p is None else p


def decisions(tests):
    """Which tests count as significant under each rule."""
    p = [base_p(e) for e in tests]
    is_assoc = [e.tool == "correlate" for e in tests]
    out = {"raw": [x < ALPHA for x in p]}
    out["BH, all tests"] = [q < ALPHA for q in benjamini_hochberg(p)]
    for name, keep in (("BH, per family", None), ("BH, associations only", "assoc")):
        sig = [x < ALPHA for x in p]
        families = [True, False] if keep is None else [True]
        for family in families:
            idx = [i for i, a in enumerate(is_assoc) if a == family]
            q = benjamini_hochberg([p[i] for i in idx])
            for i, qi in zip(idx, q, strict=True):
                sig[i] = qi < ALPHA
        out[name] = sig
    return out


def found(tests, sig, tool, metric):
    return any(s and e.tool == tool and metric in e.metrics for e, s in zip(tests, sig, strict=True))


rules = ["raw", "BH, all tests", "BH, per family", "BH, associations only"]
null_any = dict.fromkeys(rules, 0)
null_assoc = dict.fromkeys(rules, 0)
power = {r: {"sleep change": 0, "bedtime change": 0, "bedtime-sleep association": 0} for r in rules}
planted = (
    Step("bedtime_hour", START + timedelta(CHANGE), 1.0),
    Coupling("bedtime_hour", "sleep_minutes", lag_days=0, strength=-0.6),
    Step("sleep_minutes", START + timedelta(CHANGE), -30),
)
for seed in range(SEEDS):
    calm = battery(generate(START, DAYS, seed=1000 + seed).frame)
    for rule, sig in decisions(calm).items():
        null_any[rule] += any(sig)
        null_assoc[rule] += any(s for e, s in zip(calm, sig, strict=True) if e.tool == "correlate")
    shifted = battery(generate(START, DAYS, planted, seed=seed).frame)
    for rule, sig in decisions(shifted).items():
        power[rule]["sleep change"] += found(shifted, sig, "compare_windows", "sleep_minutes")
        power[rule]["bedtime change"] += found(shifted, sig, "compare_windows", "bedtime_hour")
        power[rule]["bedtime-sleep association"] += (
            found(shifted, sig, "correlate", "bedtime_hour")
        )

print(f"{SEEDS} people per condition, {len(battery(generate(START, DAYS, seed=1).frame))} tests per run")
print(f"{'rule':<24} {'null: any false':>16} {'null: false assoc.':>19} "
      f"{'sleep change':>13} {'bedtime change':>15} {'association':>12}")
for r in rules:
    pw = power[r]
    print(f"{r:<24} {null_any[r] / SEEDS:>16.0%} {null_assoc[r] / SEEDS:>19.0%} "
          f"{pw['sleep change'] / SEEDS:>13.0%} {pw['bedtime change'] / SEEDS:>15.0%} "
          f"{pw['bedtime-sleep association'] / SEEDS:>12.0%}")
