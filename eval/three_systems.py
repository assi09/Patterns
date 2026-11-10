"""Three systems on the same questions, so each part's contribution can be seen on its own.

- experts: the app as it is, with routing, experts and consults.
- pipeline: the same app with no experts, every question going to the general agent.
- general: a bare agent with every tool, no routing, no question-type plan and no automatic RAG.

experts against pipeline shows what the experts add; pipeline against general what the rest adds.
On top of PHIA's questions (`eval/phia.py`) come "why" questions on synthetic people with a planted
cause, where experts should matter most and the right answer is known. The cause is read from each
reply by one extractor that sees neither the system nor the expected answer.
Run from the repository root: `PYTHONPATH=backend:eval python eval/three_systems.py`. It pays.
"""

import argparse
import csv
import json
import random
import statistics
from datetime import date, timedelta
from pathlib import Path

import oracle
import pandas as pd
import phia
import real_eval

from app.agent.ask import default_guard, default_router
from app.agent.llm import Budget, OpenAILLM
from app.config import settings
from app.synthetic import Coupling, Step, generate

SYSTEMS = ("experts", "pipeline", "general")
RESULTS = phia.RESULTS
STAMP = phia.STAMP
START, DAYS, SHIFT_AGO = date(2026, 6, 1), 90, 21
SEEDS = range(5)
CASES = (
    {
        "name": "hrv_after_short_sleep",
        "q": "Why has my HRV dropped lately?",
        "cause": "sleep_duration",
        "crosses_areas": True,
        "metrics": ("sleep_minutes", "hrv_ms"),
        "effects": lambda on: (
            Step("sleep_minutes", on, -80.0),
            Coupling("sleep_minutes", "hrv_ms", 0, 0.9),
        ),
    },
    {
        "name": "resting_hr_after_training",
        "q": "Why has my resting heart rate gone up lately?",
        "cause": "activity",
        "crosses_areas": True,
        "metrics": ("active_zone_minutes", "resting_hr"),
        "effects": lambda on: (
            Step("active_zone_minutes", on, 40.0),
            Coupling("active_zone_minutes", "resting_hr", 1, 0.9),
        ),
    },
    {
        "name": "sleep_after_late_bedtimes",
        "q": "Why am I sleeping less lately?",
        "cause": "bedtime",
        "crosses_areas": False,
        "metrics": ("bedtime_hour", "sleep_minutes"),
        "effects": lambda on: (
            Step("bedtime_hour", on, 1.6),
            Coupling("bedtime_hour", "sleep_minutes", 0, -0.9),
        ),
    },
    {
        "name": "hrv_with_no_cause",
        "q": "Why has my HRV dropped lately?",
        "cause": "none",
        "crosses_areas": False,
        "metrics": ("hrv_ms",),
        "effects": lambda on: (Step("hrv_ms", on, -14.0),),
    },
)
READ_CAUSE = """Read one reply to a person asking why something in their fitness data changed. Return
JSON only: {"cause": X}, where X is what the reply presents as linked to or behind the change:
"sleep_duration" (less time asleep), "bedtime" (going to bed at a different time), "activity"
(training, exercise, steps), "none" (it found nothing that explains it, or only says the change
happened), or "other"."""


def scenario(case: dict, seed: int) -> pd.DataFrame:
    on = START + timedelta(days=DAYS - SHIFT_AGO)
    frame = generate(START, DAYS, case["effects"](on), seed=seed + 100).frame
    return frame


def planted_check() -> dict:
    """Free: the planted changes have to be real, or the question has no right answer."""
    found = {}
    for case in CASES:
        hits = []
        for seed in SEEDS:
            frame = scenario(case, seed)
            target = case["metrics"][-1]
            hits.append(
                oracle.change(frame, target, frame.index.max(), SHIFT_AGO, 28) in ("up", "down")
            )
        found[case["name"]] = sum(hits)
    return found


def read_cause(llm, question: str, reply: str, spent: list[float]) -> str | None:
    budget = Budget(max_calls=1, max_cost_usd=0.005)
    try:
        done = llm.complete(
            [
                {"role": "system", "content": READ_CAUSE},
                {"role": "user", "content": f"Question: {question}\nReply: {reply}"},
            ],
            budget=budget,
        )
        spent[0] += budget.cost_usd
        raw = done.text or "{}"
        return json.loads(raw[raw.index("{") : raw.rindex("}") + 1]).get("cause")
    except Exception:
        return None


def why_questions(llm, router, guard, spent: list[float], stop: float) -> list[dict]:
    items = [(case, seed) for case in CASES for seed in SEEDS]
    random.Random(phia.SEED).shuffle(items)
    rows = []
    with (RESULTS / f"why_answers_{STAMP}.jsonl").open("w") as file:
        for case, seed in items:
            if spent[0] >= stop:
                break
            row = {k: case[k] for k in ("name", "q", "cause", "crosses_areas")} | {
                "seed": seed,
                "set": "why",
            }
            frame = scenario(case, seed).drop(columns=["readiness"], errors="ignore")
            for name in SYSTEMS:
                try:
                    done = phia.run_one(name, llm, router, guard, row, frame, spent)
                    done["cause_read"] = read_cause(llm, case["q"], done["answer"], spent)
                    done["correct"] = done["cause_read"] == case["cause"]
                except Exception as error:
                    print("failed:", name, type(error).__name__, str(error)[:150])
                    done = {"error": type(error).__name__}
                row[name] = done
            rows.append(row)
            file.write(json.dumps(row, default=str) + "\n")
            file.flush()
            print(f"${spent[0]:.3f} why {case['name']}", *(row[n].get("correct") for n in SYSTEMS))
    return rows


