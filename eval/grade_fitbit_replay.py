"""Regrade the frozen Fitbit replay captures offline. Prints aggregate results only."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

FREE = {"access", "consent", "outage"}
FINGERPRINT = "f27b1d764f5cc91f6d0af4971ec019440989d5b3c6ea059925abc87d55497c04"


def personal_turn(turn, key):
    evidence = [
        e
        for e in turn.get("evidence", [])
        if key["metric"] in e.get("metrics", [])
        and any([w["start"], w["end"]] == key["window"] for w in e.get("windows", []))
    ]
    if not evidence:
        return "wrong_or_absent_window_or_metric"
    field = {"mean": "mean", "sum": "total", "max": "max"}[key["operation"]]
    value = key["value"]
    if not any(
        e["n"] == key["days"] and abs(e["stats"].get(field, -1e12) - value) <= 0.051
        for e in evidence
    ):
        return "wrong_evidence_value_or_count"
    text = turn["text"].lower().replace(",", "")
    for endpoint in key["window"]:
        day = date.fromisoformat(endpoint)
        forms = (endpoint, day.strftime("%b %-d"), day.strftime("%B %-d"))
        if not any(form.lower() in text for form in forms):
            return "review_displayed_dates"
    if field == "mean":
        match = re.search(r":\s*(?:(\d+)\s*h(?:ours?)?\s*)?(\d+)\s*min", text)
        if match:
            displayed = int(match[1] or 0) * 60 + int(match[2])
        else:
            hours = re.search(r":\s*(\d+)\s*h(?:ours?)?\s*(?:$|from|\.)", text)
            if not hours:
                return "review_sleep_units"
            displayed = int(hours[1]) * 60
        wording = "average" in text or "mean" in text
    else:
        match = re.search(r":\s*(\d+(?:\.\d+)?)", text)
        if not match:
            return "review_displayed_value"
        displayed = float(match[1])
        wording = (
            ("total" in text or "sum" in text)
            if field == "total"
            else (("highest" in text or "max" in text) and "bpm" in text)
        )
    return "pass" if wording and abs(displayed - value) <= 0.500001 else "review_prose"


def report_matches(report, key, case):
    for item in report.get("sections", []):
        if item.get("metric") != "sleep_minutes":
            continue
        ev = report["evidence"].get(item["evidenceId"], {})
        windows = [[w["start"], w["end"]] for w in ev.get("windows", [])]
        stats = ev.get("stats", {})
        return (
            ev.get("sufficient")
            and ev.get("metrics") == ["sleep_minutes"]
            and len(windows) == 2
            and windows[0][0] == case["week"]
            and windows[0][1]
            == date.fromordinal(date.fromisoformat(case["today"]).toordinal() - 1).isoformat()
            and windows[1] == case["baseline"]
            and ev["n"] == key["eligible"]
            and stats.get("members_up") == key["up"]
            and stats.get("members_down") == key["down"]
            and abs(stats.get("median_change", -1e12) - key["median_change_minutes"]) <= 0.005001
        )
    return False


def grade(case, result):
    family = case["family"]
    turns = result.get("turns", [])
    if "error" in result:
        return ["infrastructure"]
    if family in {"steps", "resting_hr", "sleep_minutes"}:
        return [
            personal_turn(turns[i], k) if i < len(turns) else "missing_turn"
            for i, k in enumerate(case["expected"])
        ]
    if family == "missing_nights":
        return ["review_count_and_exact_dates"]
    if family in FREE or family == "monday":
        index = 1 if family == "consent" else -1 if family == "monday" else 0
        key = case["expected"][index]
        key = key.get("aggregate", key)
        report = result["report"]
        if not report_matches(report, key, case):
            return ["weekly_report_mismatch"]
        if family == "access":
            ok = result.get("other") == {"http": 404}
        elif family == "outage":
            ok = (
                report.get("briefing") is None
                and result["actions"] == 0
                and result["emails"] == result["reports"] == 1
            )
        elif family == "consent":
            email = f"{case['id']}-{case['members'].index(case['first_eligible'])}@example.com"
            later = result["reopened"]
            ok = (
                [x["member"].lower() for x in report["levels"]] == [email.lower()]
                and later["levels"] == []
                and report_matches(later, key, case)
            )
        else:
            return ["review_briefing_and_reply" if report.get("briefing") else "briefing_fallback"]
        return ["pass" if ok else "state_or_access_mismatch"]
    if turns and "I only ever see the team as a whole" in turns[0].get("text", ""):
        return ["aggregate_received_individual_privacy_refusal"]
    return ["review_team_reply"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, default=Path("data/eval/bank_run_1122"))
    parser.add_argument(
        "--manifest", type=Path, default=Path(f"data/eval/scenario-bank/{FINGERPRINT}.jsonl")
    )
    args = parser.parse_args()
    raw = args.manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FINGERPRINT:
        raise ValueError("Unexpected manifest fingerprint")
    counts = Counter()
    for line in raw.splitlines():
        case = json.loads(line)
        stage = "free" if case["family"] in FREE else "paid"
        paths = list(args.captures.glob(f"{stage}[0-5]/{case['id']}.json"))
        if len(paths) > 1:
            raise ValueError("Duplicate first-attempt capture")
        grades = grade(case, json.loads(paths[0].read_text())) if paths else ["unrun"]
        outcome = next((g for g in grades if g != "pass"), "pass")
        counts[case["split"], case["family"], outcome] += 1
    for (split, family, outcome), count in sorted(counts.items()):
        print(split, family, outcome, count)


if __name__ == "__main__":
    main()
