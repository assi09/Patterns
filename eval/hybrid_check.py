"""The hybrid against no experts, and the fixes against the code before them, on fresh questions.

Hybrid: an expert answers inside its own area; a why question, or one spanning areas, goes to the
general agent with every metric and the experts' notes. Run from the repository root:
`PYTHONPATH=backend:eval python eval/hybrid_check.py`. It pays; `--stop` caps it.

`--causes-only --systems pipeline --tag _before` with PYTHONPATH pointing at a checkout of the code
before the fixes measures the same cause questions on it, so the fixes are compared question by
question. The question types and how each right answer is decided are in docs/evaluation.md.
"""

import argparse
import glob
import json
import random
from pathlib import Path

import decide_experts as base
import phia
import real_data
import real_eval
import real_regrade
import three_systems

from app.agent.ask import default_guard, default_router
from app.agent.llm import OpenAILLM
from app.config import settings

SEED = 2027
NO_HRV_CAUSE = {
    "name": "hrv_with_no_cause",
    "q": "Why has my HRV dropped lately?",
    "cause": "none",
    "driver": None,
    "target": ("hrv_ms", -1.5),
    "crosses_areas": False,
}
CAUSES = (*base.CAUSES, NO_HRV_CAUSE)
PER_CASE = {case["name"]: 7 for case in CAUSES} | {
    "resting_hr_with_no_cause": 6,
    "hrv_with_no_cause": 6,
}
OUT = Path("data/eval/results")


def asked_before() -> set:
    paths = glob.glob("data/eval/results/real_eval_*_full.jsonl") + [
        p for p in glob.glob("data/eval/results/decide_experts_*.jsonl") if "try" not in p
    ]
    return {(r["person"], r["kind"], r["q"]) for p in paths for r in map(json.loads, open(p))}


def data_questions(people: dict) -> list[dict]:
    real_eval.SEED, real_eval.PER_PERSON = SEED, 16
    old = asked_before()
    rng = random.Random(SEED)
    pool: dict[str, list[dict]] = {kind: [] for kind in base.QUOTAS}
    seen = set()
    for name, frame in sorted(people.items()):
        for item in real_eval.questions_for(name, frame):
            key = (item["person"], item["kind"], item["q"])
            if item["kind"] in pool and key not in old and key not in seen:
                seen.add(key)
                pool[item["kind"]].append(item)
    found = []
    for kind, quota in base.QUOTAS.items():
        found += rng.sample(pool[kind], min(quota, len(pool[kind])))
    return [{**item, "set": "data"} for item in found]


def cause_questions(people: dict) -> list[dict]:
    """Fresh pairs: nobody gets a case they were given in the earlier test."""
    rng = random.Random(f"{SEED}:cause")
    used = {
        (r["person"], r["case"])
        for p in glob.glob("data/eval/results/decide_experts_*.jsonl")
        if "try" not in p
        for r in map(json.loads, open(p))
        if r.get("set") == "cause"
    }
    found = []
    for case in CAUSES:
        names = sorted(people)
        rng.shuffle(names)
        taken = 0
        for name in names:
            if taken == PER_CASE[case["name"]]:
                break
            if (name, case["name"]) not in used and base.planted_cause(
                people[name], case
            ) is not None:
                taken += 1
                found.append(
                    {
                        "set": "cause",
                        "kind": case["name"],
                        "person": name,
                        "q": case["q"],
                        "cause": case["cause"],
                        "crosses_areas": case["crosses_areas"],
                        "case": case["name"],
                    }
                )
    return found


def frame_for(item: dict, people: dict):
    if item["set"] == "cause":
        case = next(c for c in CAUSES if c["name"] == item["case"])
        return base.planted_cause(people[item["person"]], case)
    if item["frame_kind"] == "planted":
        seed = f"{SEED}:{item['person']}:plant"
        return real_eval.plant(people[item["person"]], item["metric"], random.Random(seed))[0]
    return people[item["person"]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", type=float, default=2.0)
    parser.add_argument("--systems", default="experts,pipeline", help="experts = the hybrid")
    parser.add_argument("--causes-only", action="store_true")
    parser.add_argument("--tag", default="")
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args()
    systems = tuple(options.systems.split(","))
    people = real_data.load_pmdata() | real_data.choose_lifesnaps(real_data.load_lifesnaps())
    items = cause_questions(people)
    if not options.causes_only:
        items += data_questions(people)
    random.Random(SEED).shuffle(items)
    counts: dict[str, int] = {}
    for item in items:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    print("questions:", len(items), dict(sorted(counts.items())))
    print("people:", len({i["person"] for i in items}))
    if options.dry_run:
        return
    llm = OpenAILLM.from_settings(settings)
    router, guard = default_router(settings), default_guard(settings)
    spent, rows = [0.0], []
    path = OUT / f"hybrid_check_{real_eval.STAMP}{options.tag}.jsonl"
    with path.open("w") as file:
        for item in items:
            if spent[0] >= options.stop:
                print("Stopped at the spending limit.")
                break
            row = dict(item)
            frame = frame_for(item, people)
            for name in systems:
                try:
                    done = phia.run_one(name, llm, router, guard, item, frame, spent)
                    if item["set"] == "cause":
                        done["cause_read"] = three_systems.read_cause(
                            llm, item["q"], done["answer"], spent
                        )
                        done["correct"] = done["cause_read"] == item["cause"]
                    else:
                        done["correct"] = real_regrade.regraded(
                            item, done["answer"], done["read"], done["stop"] == "refused"
                        )
                except Exception as error:
                    print("failed:", name, type(error).__name__, str(error)[:150])
                    done = {"error": type(error).__name__}
                row[name] = done
            rows.append(row)
            file.write(json.dumps(row, default=str) + "\n")
            file.flush()
            print(f"${spent[0]:.3f} {item['kind']}", *(row[n].get("correct") for n in systems))
    print("spent", round(spent[0], 3), "answers", len(rows))


if __name__ == "__main__":
    main()
