"""Does a larger reader model resolve "that earlier week" and "the week before that week"?

The small reader (gpt-5.4-mini) read "For that earlier week, just Monday to Friday?" after "And
the week before?" as the opening week in 64 of 66 replayed conversations, and showing each result
with its question moved the error between families rather than removing it. This reads 40 of
the same frozen third turns (reserved people only) with the large model (gpt-5.5) as the reader,
on the code of main, and grades them against the bank's key. The read-back check is unchanged.
The baseline is the replay's own small-model reading of the same turns.

    PYTHONPATH=backend .venv/bin/python eval/reader_model_probe.py freeze
    PYTHONPATH=backend .venv/bin/python eval/reader_model_probe.py run --sha <printed by freeze>
    PYTHONPATH=backend .venv/bin/python eval/reader_model_probe.py score
"""

import argparse
import hashlib
import json
from collections import Counter
from datetime import date
from pathlib import Path

SOURCE = Path(
    "data/eval/reader_followups_2026-11-23/jobs.json"
)  # frozen there, with its key
PROBE = Path("data/eval/reader_model_probe_2026-11-23")
TAKE = {"steps": 14, "resting_hr": 13, "sleep_minutes": 13}
OUT, JOBS, READINGS = PROBE, PROBE / "jobs.json", PROBE / "readings.jsonl"
CAP_USD = 1.20


def use(out: Path) -> None:
    global OUT, JOBS, READINGS
    OUT, JOBS, READINGS = out, out / "jobs.json", out / "readings.jsonl"


def resolved(request: dict | None) -> list:
    if not request or request.get("kind") not in ("data", "causality"):
        return []
    return [
        [p["metrics"], p["operation"], [[w["start"], w["end"]] for w in p["windows"]]]
        for p in request.get("parts", [])
    ]


def freeze(
    reader: str = "large",
    every: bool = False,
    cap: float = CAP_USD,
    reasoning: str | None = None,
    temperature: float | None = None,
) -> None:
    """`every`: all of the source's readings, both splits and the opening-week control."""
    source = json.loads(SOURCE.read_text())["jobs"]
    jobs = []
    families = sorted({j["family"] for j in source}) if every else list(TAKE)
    for family in families:
        chosen = sorted(
            (
                j
                for j in source
                if j["family"] == family and (every or j["split"] == "evaluation")
            ),
            key=lambda j: j["case"],
        )[: None if every else TAKE[family]]
        for job in chosen:
            # The state as main saves it: no question kept beside each result.
            history = [
                h | {"state": {k: v for k, v in h["state"].items() if k != "asked"}}
                for h in job["history"]
            ]
            jobs.append(job | {"history": history})
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = {
        "cap_usd": cap,
        "reader": reader,
        "reasoning": reasoning,
        "temperature": temperature,
        "jobs": jobs,
    }
    body = json.dumps(frozen, sort_keys=True, indent=1)
    JOBS.write_text(body)
    print(f"{len(jobs)} readings frozen {dict(Counter(j['family'] for j in jobs))}")
    print(f"reader {reader}, reasoning {reasoning}, temperature {temperature}")
    print(f"cap ${cap}")
    print(f"sha256 {hashlib.sha256(body.encode()).hexdigest()}")


