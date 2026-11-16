"""The verifier on its own: does it pass true claims and catch broken ones, on real people's data?

PHIA's runs show how often the verifier rejects a claim, not whether it was right to. Here code
writes true claims from real people's evidence (PMData, LifeSnaps), in the forms the agent uses:
values, highs, totals, one day against the usual range, a change or no change, rounded or in hours
and minutes. Each is then broken one way at a time (a wrong number, a date outside the evidence, a
reversed direction, the wrong metric, a change that is not significant, causal or medical wording,
too little data). Reported: the share of true claims wrongly rejected, and the share of each break
caught. Free and deterministic: the verifier is code, no model is called.

    PYTHONPATH=backend:eval python eval/verifier_check.py

Only totals are printed and saved; the claims hold real people's values and stay in memory.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pandas as pd
import real_data
from app.agent.present import duration, format_level, label, short_date
from app.agent.verifier import ALPHA, Claim, check_claim
from app.analysis.day import compare_day
from app.analysis.evidence import Evidence, ToolError, Window
from app.analysis.tools import ADDITIVE, compare_windows, describe

SUMMARY = Path("eval/results/verifier_check_summary.json")
METRICS = ("steps", "sleep_minutes", "resting_hr", "deep_sleep_minutes", "hrv_ms")
# A metric the claim is switched to, which the cited evidence does not cover.
OTHER = {
    "steps": "sleep_minutes",
    "sleep_minutes": "steps",
    "resting_hr": "steps",
    "deep_sleep_minutes": "steps",
    "hrv_ms": "sleep_minutes",
}
DAYS = 21  # each window; the agent's usual "last three weeks against the three before"
MIN_PRESENT = 0.8


@dataclass
class Case:
    """A claim and the evidence it may cite. `ok` says whether the verifier should pass it."""

    kind: str  # the form of the claim, or the break applied to it
    ok: bool
    claim: Claim
    evidence: dict[str, Evidence] = field(repr=False)


def name(metric: str) -> str:
    text = label(metric)
    return text if text[:3].isupper() else text[0].lower() + text[1:]


def claim(text, kind, evidence, metric, direction=None) -> Claim:
    return Claim(
        text=text,
        kind=kind,
        evidence_ids=[e.id for e in evidence],
        metric=metric,
        direction=direction,
    )


def forms(metric: str, value: float) -> list[str]:
    """The ways the agent may state one value, all true: as the app formats it, and for durations
    in plain minutes or decimal hours, for counts rounded to the hundred."""
    out = [format_level(metric, value)]
    if metric.endswith("_minutes"):
        out += [f"{round(value)} minutes", f"{value / 60:.1f} hours"]
    elif abs(value) >= 1000:
        out.append(f"about {round(value, -2):,.0f}")
    return out


def wrong(metric: str, value: float, factor: float) -> str:
    return format_level(metric, value * factor)


def cases_for(frame: pd.DataFrame, metric: str) -> list[Case]:
    values = frame[metric].dropna()
    if values.empty:
        return []
    end = values.index.max().date()
    recent = Window(start=end - timedelta(DAYS - 1), end=end)
    base = Window(start=end - timedelta(2 * DAYS - 1), end=end - timedelta(DAYS))
    rows = frame.loc[pd.Timestamp(base.start) : pd.Timestamp(end), metric]
    if rows.notna().sum() < MIN_PRESENT * 2 * DAYS:
        return []
    d = describe(frame, metric, recent)
    c = compare_windows(frame, metric, recent, base)
    try:
        day = compare_day(frame, metric, end)
    except ToolError:
        day = None
    thin = describe(frame, metric, Window(start=end - timedelta(1), end=end))
    other = OTHER[metric]
    span = f"from {short_date(recent.start)} to {short_date(end)}"
    far = short_date(recent.start - timedelta(90))
    cited = {e.id: e for e in (d, c, thin) + ((day,) if day else ())}
    out: list[Case] = []

    def add(kind, ok, text, ckind, ev, direction=None, about=metric):
        out.append(Case(kind, ok, claim(text, ckind, ev, about, direction), cited))

    # Values: the average, the highest, and a total where one means something.
    stats = d.stats
    for form in forms(metric, stats["mean"]):
        add(
            "true: average",
            True,
            f"Your average {name(metric)} {span} was {form}.",
            "value",
            [d],
        )
    add(
        "true: highest",
        True,
        f"Your highest {name(metric)} {span} was {format_level(metric, stats['max'])}.",
        "value",
        [d],
    )
    if metric in ADDITIVE and "total" in stats:
        add(
            "true: total",
            True,
            f"Your total {name(metric)} {span} came to "
            f"{format_level(metric, stats['total'])}.",
            "value",
            [d],
        )

    mean = f"Your average {name(metric)} {span} was "
    add(
        "break: number 30% off",
        False,
        mean + wrong(metric, stats["mean"], 1.3) + ".",
        "value",
        [d],
    )
    add(
        "break: number 10% off",
        False,
        mean + wrong(metric, stats["mean"], 1.1) + ".",
        "value",
        [d],
    )
    if abs(stats["max"] - stats["mean"]) > 0.05 * abs(stats["mean"]):
        # A model's likely slip: the right evidence, the wrong statistic from it.
        add(
            "break: highest quoted as the average",
            False,
            mean + format_level(metric, stats["max"]) + ".",
            "value",
            [d],
        )
    add(
        "break: date outside",
        False,
        f"Your average {name(metric)} from {far} to "
        f"{short_date(end)} was {format_level(metric, stats['mean'])}.",
        "value",
        [d],
    )
    add(
        "break: wrong metric",
        False,
        f"Your average {name(other)} {span} was {format_level(metric, stats['mean'])}.",
        "value",
        [d],
        about=other,
    )
    add(
        "break: too little data",
        False,
        f"Your average {name(metric)} on "
        f"{short_date(end)} was {format_level(metric, thin.stats['mean'])}.",
        "value",
        [thin],
    )
    add(
        "break: causal wording",
        False,
        mean + format_level(metric, stats["mean"]) + ", due to a busier schedule.",
        "value",
        [d],
    )
    add(
        "break: medical wording",
        False,
        mean
        + format_level(metric, stats["mean"])
        + ", which can be a sign of insomnia.",
        "value",
        [d],
    )

    # A change, or none.
    s = c.stats
    if c.sufficient and s["p_value"] is not None and s["difference"]:
        up = s["difference"] > 0
        then, now = (
            format_level(metric, s["mean_baseline"]),
            format_level(metric, s["mean_recent"]),
        )
        size = duration(abs(s["difference"])) if metric.endswith("_minutes") else None
        move, back = ("rose", "fell") if up else ("fell", "rose")
        text = (
            f"Your {name(metric)} {move} from {then} to {now} over the last {DAYS} days, "
            f"against the {DAYS} days before."
        )
        direction, flipped = ("up", "down") if up else ("down", "up")
        if s["p_value"] < ALPHA:
            add("true: change", True, text, "change", [c], direction)
            if size:
                add(
                    "true: change",
                    True,
                    f"Your {name(metric)} {move} by {size} a day over the "
                    f"last {DAYS} days.",
                    "change",
                    [c],
                    direction,
                )
            add(
                "break: reversed direction",
                False,
                text.replace(move, back, 1).replace(
                    f"from {then} to {now}", f"from {now} to {then}"
                ),
                "change",
                [c],
                flipped,
            )
            add(
                "break: wording against direction",
                False,
                text.replace(move, back, 1),
                "change",
                [c],
                direction,
            )
            add(
                "break: says no change",
                False,
                f"Your {name(metric)} held steady over the last {DAYS} days.",
                "no_change",
                [c],
            )
        else:
            add(
                "true: no change",
                True,
                f"Your {name(metric)} held steady: {then} in the "
                f"{DAYS} days before and {now} in the last {DAYS}.",
                "no_change",
                [c],
            )
            add("break: change not significant", False, text, "change", [c], direction)

    # One day against the usual range.
    if day and day.sufficient and "position" in day.stats:
        st = day.stats
        position = st["position"]
        value, low, high = (
            format_level(metric, st[k]) for k in ("value", "usual_low", "usual_high")
        )
        where = {"above": "above", "below": "below", "within": "within"}[position]
        text = (
            f"On {short_date(end)}, your {name(metric)} was {value}, {where} your usual "
            f"range of {low} to {high}."
        )
        direction = {"above": "up", "below": "down", "within": None}[position]
        add("true: day", True, text, "day", [day], direction)
        if position != "within":
            opposite = "below" if position == "above" else "above"
            add(
                "break: day on the wrong side",
                False,
                text.replace(where, opposite, 1),
                "day",
                [day],
                "down" if direction == "up" else "up",
            )
        add(
            "break: number 30% off",
            False,
            f"On {short_date(end)}, your {name(metric)} was "
            f"{wrong(metric, st['value'], 1.3)}.",
            "day",
            [day],
            direction,
        )
    return out


def reason_kind(reason: str) -> str:
    """A rejection's reason without the values in it, so it can be printed and saved."""
    return re.split(r"[:;(]", reason, maxsplit=1)[0].strip()


