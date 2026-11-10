"""Should the experts stay? Separated experts against the same app with no experts, on real people.

Real Fitbit histories from PMData and LifeSnaps, with the questions the app is for: has it changed,
do these go together, is the weekend different, and why did it change, with a known cause planted
in the real series. The questions are drawn afresh, leaving out any asked before.

The rule was fixed before this ran. The experts stay only if they are as accurate as no experts on
data questions and on causes, cost at most 10% more, and are clearly better at something.
Run from the repository root: `PYTHONPATH=backend:eval python eval/decide_experts.py`. It pays.
Answers stay in the git-ignored `data/eval/results`, because these are real people; totals are
committed. Whole-agent behaviour (logging, memory, follow-ups) is `agent_eval.py --no-experts`.
"""

import argparse
import glob
import json
import random
import statistics
from pathlib import Path

import oracle
import phia
import real_data
import real_eval
import real_regrade
import three_systems

from app.agent.ask import default_guard, default_router
from app.agent.llm import OpenAILLM
from app.config import settings

SEED = 2026
SYSTEMS = ("experts", "pipeline")
QUOTAS = {"change": 18, "link": 16, "weekend": 12, "planted": 14, "planted_control": 10}
PER_CAUSE = 6
RECENT = 21
OUT = Path("data/eval/results")
CAUSES = (
    {
        "name": "hrv_after_short_sleep",
        "q": "Why has my HRV dropped lately?",
        "cause": "sleep_duration",
        "driver": ("sleep_minutes", -1.8),
        "target": ("hrv_ms", -1.3),
        "crosses_areas": True,
    },
    {
        "name": "resting_hr_after_training",
        "q": "Why has my resting heart rate gone up lately?",
        "cause": "activity",
        "driver": ("active_zone_minutes", 1.8),
        "target": ("resting_hr", 1.3),
        "crosses_areas": True,
    },
    {
        "name": "resting_hr_after_short_sleep",
        "q": "Why has my resting heart rate gone up lately?",
        "cause": "sleep_duration",
        "driver": ("sleep_minutes", -1.8),
        "target": ("resting_hr", 1.3),
        "crosses_areas": True,
    },
    {
        "name": "sleep_after_late_bedtimes",
        "q": "Why am I sleeping less lately?",
        "cause": "bedtime",
        "driver": ("bedtime_hour", 1.8),
        "target": ("sleep_minutes", -1.3),
        "crosses_areas": False,
    },
    {
        "name": "resting_hr_with_no_cause",
        "q": "Why has my resting heart rate gone up lately?",
        "cause": "none",
        "driver": None,
        "target": ("resting_hr", 1.5),
        "crosses_areas": False,
    },
)


def way(shift: float) -> str:
    return "up" if shift > 0 else "down"


def shifted(frame, metric: str, sds: float):
    """The series moved by `sds` of its own earlier spread over the last days: real noise stays."""
    recent = frame.index > frame.index.max() - real_eval.pd.Timedelta(days=RECENT)
    spread = float(frame.loc[~recent, metric].std())
    copy = frame.copy()
    copy.loc[recent, metric] = copy.loc[recent, metric] + sds * spread
    return copy


def planted_cause(frame, case: dict):
    """The frame with the cause planted, or None if a person's data cannot give a sound answer."""
    end = frame.index.max()
    target, target_sds = case["target"]
    used = [target, *([case["driver"][0]] if case["driver"] else [])]
    if any(m not in frame or frame[m].iloc[-RECENT:].notna().sum() < 10 for m in used):
        return None
    copy = shifted(frame, target, target_sds)
    if oracle.change(copy, target, end, RECENT, 28) != way(target_sds):
        return None
    if case["driver"]:
        driver, driver_sds = case["driver"]
        copy = shifted(copy, driver, driver_sds)
        if oracle.change(copy, driver, end, RECENT, 28) != way(driver_sds):
            return None
    else:  # "nothing explains it" must be true of the things a reply would name
        for other in ("sleep_minutes", "active_zone_minutes", "bedtime_hour"):
            if other in copy and oracle.change(copy, other, end, RECENT, 28) not in ("none", None):
                return None
    return copy


