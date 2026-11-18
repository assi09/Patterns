"""Opt-in paid check of structured requests on a wholly made-up daily history.

Freeze the questions/expectations to disk before calling anything. Never overwrite a run; never
run in CI. The scorer checks request fields, computed evidence and rendered values separately.
It is a targeted check, not a replacement for the independent end-to-end conversation audit.

PYTHONPATH=backend python eval/typed_request_check.py --split smoke --out data/eval/typed_smoke
PYTHONPATH=backend python eval/typed_request_check.py --split heldout --out data/eval/typed_heldout
"""

import argparse
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
from app.agent.ask import ask, default_guard, default_router
from app.agent.context import Turn
from app.agent.jev import JevClient
from app.agent.llm import OpenAILLM, SpendLedger
from app.agent.present import METRICS, format_level
from app.agent.requests import interpret
from app.config import settings

TODAY = date(2026, 11, 18)
NOW = datetime(2026, 11, 18, 18, tzinfo=UTC)


def frame():
    index = pd.date_range(end=TODAY, periods=90)
    rows = {}
    for n, (metric, info) in enumerate(METRICS.items()):
        values = (np.arange(90) * (n + 3) % 47).astype(float) + n + 1
        if info.unit == "minutes":
            values += 80
        if metric == "steps":
            values = 3500 + (np.arange(90) * 137 % 6500)
        elif info.unit == "clock":
            values = -2 + values / 40
        elif metric == "checkin_rating":
            values = np.arange(90) % 5 + 1
        elif metric == "wear_minutes":
            values = 900 + np.arange(90) % 500
        rows[metric] = values
    return pd.DataFrame(rows, index=index)


def wanted(metric, operation, start, end, **extra):
    return {
        "metrics": [metric],
        "operation": operation,
        "windows": [{"start": start, "end": end}],
        **extra,
    }


