"""Reads the independently worded bank (eval/fresh_bank.py) on two versions and scores each family.

Reader only. The expected reading comes from each case, never from the generated text. Items
whose words do not match their case were excluded before any reading (EXCLUDED). Each family is
scored with a Wilson 95% interval, so a small difference is not read as a gain.

    PYTHONPATH=backend .venv/bin/python eval/fresh_bank_check.py freeze
    PYTHONPATH=<code>/backend .venv/bin/python eval/fresh_bank_check.py run --sha <sha> --label main
    PYTHONPATH=backend .venv/bin/python eval/fresh_bank_check.py score
"""

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

BANK = Path("data/eval/fresh_bank_2026-11-23/bank.json")
BANK_SHA = "c45b6af0676e451a1a17a605a570c155a4578a2ef05392c83c0c401879cd90e6"
OUT = Path("data/eval/fresh_bank_check_2026-11-23")
JOBS = OUT / "jobs.json"
CAP_USD = 1.10
TODAY = "2026-11-02"
WEEK = ["2026-10-12", "2026-10-18"]
DAY = ["2026-10-31", "2026-10-31"]
FIVE = (date(2026, 10, 12), date(2026, 10, 16))
# Asks for a breakdown of the data, not where it came from: judged before any reading.
EXCLUDED = {
    ("source_data", 1),
    ("source_data", 7),
    ("source_data", 8),
    ("source_data", 11),
}
UNSAVED_REPLY = (
    "Okay, I won't keep anything from this message, and nothing else about you is kept. I can "
    "still use what you said here, in this chat."
)
MEASURES = {
    "sleep": "sleep_minutes",
    "steps": "steps",
    "resting heart rate": "resting_hr",
}


def state(part: dict, last: str = "data") -> dict:
    return {
        "last": last,
        "data": [part],
        "answer": {"kind": last, "parts": 1, "reads": 0},
    }


PLANK = {
    "question": "How do I do a plank?",
    "answer": "Hold a straight line on your forearms and toes. From free-exercise-db.",
    "state": {"last": "guidance", "guidance": ["plank"]},
}
STEPS = {
    "question": "Total steps from 2026-10-19 to 2026-10-25?",
    "answer": "From Mon, Oct 19 to Sun, Oct 25, total steps: 61,204.",
    "state": state({"metrics": ["steps"], "operation": "sum",
                    "windows": [{"start": "2026-10-19", "end": "2026-10-25"}]}),
}  # fmt: skip
BREAKFAST = {
    "question": "Read confirmed breakfast energy for October 31, 2026.",
    "answer": "On Sat, Oct 31 you logged 1 entry. Energy consumed: 327 kcal.",
    "state": state({"metrics": ["food_logs"], "operation": "food", "meal_type": "BREAKFAST",
                    "nutrients": ["energy"], "windows": [{"start": DAY[0], "end": DAY[1]}]}),
}  # fmt: skip
AVERAGE = {
    "question": "Average steps from 2026-10-12 to 2026-10-16?",
    "answer": "From Mon, Oct 12 to Fri, Oct 16, daily average steps: 8,210.",
    "state": state({"metrics": ["steps"], "operation": "mean",
                    "windows": [{"start": "2026-10-12", "end": "2026-10-16"}]}),
}  # fmt: skip


def period_days(spec: dict) -> list[str]:
    anchor = FIVE[0] if spec["counted_from"] == "its_first_day" else FIVE[1]
    day = anchor + timedelta(days=spec["days_after"])
    rest = timedelta(days=spec["length"] - 1)
    start, end = (day, day + rest) if spec["role"] == "begins" else (day - rest, day)
    return [start.isoformat(), end.isoformat()]


def job(family: str, i: int, item: dict) -> dict | None:
    q = item["question"].replace("{start}", WEEK[0]).replace("{end}", WEEK[1])
    base = {"id": f"{family}-{i}", "family": family, "question": q}
    if family in ("recall_unsaved", "recall_plain"):
        reply = (
            UNSAVED_REPLY if family == "recall_unsaved" else "Thanks for telling me."
        )
        before = {"question": item["before"], "answer": reply, "state": {}}
        return base | {"before": before, "want": {"recall": ["this_chat", "all"]}}
    if family == "recall_kept":
        return base | {"before": None, "want": {"recall": ["kept", "waiting", "all"]}}
    if family.startswith("source"):
        before = STEPS if family == "source_data" else PLANK
        return base | {
            "before": before,
            "want": {"source": family != "source_negative"},
        }
    if family == "coverage":
        want = {"parts": [[[MEASURES[item["measure"]]], "coverage", [WEEK]]]}
        return base | {"before": None, "want": want}
    if family == "coverage_negative":
        return base | {"before": None, "want": {"not_one_measure": True}}
    if family == "food":
        want = {
            "keep_meal": {"food": [item["nutrient"]], "meal": "BREAKFAST"},
            "all_meals": {"food": [item["nutrient"]], "meal": None},
            "burned": {"parts": [[["calories"], "value", [DAY]]]},
        }[item["kind"]]
        return base | {"before": BREAKFAST, "want": want, "kind": item["kind"]}
    if family == "periods":
        return base | {
            "before": AVERAGE,
            "want": {"parts": [[["steps"], "mean", [period_days(item)]]]},
        }
    return None