def data_questions(people: dict) -> list[dict]:
    real_eval.SEED, real_eval.PER_PERSON = SEED, 16
    asked = {
        (r["person"], r["kind"], r["q"])
        for path in glob.glob("data/eval/results/real_eval_*_full.jsonl")
        for r in map(json.loads, open(path))
    }
    rng = random.Random(SEED)
    pool: dict[str, list[dict]] = {kind: [] for kind in QUOTAS}
    for name, frame in sorted(people.items()):
        for item in real_eval.questions_for(name, frame):
            if item["kind"] in pool and (item["person"], item["kind"], item["q"]) not in asked:
                pool[item["kind"]].append(item)
    found = []
    for kind, quota in QUOTAS.items():
        seen, unique = set(), []
        for item in pool[kind]:
            key = (item["person"], item["q"])
            if key not in seen:
                seen.add(key)
                unique.append(item)
        found += rng.sample(unique, min(quota, len(unique)))
    return [{**item, "set": "data"} for item in found]


def cause_questions(people: dict) -> list[dict]:
    rng = random.Random(f"{SEED}:cause")
    names = sorted(people)
    found = []
    for case in CAUSES:
        rng.shuffle(names)
        taken = 0
        for name in names:
            if taken == PER_CAUSE:
                break
            if planted_cause(people[name], case) is not None:
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
    frame = people[item["person"]]
    if item["set"] == "cause":
        case = next(c for c in CAUSES if c["name"] == item["case"])
        return planted_cause(frame, case)
    if item["frame_kind"] == "planted":
        seed = f"{SEED}:{item['person']}:plant"
        return real_eval.plant(frame, item["metric"], random.Random(seed))[0]
    return frame


def complete(row: dict) -> bool:
    return all("answer" in row.get(name, {}) for name in SYSTEMS)


def compare(group: list[dict]) -> dict:
    hits = {n: [bool(r[n].get("correct")) for r in group] for n in SYSTEMS}
    result = phia.paired(hits["experts"], hits["pipeline"])
    return {
        "experts": phia.rate(hits["experts"]),
        "no_experts": phia.rate(hits["pipeline"]),
        "only_experts_right": result["only_experts_right"],
        "only_no_experts_right": result["only_general_right"],
        "p": result["p"],
    }


def ran(group: list[dict], name: str) -> dict:
    items = [r[name] for r in group]
    if not items:
        return {}
    return {
        "cost_per_answer": round(statistics.mean(i["cost"] for i in items), 5),
        "calls_per_answer": round(statistics.mean(i["calls"] for i in items), 2),
        "fallback_replies": sum("pin that down" in i["answer"] for i in items),
        "ran_out_of_budget": sum(i["stop"] == "budget" for i in items),
        "medical_words": sum(i["medical"] for i in items),
    }


def summarise(rows: list[dict], spent: float) -> dict:
    done = [r for r in rows if complete(r)]
    data = [r for r in done if r["set"] == "data"]
    cause = [r for r in done if r["set"] == "cause"]
    return {
        "spent_usd": round(spent, 3),
        "asked": len(rows),
        "failed_to_run": len(rows) - len(done),
        "data_questions": compare(data),
        "by_kind": {k: compare([r for r in data if r["kind"] == k]) for k in QUOTAS},
        "causes": compare(cause),
        "causes_crossing_areas": compare([r for r in cause if r["crosses_areas"]]),
        "causes_same_area": compare([r for r in cause if not r["crosses_areas"] and r["cause"] != "none"]),
        "causes_none_to_find": compare([r for r in cause if r["cause"] == "none"]),
        "how_each_ran": {n: ran(done, n) for n in SYSTEMS},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", type=float, default=1.85)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--tag", default="")
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args()
    people = real_data.load_pmdata() | real_data.choose_lifesnaps(real_data.load_lifesnaps())
    items = data_questions(people) + cause_questions(people)
    random.Random(SEED).shuffle(items)
    counts: dict[str, int] = {}
    for item in items:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    print("questions:", len(items), dict(sorted(counts.items())))
    print("people:", len({i["person"] for i in items}))
    if options.dry_run:
        return
    if options.limit:
        items = items[: options.limit]
    llm = OpenAILLM.from_settings(settings)
    router, guard = default_router(settings), default_guard(settings)
    spent, rows = [0.0], []
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"decide_experts_{real_eval.STAMP}{options.tag}.jsonl").open("w") as file:
        for item in items:
            if spent[0] >= options.stop:
                print("Stopped at the spending limit.")
                break
            row = dict(item)
            frame = frame_for(item, people)
            for name in SYSTEMS:
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
            print(f"${spent[0]:.3f} {item['kind']}", *(row[n].get("correct") for n in SYSTEMS))
    summary = summarise(rows, spent[0])
    (phia.RESULTS / f"decide_experts_{real_eval.STAMP}{options.tag}.json").write_text(
        json.dumps(summary, indent=1)
    )
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