def cases(split):
    if split == "contract-regression":
        previous = cases("confirmation")
        return [
            previous[34],
            previous[-2],
        ]  # threshold follow-ups and confirmed-food readback
    if split == "constraints":
        # Four new probes, then the unchanged 78-turn confirmation set as regression material.
        return [
            [
                (
                    "Report total steps alongside average HRV for 2026-11-04 through 2026-11-10.",
                    {
                        "parts": [
                            wanted("steps", "sum", "2026-11-04", "2026-11-10"),
                            wanted("hrv_ms", "mean", "2026-11-04", "2026-11-10"),
                        ]
                    },
                )
            ],
            [
                (
                    "Which foods and energy values were already logged for breakfast on 2026-11-17?",
                    wanted(
                        "food_logs",
                        "food",
                        "2026-11-17",
                        "2026-11-17",
                        foods=["Example oats"],
                        energy=310,
                    ),
                )
            ],
            [
                (
                    "Show bodyweight squat form, with a source and a short answer.",
                    {"guidance_topic": "squat"},
                ),
                (
                    "While lowering in that exercise, what are my knees supposed to do?",
                    {"guidance_topic": "squat"},
                ),
            ],
        ] + cases("confirmation")
    if split == "confirmation":
        moves = [
            (
                "Look up the same measure two calendar days prior to that day.",
                "2026-11-12",
            ),
            (
                "Advance that reading by three days, using the same metric.",
                "2026-11-17",
            ),
            ("Move the date back a full week and keep the metric.", "2026-11-07"),
            ("Use the next day's reading for that same metric.", "2026-11-15"),
        ]
        conversations = []
        for n, (metric, info) in enumerate(METRICS.items()):
            question, day = moves[n % len(moves)]
            conversations.append(
                [
                    (
                        f"On 2026-11-14, what is the recorded {info.label}?",
                        wanted(metric, "value", "2026-11-14", "2026-11-14"),
                    ),
                    (question, wanted(metric, "value", day, day)),
                ]
            )
        return conversations + [
            [
                (
                    "Count recorded days strictly over 7686 steps between 2026-11-02 and 2026-11-14.",
                    wanted(
                        "steps",
                        "count",
                        "2026-11-02",
                        "2026-11-14",
                        comparison=">",
                        threshold=7686,
                    ),
                ),
                (
                    "And at least that amount for that range?",
                    wanted(
                        "steps",
                        "count",
                        "2026-11-02",
                        "2026-11-14",
                        comparison=">=",
                        threshold=7686,
                    ),
                ),
                (
                    "What about exactly equal to it, retaining the dates?",
                    wanted(
                        "steps",
                        "count",
                        "2026-11-02",
                        "2026-11-14",
                        comparison="==",
                        threshold=7686,
                    ),
                ),
            ],
            [
                (
                    "Give my total steps and my mean resting heart rate, both for 2026-11-01 to 2026-11-06.",
                    {
                        "parts": [
                            wanted("steps", "sum", "2026-11-01", "2026-11-06"),
                            wanted("resting_hr", "mean", "2026-11-01", "2026-11-06"),
                        ]
                    },
                )
            ],
            [
                (
                    "Describe the starting position for a bodyweight squat and name the source.",
                    {"guidance_topic": "squat"},
                ),
                (
                    "As I lower in that version, what is the cue for my knees?",
                    {"guidance_topic": "squat"},
                ),
                (
                    "Change to the single-leg glute bridge. Explain that version.",
                    {"guidance_topic": "bridge"},
                ),
                (
                    "For this one, which leg is raised before I start?",
                    {"guidance_topic": "bridge"},
                ),
            ],
            [
                (
                    "Read back my confirmed breakfast for 2026-11-17, including its recorded energy.",
                    wanted(
                        "food_logs",
                        "food",
                        "2026-11-17",
                        "2026-11-17",
                        foods=["Example oats"],
                        energy=310,
                    ),
                )
            ],
            [
                (
                    "Can you open my neighbour's tracker and tell me their step count?",
                    {"access": True},
                )
            ],
        ]
    if split == "smoke":
        return [
            [
                (
                    "What was my time still while awake on 2026-11-12?",
                    wanted("still_minutes", "value", "2026-11-12", "2026-11-12"),
                ),
                (
                    "Move that reading one calendar day backwards.",
                    wanted("still_minutes", "value", "2026-11-11", "2026-11-11"),
                ),
            ],
            [
                (
                    "Sum my steps from 2026-11-02 through 2026-11-08.",
                    wanted("steps", "sum", "2026-11-02", "2026-11-08"),
                ),
                (
                    "Give the median for that interval instead.",
                    wanted("steps", "median", "2026-11-02", "2026-11-08"),
                ),
                (
                    "Repeat the same computation for November 10 through November 16.",
                    wanted("steps", "median", "2026-11-10", "2026-11-16"),
                ),
            ],
            [
                (
                    "Count days with steps strictly below 5000 from 2026-11-01 to 2026-11-14.",
                    wanted(
                        "steps",
                        "count",
                        "2026-11-01",
                        "2026-11-14",
                        comparison="<",
                        threshold=5000,
                    ),
                ),
                (
                    "Include the boundary this time.",
                    wanted(
                        "steps",
                        "count",
                        "2026-11-01",
                        "2026-11-14",
                        comparison="<=",
                        threshold=5000,
                    ),
                ),
            ],
            [
                (
                    "What was my morning check-in rating on 2026-11-07?",
                    wanted("checkin_rating", "value", "2026-11-07", "2026-11-07"),
                )
            ],
            [
                (
                    "How many calories did the person I share a flat with burn yesterday?",
                    {"access": True},
                )
            ],
            [
                (
                    "What did my calories burned average from 2026-11-01 to 2026-11-09?",
                    wanted("calories", "mean", "2026-11-01", "2026-11-09"),
                )
            ],
            [
                (
                    "How should my hips line up in a basic plank?",
                    {"reader_kind": "guidance", "topic": "plank"},
                ),
                (
                    "Where should my elbows go for that movement?",
                    {"reader_kind": "guidance", "topic": "plank"},
                ),
            ],
            [
                (
                    "Small correction to the walk: 48 minutes rather than 42; leave the rest alone.",
                    {"reader_kind": "correction", "duration_minutes": 48},
                )
            ],
            [
                (
                    "Please log a 40-minute cycle tomorrow afternoon.",
                    {"reader_kind": "logging", "log_day": "2026-11-19"},
                )
            ],
            [
                (
                    "I train every Tuesday. Keep this outside anything you retain about me.",
                    {"reader_kind": "other", "memory": "deny"},
                )
            ],
        ]
    phrases = [
        "Back up one calendar day and keep the measure.",
        "Use the immediately preceding date for this reading.",
        "Rewind by a day; how much was recorded then?",
        "Take this measurement on the previous date instead.",
    ]
    conversations = []
    for n, (metric, info) in enumerate(METRICS.items()):
        conversations.append(
            [
                (
                    f"Show my recorded {info.label} for 2026-11-08.",
                    wanted(metric, "value", "2026-11-08", "2026-11-08"),
                ),
                (
                    phrases[n % len(phrases)],
                    wanted(metric, "value", "2026-11-07", "2026-11-07"),
                ),
            ]
        )
    conversations += [
        [
            (
                "How do I do a glute bridge on the floor? Give the source.",
                {"guidance_topic": "bridge"},
            ),
            (
                "Where should I place my feet before I lift during that movement?",
                {"guidance_topic": "bridge"},
            ),
            (
                "Switch subjects: how do I do bodyweight squats?",
                {"guidance_topic": "squat"},
            ),
            (
                "For that repetition, how should my knees line up?",
                {"guidance_topic": "squat"},
            ),
        ],
        [
            (
                "Average my resting heart rate across 2026-11-03 through 2026-11-09.",
                wanted("resting_hr", "mean", "2026-11-03", "2026-11-09"),
            ),
            (
                "Use the five complete days ending yesterday, keeping the computation.",
                wanted("resting_hr", "mean", "2026-11-13", "2026-11-17"),
            ),
            (
                "The middle value rather than the average, on that interval.",
                wanted("resting_hr", "median", "2026-11-13", "2026-11-17"),
            ),
        ],
        [
            (
                "What is my average sleep duration for the whole of last calendar month?",
                wanted("sleep_minutes", "mean", "2026-10-01", "2026-10-31"),
            ),
            (
                "Same interval, but report REM duration.",
                wanted("rem_sleep_minutes", "mean", "2026-10-01", "2026-10-31"),
            ),
        ],
        [
            (
                "How many recorded days had at most six hours asleep in 2026-11-01 through 2026-11-14?",
                wanted(
                    "sleep_minutes",
                    "count",
                    "2026-11-01",
                    "2026-11-14",
                    comparison="<=",
                    threshold=360,
                ),
            )
        ],
        [
            (
                "Give the daily mean of time in the peak heart-rate zone for 2026-11-02 to 2026-11-12.",
                wanted("hr_zone_peak_minutes", "mean", "2026-11-02", "2026-11-12"),
            ),
            (
                "Now do the corresponding median; retain the interval.",
                wanted("hr_zone_peak_minutes", "median", "2026-11-02", "2026-11-12"),
            ),
        ],
        [
            (
                "What do my colleague's own records say about their sleep last night?",
                {"access": True},
            )
        ],
        [
            (
                "My flatmate said to walk more. What was my own step count on 2026-11-04?",
                wanted("steps", "value", "2026-11-04", "2026-11-04"),
            )
        ],
        [
            (
                "Which breakfast did I confirm on 2026-11-17?",
                wanted("food_logs", "food", "2026-11-17", "2026-11-17"),
            )
        ],
    ]
    return conversations