def run(sha: str) -> None:
    from app.agent.context import Turn
    from app.agent.llm import BudgetExceeded, OpenAILLM, Role, SpendLedger
    from app.agent.requests import interpret
    from app.config import settings

    class LargeReader(OpenAILLM):
        def read_request(self, messages, *, tools, budget):
            return self.complete(messages, role=Role.LARGE, tools=tools, budget=budget)

    body = JOBS.read_text()
    if hashlib.sha256(body.encode()).hexdigest() != sha:
        raise ValueError("The frozen jobs changed since they were approved")
    if READINGS.exists():
        raise ValueError(
            f"{READINGS} exists: a finished run is never rerun for a higher mark"
        )
    frozen = json.loads(body)
    ledger = SpendLedger(cap_usd=frozen["cap_usd"])
    base = OpenAILLM.from_settings(settings, ledger)
    if frozen["reader"] == "large":
        llm = LargeReader.__new__(LargeReader)
        llm.__dict__.update(base.__dict__)
    else:
        llm = base
    # The reader's own options; the read-back check is unchanged. Function tools take
    # no reasoning effort on chat completions for the small model (a 400 from the API).
    options = {
        key: value
        for key, value in (
            ("reasoning_effort", frozen.get("reasoning")),
            ("temperature", frozen.get("temperature")),
        )
        if value is not None
    }
    if options:
        role = Role.LARGE if frozen["reader"] == "large" else Role.SMALL
        llm._options = {**llm._options, role: options}
    done = 0
    with READINGS.open("w") as out:
        for job in frozen["jobs"]:
            if ledger.spent_usd >= frozen["cap_usd"]:
                print(f"Stopped at the cap after {done} readings.")
                break
            history = [
                Turn(h["question"], h["answer"], request_state=h["state"])
                for h in job["history"]
            ]
            request, _, budget = interpret(
                llm,
                job["question"],
                history,
                date.fromisoformat(job["today"]),
                keep_readings=True,
            )
            if request is not None and request.reader_error == BudgetExceeded.__name__:
                print(
                    f"Stopped at the cap after {done} readings; this one is not recorded."
                )
                break
            done += 1
            row = {
                "case": job["case"],
                "family": job["family"],
                "request": request.model_dump(mode="json") if request else None,
                "cost_usd": budget.cost_usd,
            }
            out.write(json.dumps(row, default=str) + "\n")
            out.flush()
    print(
        f"{done} readings, ${ledger.spent_usd:.6f} spent of a ${frozen['cap_usd']} cap."
    )


def score() -> None:
    jobs = {(j["case"], j["family"]): j for j in json.loads(JOBS.read_text())["jobs"]}
    rows = [json.loads(line) for line in READINGS.read_text().splitlines()]
    now, before = Counter(), Counter()
    for row in rows:
        job = jobs[(row["case"], row["family"])]
        now[job["family"], job["expected"] in resolved(row["request"])] += 1
        if job["baseline_right"] is not None:
            before[job["family"], job["baseline_right"]] += 1
    frozen = json.loads(JOBS.read_text())
    setting = (
        ", ".join(
            f"{key} {frozen[key]}"
            for key in ("reader", "reasoning", "temperature")
            if frozen.get(key) is not None
        )
        or "reader large"
    )  # the first probe's file predates these fields
    print(setting)
    for family in sorted({f for f, _ in now}):
        total = now[family, True] + now[family, False]
        was = before[family, True] + before[family, False]
        base = f"small (replay) {before[family, True]}/{was}" if was else "no baseline"
        print(f"{family:17} now {now[family, True]}/{total}   {base}")
    print(f"{len(rows)} of {len(jobs)} read; ${sum(r['cost_usd'] for r in rows):.6f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=PROBE)
    sub = parser.add_subparsers(dest="command", required=True)
    frozen = sub.add_parser("freeze")
    frozen.add_argument("--reader", choices=("small", "large"), default="large")
    frozen.add_argument("--every", action="store_true")
    frozen.add_argument("--cap", type=float, default=CAP_USD)
    frozen.add_argument("--reasoning", choices=("minimal", "low", "medium"))
    frozen.add_argument("--temperature", type=float)
    sub.add_parser("run").add_argument("--sha", required=True)
    sub.add_parser("score")
    args = parser.parse_args()
    use(args.out)
    if args.command == "freeze":
        freeze(args.reader, args.every, args.cap, args.reasoning, args.temperature)
    elif args.command == "run":
        run(args.sha)
    else:
        score()


if __name__ == "__main__":
    main()