def freeze() -> None:
    raw = BANK.read_text()
    if hashlib.sha256(raw.encode()).hexdigest() != BANK_SHA:
        raise ValueError("The bank changed since it was generated")
    bank = json.loads(raw)
    jobs = [
        made
        for family, items in bank.items()
        for i, item in enumerate(items)
        if (family, i) not in EXCLUDED and (made := job(family, i, item))
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"cap_usd": CAP_USD, "jobs": jobs}, sort_keys=True, indent=1)
    JOBS.write_text(body)
    print(f"{len(jobs)} readings frozen {dict(Counter(j['family'] for j in jobs))}")
    print(
        f"cap ${CAP_USD} per version; sha256 {hashlib.sha256(body.encode()).hexdigest()}"
    )


def run(sha: str, label: str) -> None:
    from app.agent.context import Turn
    from app.agent.llm import OpenAILLM, SpendLedger
    from app.agent.requests import interpret
    from app.config import settings

    body = JOBS.read_text()
    if hashlib.sha256(body.encode()).hexdigest() != sha:
        raise ValueError("The frozen jobs changed since they were approved")
    out = OUT / f"{label}.jsonl"
    if out.exists():
        raise ValueError(
            f"{out} exists: a finished run is never rerun for a higher mark"
        )
    frozen = json.loads(body)
    ledger = SpendLedger(cap_usd=frozen["cap_usd"])
    llm = OpenAILLM.from_settings(settings, ledger)
    with out.open("w") as rows:
        for item in frozen["jobs"]:
            if ledger.spent_usd >= frozen["cap_usd"]:
                print("Stopped at the cap.")
                break
            b = item["before"]
            history = (
                [Turn(b["question"], b["answer"], request_state=b["state"])]
                if b
                else []
            )
            request, _, budget = interpret(
                llm,
                item["question"],
                history,
                date.fromisoformat(TODAY),
                keep_readings=True,
            )
            row = {"id": item["id"], "request": request.model_dump(mode="json")}
            rows.write(
                json.dumps(row | {"cost_usd": budget.cost_usd}, default=str) + "\n"
            )
    print(f"{label}: ${ledger.spent_usd:.6f} spent")


def right(want: dict, r: dict) -> bool:
    parts = r.get("parts", [])
    shape = [
        [p["metrics"], p["operation"], [[w["start"], w["end"]] for w in p["windows"]]]
        for p in parts
    ]
    if "recall" in want:
        return (
            r.get("kind") == "memory"
            and r.get("memory_action") == "recall"
            and r.get("recall") in want["recall"]
        )
    if "source" in want:
        return (r.get("kind") == "source") is want["source"]
    if "not_one_measure" in want:
        return not (
            r.get("kind") == "data"
            and len(parts) == 1
            and len(parts[0]["metrics"]) == 1
        )
    if "food" in want:
        return (
            r.get("kind") == "data"
            and len(parts) == 1
            and parts[0]["operation"] == "food"
            and parts[0].get("nutrients") == want["food"]
            and parts[0].get("meal_type") == want["meal"]
            and shape[0][2] == [DAY]
        )
    return r.get("kind") in ("data", "causality") and shape == want["parts"]


def wilson(k: int, n: int) -> str:
    if not n:
        return "-"
    p, z = k / n, 1.96
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return f"{max(0, centre - half):.0%}-{min(1, centre + half):.0%}"


def score() -> None:
    jobs = {j["id"]: j for j in json.loads(JOBS.read_text())["jobs"]}
    runs = {
        p.stem: [json.loads(x) for x in p.read_text().splitlines()]
        for p in sorted(OUT.glob("*.jsonl"))
    }
    families = list(dict.fromkeys(j["family"] for j in jobs.values()))
    print(f"{'family':18}" + "".join(f"{label:>24}" for label in runs))
    for family in families:
        line = f"{family:18}"
        for rows in runs.values():
            got = [
                right(jobs[r["id"]]["want"], r["request"])
                for r in rows
                if jobs[r["id"]]["family"] == family
            ]
            line += f"{sum(got):>6}/{len(got):<3} ({wilson(sum(got), len(got)):>9})    "
        print(line)
    for label, rows in runs.items():
        print(f"{label}: {len(rows)} read, ${sum(r['cost_usd'] for r in rows):.6f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    paid = sub.add_parser("run")
    paid.add_argument("--sha", required=True)
    paid.add_argument("--label", required=True)
    sub.add_parser("score")
    args = parser.parse_args()
    if args.command == "freeze":
        freeze()
    elif args.command == "run":
        run(args.sha, args.label)
    else:
        score()


if __name__ == "__main__":
    main()