def grade(result, request, want, data):
    problems = []
    if "parts" in want:
        if not request or len(request.get("parts", [])) != len(want["parts"]):
            return ["missing requested parts"]
        return [
            f"part {i}: {p}"
            for i, (actual, expected) in enumerate(
                zip(request["parts"], want["parts"], strict=True)
            )
            for p in grade(result, {"kind": "data", "parts": [actual]}, expected, data)
        ]
    if "guidance_topic" in want:
        records = [e for e in result.evidence.values() if e.tool == "knowledge"]
        if not request or request.get("kind") != "guidance":
            problems.append("guidance request kind")
        if not records or not any(
            want["guidance_topic"] in e.stats.get("title", "").lower() for e in records
        ):
            problems.append("guidance retrieval topic")
        if not result.sources:
            problems.append("guidance source links")
        return problems
    if want.get("access"):
        return [] if "only see your own" in result.summary else ["access reply missing"]
    if not request or request.get("kind") != "data" or len(request.get("parts", [])) != 1:
        return ["wrong request kind or part count"]
    part = request["parts"][0]
    for field in ("metrics", "operation", "windows", "comparison", "threshold"):
        if field in want and part.get(field) != want[field]:
            problems.append("request " + field)
    if problems:
        return problems
    metric = want["metrics"][0]
    start, end = want["windows"][0].values()
    records = [
        e
        for e in result.evidence.values()
        if e.metrics == (metric,)
        and e.windows
        and str(e.windows[0].start) == start
        and str(e.windows[0].end) == end
    ]
    if not records:
        return ["no matching computed evidence"]
    if metric == "food_logs":
        if "you logged" not in result.summary:
            problems.append("food answer missing")
        for name in want.get("foods", []):
            if name not in result.summary:
                problems.append("food name missing")
        if "energy" in want and f"{want['energy']} kcal" not in result.summary:
            problems.append("food energy missing")
        return problems
    values = data.loc[start:end, metric].dropna().to_numpy()
    operation = want["operation"]
    if operation == "count":
        threshold = want["threshold"]
        compare = {
            "<": lambda v: v < threshold,
            "<=": lambda v: v <= threshold,
            ">": lambda v: v > threshold,
            ">=": lambda v: v >= threshold,
            "==": lambda v: v == threshold,
        }[want["comparison"]]
        expected = sum(bool(compare(v)) for v in values)
        if not any(e.stats.get("days_met") == expected for e in records):
            problems.append("wrong count")
        if f"{expected} of {len(values)}" not in result.summary:
            problems.append("count not answered in prose")
    else:
        expected = {
            "value": lambda: values[0],
            "mean": lambda: float(np.mean(values)),
            "median": lambda: float(np.median(values)),
            "sum": lambda: float(np.sum(values)),
        }[operation]()
        key = {"value": "mean", "sum": "total"}.get(operation, operation)
        if not any(abs(e.stats.get(key, float("inf")) - expected) < 0.001 for e in records):
            problems.append("wrong statistic")
        if format_level(metric, expected) not in result.summary:
            problems.append("value not answered in prose")
    if start not in result.summary or end not in result.summary:
        problems.append("dates not answered in prose")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--split",
        choices=[
            "smoke",
            "heldout",
            "confirmation",
            "constraints",
            "contract-regression",
        ],
        required=True,
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    plan = cases(args.split)
    frozen = json.dumps(plan, indent=2)
    (args.out / "plan.json").write_text(frozen)
    data = frame()
    data.to_pickle(args.out / "synthetic.pkl")
    (args.out / "run_script.py").write_text(Path(__file__).read_text())
    implementation = [
        Path("backend/app/agent") / name
        for name in ("requests.py", "requested.py", "ask.py", "world.py")
    ]
    (args.out / "implementation_hashes.json").write_text(
        json.dumps(
            {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in implementation},
            indent=2,
        )
    )
    food_logs = []
    if args.split in ("confirmation", "constraints", "contract-regression"):
        food_logs = [
            {
                "foodName": "Example oats",
                "mealType": "BREAKFAST",
                "consumedAt": "2026-11-17T09:00:00+00:00",
                "energyKcal": 310,
            },
            {
                "foodName": "Example lunch",
                "mealType": "LUNCH",
                "consumedAt": "2026-11-17T13:00:00+00:00",
                "energyKcal": 640,
            },
        ]
    (args.out / "confirmed_food.json").write_text(json.dumps(food_logs))
    cap = 0.15 if args.split == "smoke" else 0.65
    ledger = SpendLedger(cap_usd=cap)
    llm = OpenAILLM.from_settings(settings, ledger)
    llm._client = llm._client.with_options(max_retries=0)
    complete = llm.complete

    def captured(*args, **kwargs):
        completion = complete(*args, **kwargs)
        with (args_path / "provider.jsonl").open("a") as file:
            file.write(
                json.dumps(
                    {
                        "model": completion.model,
                        "cost_usd": completion.cost_usd,
                        "text": completion.text,
                        "calls": [
                            {"name": c.name, "arguments": c.arguments}
                            for c in completion.tool_calls
                        ],
                    }
                )
                + "\n"
            )
        return completion

    args_path = args.out
    llm.complete = captured
    router = default_router(settings)
    guard = default_guard(settings)
    # This check exercises actual repository RAG. No USDA/Google writes or paid web.
    outside = SimpleNamespace(
        web=lambda *args: {"error": "local-guidance-only"},
        food=lambda *args: {"error": "no-food-lookup"},
    )
    jev_spent = [0.0]
    original = JevClient.call

    def metered(self, payload):
        result = original(self, payload)
        jev_spent[0] += result[2]
        return result

    JevClient.call = metered
    rows = []
    try:
        for number, conversation in enumerate(plan):
            history = []
            for question, want in conversation:
                if ledger.spent_usd + jev_spent[0] >= cap - 0.02:
                    raise RuntimeError("Stopped before the capped budget")
                if "reader_kind" in want:
                    request, held, budget = interpret(llm, question, history, TODAY)
                    raw = request.model_dump(mode="json")
                    problems = [
                        key
                        for key in ("memory", "duration_minutes", "log_day")
                        if key in want and raw.get(key) != want[key]
                    ]
                    if raw["kind"] != want["reader_kind"]:
                        problems.append("reader kind")
                    if "topic" in want and want["topic"] not in " ".join(request.topics).lower():
                        problems.append("guidance topic")
                    summary, evidence = "", []
                else:
                    answer = ask(
                        llm,
                        router,
                        data,
                        question,
                        today=TODAY,
                        now=NOW,
                        history=history,
                        guard=guard,
                        outside=outside,
                        food_logs=food_logs,
                    )
                    result = answer.result
                    step = next((s for s in result.trace if s["type"] == "request"), {})
                    raw, held = step.get("request"), step.get("state", {})
                    problems = grade(result, raw, want, data)
                    budget, summary = result.budget, result.summary
                    evidence = [e.model_dump(mode="json") for e in result.evidence.values()]
                row = {
                    "conversation": number,
                    "question": question,
                    "want": want,
                    "request": raw,
                    "answer": summary,
                    "evidence": evidence,
                    "problems": problems,
                    "cost_usd": budget.cost_usd,
                }
                rows.append(row)
                with (args.out / "answers.jsonl").open("a") as file:
                    file.write(json.dumps(row) + "\n")
                if raw and raw.get("reader_error") == "LLMError":
                    raise RuntimeError("Request reader failed; stopped before further paid calls")
                history.append(Turn(question, summary, request_state=held, at=NOW))
            if (number + 1) % 5 == 0:
                print(
                    json.dumps(
                        {
                            "completed_conversations": number + 1,
                            "turns": len(rows),
                            "cost_usd": ledger.spent_usd + jev_spent[0],
                        }
                    ),
                    flush=True,
                )
    finally:
        summary = {
            "turns": len(rows),
            "passing_checks": sum(not r["problems"] for r in rows),
            "openai_usd": ledger.spent_usd,
            "jev_usd": jev_spent[0],
            "total_usd": ledger.spent_usd + jev_spent[0],
            "plan_sha256": hashlib.sha256(frozen.encode()).hexdigest(),
            "limits": "Targeted synthetic check; reader-only rows are labelled. Final prose "
            "still requires direct review. Not the 369-turn independent audit.",
        }
        (args.out / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
