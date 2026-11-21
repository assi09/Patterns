"""Scores a reader replay against expectations written before it ran (no model, no cost).

    .venv/bin/python eval/reader_smoke_check.py eval/reader_smoke_expected.json \\
        data/eval/reader_smoke_2026-11-19/readings.jsonl

A turn is clean when the final request has the expected kind and exactly the expected clauses:
each data clause's metric, operation, dates and comparison; a log's entry, day and duration; a
status question as status; a memory action and recall scope; an investigation's focus. Clean on
the first attempt and clean after a retry are counted apart. The stop rules (a rejected schema, a
swapped period, a dropped clause, a read turned into a write) are reported by name.
"""

import json
import sys
from pathlib import Path

WRITES = ("logging", "correction", "confirmation")


def reads(request: dict) -> list[tuple]:
    parts = request.get("parts", []) if request["kind"] in ("data", "causality") else []
    found = []
    for part in [*parts, *request.get("reads", [])]:
        windows = part.get("windows") or [{}]
        found.append(
            (
                tuple(part["metrics"]),
                part["operation"],
                windows[0].get("start"),
                windows[-1].get("end"),
                part.get("comparison"),
                part.get("threshold"),
            )
        )
    return found


def wanted(expect: list[dict]) -> list[tuple]:
    return [
        (
            (e["metric"],),
            e["operation"],
            e["start"],
            e["end"],
            e.get("comparison"),
            float(e["threshold"]) if "threshold" in e else None,
        )
        for e in expect
        if e["type"] == "data"
    ]


def verdict(item: dict, row: dict) -> tuple[str, list[str]]:
    request = row["request"] or {}
    problems = []
    if request.get("reader_error") in (
        "ValidationError",
        "LLMError",
        "BadRequestError",
    ):
        return "schema", [f"reader error {request['reader_error']}"]
    kind = request.get("kind")
    if kind != item["kind"]:
        problems.append(f"kind {kind}, expected {item['kind']}")
    if kind in WRITES and item["kind"] not in WRITES:
        problems.append("read turned into a write")
    got, want = reads(request), wanted(item["expect"])
    if sorted(got, key=str) != sorted(want, key=str):
        missing = [w for w in want if w not in got]
        extra = [g for g in got if g not in want]
        if missing and len(got) < len(want):
            problems.append(f"dropped clause: {missing}")
        swapped = {(w[0], w[1]) for w in missing} & {(g[0], g[1]) for g in extra}
        if swapped:
            problems.append(f"period wrong for {sorted(swapped)}")
        if extra:
            problems.append(f"read differs or extra: {extra}")
    for e in item["expect"]:
        if e["type"] == "log":
            if request.get("log_day") != e["day"]:
                problems.append(
                    f"log day {request.get('log_day')}, expected {e['day']}"
                )
            if request.get("duration_minutes") != e["duration"]:
                problems.append(
                    f"duration {request.get('duration_minutes')}, expected {e['duration']}"
                )
        if e["type"] == "status" and not (request.get("status") or kind == "status"):
            problems.append("status question not read as status")
        if e["type"] == "memory":
            if request.get("memory_action") != e["action"]:
                problems.append(
                    f"memory {request.get('memory_action')}, expected {e['action']}"
                )
            if "recall" in e and request.get("recall") not in e["recall"]:
                problems.append(
                    f"recall {request.get('recall')}, expected {e['recall']}"
                )
        if e["type"] == "investigate" and request.get("focus") != e["focus"]:
            problems.append(f"focus {request.get('focus')}, expected {e['focus']}")
    if problems:
        return "not clean", problems
    retried = len(request.get("attempts", [])) > 1
    return ("clean after a retry" if retried else "clean"), []


def main() -> None:
    expected = {t["id"]: t for t in json.loads(Path(sys.argv[1]).read_text())["turns"]}
    rows = [json.loads(line) for line in Path(sys.argv[2]).read_text().splitlines()]
    counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['conversation']}/{row['turn']}"
        status, problems = verdict(expected[key], row)
        counts[status] = counts.get(status, 0) + 1
        attempts = [
            (a.get("outcome"), a.get("codes"))
            for a in (row["request"] or {}).get("attempts", [])
        ]
        print(f"{status:20} {key:28} {attempts}")
        for problem in problems:
            print(f"{'':20}   - {problem}")
    missing = sorted(set(expected) - {f"{r['conversation']}/{r['turn']}" for r in rows})
    print(json.dumps(counts), "not run:", missing)
    cost = sum(r["cost_usd"] for r in rows)
    print(f"cost ${cost:.4f}, {sum(r['calls'] for r in rows)} calls")


if __name__ == "__main__":
    main()