def main() -> None:
    people = {f"pmdata/{k}": v for k, v in real_data.load_pmdata().items()} | {
        f"lifesnaps/{k}": v for k, v in real_data.load_lifesnaps().items()
    }
    cases: list[Case] = []
    used = set()
    for person, frame in people.items():
        for metric in METRICS:
            if metric in frame.columns and (found := cases_for(frame, metric)):
                cases += found
                used.add(person)

    tally: dict[str, Counter] = defaultdict(Counter)
    why_wrong: dict[str, Counter] = defaultdict(Counter)
    for case in cases:
        reasons = check_claim(case.claim, case.evidence)
        rejected = bool(reasons)
        right = rejected != case.ok
        tally[case.kind]["right" if right else "wrong"] += 1
        if not right:
            why_wrong[case.kind].update(
                [reason_kind(r) for r in reasons] if reasons else ["passed"]
            )

    rows = {
        kind: {
            "cases": sum(t.values()),
            "right": t["right"],
            "rate": round(t["right"] / sum(t.values()), 3),
            "when_wrong": dict(why_wrong[kind].most_common(4)),
        }
        for kind, t in sorted(tally.items())
    }
    true = [r for k, r in rows.items() if k.startswith("true")]
    broken = [r for k, r in rows.items() if k.startswith("break")]
    summary = {
        "people": len(used),
        "claims": len(cases),
        "true_claims_passed": round(
            sum(r["right"] for r in true) / sum(r["cases"] for r in true), 3
        ),
        "broken_claims_caught": round(
            sum(r["right"] for r in broken) / sum(r["cases"] for r in broken), 3
        ),
        "by_kind": rows,
    }
    SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY.write_text(json.dumps(summary, indent=1) + "\n")
    json.dump(summary, sys.stdout, indent=1)
    print()


if __name__ == "__main__":
    main()