def third_system(llm, router, guard, spent: list[float], stop: float) -> list[dict]:
    """The no-expert pipeline on the questions the other two already answered."""
    path = RESULTS / f"phia_answers_{STAMP}.jsonl"
    rows = [json.loads(line) for line in path.open()]
    frames = {user: phia.person(user) for user in phia.USERS}
    for row in rows:
        if spent[0] >= stop:
            print("Stopped at the spending limit.")
            break
        try:
            row["pipeline"] = phia.run_one(
                "pipeline", llm, router, guard, row, frames[row["user"]], spent
            )
        except Exception as error:
            print("failed: pipeline", type(error).__name__, str(error)[:150])
            row["pipeline"] = {"error": type(error).__name__}
            if "quota" in str(error).lower() or "credit" in str(error).lower():
                break
        print(f"${spent[0]:.3f} {row['set']} pipeline={row['pipeline'].get('correct')}")
    path.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))
    return rows


def complete(row: dict) -> bool:
    return all("answer" in row.get(name, {}) for name in SYSTEMS)


def compare(group: list[dict], key: str = "correct") -> dict:
    hits = {n: [bool(r[n].get(key)) for r in group] for n in SYSTEMS}
    return {
        **{n: phia.rate(hits[n]) for n in SYSTEMS},
        "experts_vs_pipeline": _pair(hits["experts"], hits["pipeline"]),
        "pipeline_vs_general": _pair(hits["pipeline"], hits["general"]),
        "experts_vs_general": _pair(hits["experts"], hits["general"]),
    }


def _pair(first: list[bool], second: list[bool]) -> dict:
    result = phia.paired(first, second)
    return {
        "only_first_right": result["only_experts_right"],
        "only_second_right": result["only_general_right"],
        "p": result["p"],
    }


def detail(group: list[dict]) -> dict:
    out = {}
    for name in SYSTEMS:
        items = [r[name] for r in group]
        out[name] = {
            "cost_per_answer": round(statistics.mean(i["cost"] for i in items), 5)
            if items
            else None,
            "calls_per_answer": round(statistics.mean(i["calls"] for i in items), 2)
            if items
            else None,
            "fallback_replies": sum("pin that down" in i["answer"] for i in items),
            "ran_out_of_budget": sum(i["stop"] == "budget" for i in items),
            "refused": sum(i["stop"] == "refused" for i in items),
            "medical_words": sum(i["medical"] for i in items),
        }
    return out


def blind_sheet(rows: list[dict]) -> None:
    """Three answers each to 17 open questions, shuffled and unlabeled: 51 to grade."""
    opened = [r for r in rows if r["set"] == "open" and complete(r)]
    rng = random.Random(f"{phia.SEED}:blind3")
    sheet = [(r, n) for r in rng.sample(opened, min(17, len(opened))) for n in SYSTEMS]
    rng.shuffle(sheet)
    with (RESULTS / f"phia_blind_{STAMP}.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            ["id", "question", "answer", "correct_1_to_5", "useful_1_to_5", "clear_1_to_5", "notes"]
        )
        for at, (row, name) in enumerate(sheet, 1):
            writer.writerow([at, row["q"], row[name]["answer"], "", "", "", ""])
    key = {at: name for at, (_, name) in enumerate(sheet, 1)}
    (RESULTS / f"phia_blind_key_{STAMP}.json").write_text(json.dumps(key, indent=0))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", type=float, default=1.3)
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args()
    print("planted changes found, of 5 each:", planted_check())
    if options.dry_run:
        return
    llm = OpenAILLM.from_settings(settings)
    router, guard = default_router(settings), default_guard(settings)
    spent = [0.0]
    why = why_questions(
        llm, router, guard, spent, options.stop
    )  # first: where experts should matter
    rows = third_system(llm, router, guard, spent, options.stop)
    done = [r for r in rows if complete(r)]
    exact = [r for r in done if r["set"] == "exact"]
    whys = [r for r in why if complete(r)]
    summary = {
        "spent_usd": round(spent[0], 3),
        "exact_questions_with_all_three": len(exact),
        "open_questions_with_all_three": sum(r["set"] == "open" for r in done),
        "exact_strict": compare(exact),
        "exact_fair": compare(exact, "correct_fair"),
        "why_all": compare(whys),
        "why_crossing_areas": compare([r for r in whys if r["crosses_areas"]]),
        "why_within_one_area": compare(
            [r for r in whys if not r["crosses_areas"] and r["cause"] != "none"]
        ),
        "why_no_cause_planted": compare([r for r in whys if r["cause"] == "none"]),
        "how_each_system_ran": {
            "exact": detail(exact),
            "open": detail([r for r in done if r["set"] == "open"]),
            "why": detail(whys),
        },
    }
    Path(RESULTS / f"three_systems_{STAMP}.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    blind_sheet(rows)


if __name__ == "__main__":
    main()
