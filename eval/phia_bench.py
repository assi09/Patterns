"""PHIA's own questions as a benchmark: Patterns against three baselines, run in batches.

Mode A asks each question of the PHIA synthetic user it was written for and grades it against PHIA's
published answer. Mode B asks the same questions of real people (PMData, LifeSnaps), the course's
required real public data, with the answer computed by PHIA's own answer logic on that person's data
(`phia.recompute`, which reproduces all 1,603 published answers). Questions and answers are not ours.

Systems, all on the same model, data, date and question:
- patterns: the app as it is (`ask`: router, experts, plans, verifier).
- single_agent: one agent with every tool and the default guide, no router or plans.
- chatbot: the data pasted in as a table, no tools (PHIA's "numerical reasoning" baseline).
- code: the model writes one pandas expression over the table, and code runs it (PHIA's
  "code generation" baseline).

Run from the repository root with PYTHONPATH=backend:eval:
  python eval/phia_bench.py build                      free: cleans the questions, makes the batches
  python eval/phia_bench.py run --mode A --batch 1 --first 20   pays: the first 20 of a batch
  python eval/phia_bench.py run --mode A --batch 1     pays: the rest of it (answered items are kept)
  python eval/phia_bench.py report                     free: accuracy, paired tests, cost
A run stops by itself after `STOP_AFTER` failures in a row of any one system, or at `--stop` dollars.
Answers about real people stay in the git-ignored data/eval/results; only totals are committed.
"""

import argparse
import json
import math
import random
import re
import time as clock
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime, time
from pathlib import Path

import numpy as np
import pandas as pd
import phia
import real_data
import real_eval
from app.agent.agent import DEFAULT_GUIDE, answer
from app.agent.ask import ask, default_guard, default_router
from app.agent.experts import BUDGETS, Depth
from app.agent.llm import Budget, OpenAILLM, SpendLedger
from app.analysis.day import with_scores
from app.config import settings
from scipy.stats import binomtest

ITEMS = Path(
    "data/eval/phia_bench_items.json"
)  # git-ignored: real people's answers stay local
ANSWERS = Path("data/eval/results")  # git-ignored: replies about real people stay local
SUMMARY = Path("eval/results/phia_bench_summary.json")
SYSTEMS = ("patterns", "single_agent", "chatbot", "code")
BATCHES_A, BATCHES_B, BATCH_SIZE = 5, 2, 300
STOP_AFTER = 5
SEED = 503
# What any person could have on one day: a "how many days" question past these is answered "0" by
# every system without reading anything ("exactly 15 hours of sleep"), so it proves nothing.
PLAUSIBLE = {
    "sleep_minutes": (60, 960),
    "light_sleep_minutes": (0, 600),
    "deep_sleep_minutes": (0, 240),
    "rem_sleep_minutes": (0, 240),
    "awake_minutes": (0, 240),
    "steps": (0, 40000),
    "active_zone_minutes": (0, 400),
    "resting_heart_rate": (30, 110),
    "heart_rate_variability": (5, 250),
}
RATES = {"resting_heart_rate", "heart_rate_variability"}
UNIT = {"steps": "steps", "resting_heart_rate": "bpm", "heart_rate_variability": "ms"}


# Building the questions (free)


def _codes() -> dict[tuple[int, str], str]:
    _, facts = phia.exact_questions()
    codes = {}
    for persona in phia.PERSONAS:
        table = pd.read_csv(phia.ROOT / f"{persona}_final.csv")
        owner = facts["owners"][persona]
        for question, code in zip(table.question, table.code, strict=True):
            codes.setdefault((owner, str(question).strip()), str(code))
    return codes


def _threshold(match: re.Match) -> tuple[str, float] | None:
    if not match["where"]:
        return None
    column, _, number, minutes = phia.WHERE.fullmatch(match["where"].strip()).groups()
    return column, float(number) * (60 if minutes else 1)


# Checking PHIA's key against its own words: it has errors. "Sleep less than 3 hours" is coded as
# sleep_minutes >= 180, and light-sleep questions are computed on total sleep (found 2026-11-16).
METRIC_WORDS = [  # most specific first
    ("light", "light_sleep_minutes"),
    ("deep", "deep_sleep_minutes"),
    ("rem", "rem_sleep_minutes"),
    ("awake", "awake_minutes"),
    ("heart rate variability", "heart_rate_variability"),
    ("hrv", "heart_rate_variability"),
    ("resting", "resting_heart_rate"),
    ("heart rate", "resting_heart_rate"),
    ("zone", "active_zone_minutes"),
    ("step", "steps"),
    ("walk", "steps"),
    ("sleep", "sleep_minutes"),
    ("slept", "sleep_minutes"),
]
HOW_WORDS = [
    ("how many days", "count"),
    ("median", "median"),
    ("middle", "median"),
    ("average", "mean"),
    ("mean", "mean"),
    ("highest", "max"),
    ("most", "max"),
    ("max", "max"),
    ("best", "max"),
    ("lowest", "min"),
    ("least", "min"),
    ("min", "min"),
    ("fewest", "min"),
    ("total", "sum"),
    ("sum", "sum"),
]
LESS = re.compile(
    r"\b(less than|fewer than|under|below|at most|less|fewer|lower than)\b",
    re.IGNORECASE,
)
MORE = re.compile(
    r"\b(more than|greater than|over|above|at least|exceed|higher than|more|greater)\b",
    re.IGNORECASE,
)
EQUAL = re.compile(r"\b(exactly|equals?|equal to)\b", re.IGNORECASE)


def named_metric(q):
    low = q.lower()
    for word, col in METRIC_WORDS:
        if re.search(rf"\b{word}", low):
            return col
    return None


def key_problems(q, m, threshold_col):
    out = []
    target = m["column"] if m["column"] != "datetime" else threshold_col
    if (named := named_metric(q)) and target and named != target:
        out.append(f"metric: words {named}, code {target}")
    low = re.sub(r"\b(at least|at most|or equal to|minutes?|mins?)\b", " ", q.lower())
    how = next((h for w, h in HOW_WORDS if re.search(rf"\b{w}\b", low)), None)
    if how and how != m["how"]:
        out.append(f"kind: words {how}, code {m['how']}")
    if m["where"]:
        op = re.search(r"(<=|>=|<|>|==)", m["where"]).group(1)
        if re.search(
            r"less than or equal|at most|fewer than or equal", q, re.IGNORECASE
        ):
            said = "lt"
        elif re.search(
            r"greater than or equal|more than or equal|at least", q, re.IGNORECASE
        ):
            said = "gt"
        elif EQUAL.search(q):
            said = "eq"
        elif LESS.search(q):
            said = "lt"
        elif MORE.search(q):
            said = "gt"
        else:
            said = None
        coded = {"<": "lt", "<=": "lt", ">": "gt", ">=": "gt", "==": "eq"}[op]
        if said and said != coded:
            out.append(f"direction: words {said}, code {op}")
    period = re.search(r"last (\d+) days|today|yesterday", q.lower())
    said_when = period.group(0) if period else None
    if (m["when"] or None) != said_when:
        out.append(f"period: words {said_when}, code {m['when']}")
    return out


def why_dropped(match: re.Match, question: str = "") -> str | None:
    """Why a question proves nothing, or None if it is kept."""
    if question and key_problems(question, match, (_threshold(match) or (None,))[0]):
        return "PHIA's key does not match its own words (wrong metric or direction)"
    if match["how"] == "sum" and match["column"] in RATES:
        return "a total of a heart rate, which means nothing"
    if match["how"] == "count" and match["when"] in ("today", "yesterday"):
        return "'how many days' asked about one day"
    if (found := _threshold(match)) and found[0] in PLAUSIBLE:
        low, high = PLAUSIBLE[found[0]]
        if not low <= found[1] <= high:
            return "a threshold no person reaches, answered 0 by anyone"
    return None


def tidy(question: str) -> str:
    """The template's doubled word ("did I I had") made single; nothing else is changed."""
    return re.sub(r"\bI I\b", "I", question).strip()


MIN_COVERAGE = 0.8  # of the days in a question's period, for a real person


def covered(frame: pd.DataFrame, match: re.Match, needed: set[str]) -> bool:
    """Whether the person has the data the question's period needs. A real person's sleep can stop
    weeks before their steps do: "last 21 days" over one night of sleep gave a key of 1, which no
    system could fairly be marked on (the live check of 2026-11-16)."""
    last, when = frame.index.max(), match["when"]
    needed = {c for c in needed if c}
    if when in ("today", "yesterday"):
        day = last if when == "today" else last - pd.Timedelta(days=1)
        return all(day in frame.index and pd.notna(frame.at[day, c]) for c in needed)
    if when and (days := re.fullmatch(r"last (\d+) days", when)):
        rows = frame.loc[last - pd.Timedelta(days=int(days[1]) - 1) : last]
        return all(rows[c].notna().mean() >= MIN_COVERAGE for c in needed)
    return all(frame[c].notna().sum() >= 30 for c in needed)


def phia_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """A real person's table in PHIA's column names, for PHIA's answer logic."""
    back = {ours: theirs for theirs, ours in phia.COLUMNS.items()}
    out = frame.rename(columns=back)
    out = out[[c for c in back.values() if c in out.columns]].copy()
    out["datetime"] = out.index
    return out


def _stratified(
    items: list[dict], batches: int, rng: random.Random
) -> list[list[dict]]:
    """Every kind, period and metric spread evenly over the batches."""
    rng.shuffle(items)
    items.sort(key=lambda i: (i["how"], i["when"], i["metric"]))
    out = [[] for _ in range(batches)]
    for n, item in enumerate(items):
        out[n % batches].append(item)
    for batch in out:
        rng.shuffle(batch)
    return out


def build() -> dict:
    rng = random.Random(SEED)
    published, _ = phia.exact_questions()
    codes = _codes()
    dropped, mode_a = Counter(), []
    for item in published:
        match = phia._eligible(codes[(item["user"], item["q"])])
        if reason := why_dropped(match, item["q"]):
            dropped[reason] += 1
            continue
        mode_a.append(
            {
                "mode": "A",
                "person": str(item["user"]),
                "q": tidy(item["q"]),
                "code": codes[(item["user"], item["q"])],
                "label": item["label"],
                "also_accepted": item["also_accepted"],
                "how": match["how"],
                "when": match["when"] or "all data",
                "metric": match["column"],
            }
        )
    # Mode B: the same questions, each asked of one real person who has the data it needs.
    people = {f"pmdata/{k}": v for k, v in real_data.load_pmdata().items()}
    people |= {f"lifesnaps/{k}": v for k, v in real_data.load_lifesnaps().items()}
    frames = {name: phia_frame(frame) for name, frame in people.items()}
    names, mode_b, unplaced = sorted(frames), [], 0
    seen = set()
    for item in mode_a:
        if item["q"] in seen:
            continue
        seen.add(item["q"])
        match = phia._eligible(item["code"])
        needed = {
            c
            for c in (match["column"], (_threshold(match) or ("",))[0])
            if c != "datetime"
        }
        for name in rng.sample(names, len(names)):
            frame = frames[name]
            if not all(
                c in frame.columns and frame[c].notna().sum() >= 30 for c in needed if c
            ):
                continue
            if not covered(frame, match, needed):
                continue
            keys = [
                phia.recompute(frame, match, w)
                for w in ("published", "including_today", "before_today")
            ]
            if any(math.isnan(k) for k in keys):
                continue
            mode_b.append(
                item
                | {
                    "mode": "B",
                    "person": name,
                    "label": keys[0],
                    "also_accepted": keys[1:],
                }
            )
            break
        else:
            unplaced += 1
    batches_a = _stratified(mode_a, BATCHES_A, rng)
    pool_b = _stratified(mode_b, max(1, len(mode_b) // BATCH_SIZE), rng)[:BATCHES_B]
    for mode, batches in (("A", batches_a), ("B", pool_b)):
        for number, batch in enumerate(batches, start=1):
            for n, item in enumerate(batch):
                item |= {"batch": number, "id": f"{mode}{number}-{n:03d}"}
    built = {
        "published": 4000,
        "relevant_shape": len(published),
        "dropped": dict(dropped),
        "mode_a": len(mode_a),
        "mode_b_pool": len(mode_b),
        "mode_b_unplaced": unplaced,
        "tidied": sum(tidy(i["q"]) != i["q"] for i in published),
        "batches": {
            "A": [len(b) for b in batches_a],
            "B": [len(b) for b in pool_b],
        },
        "items": [i for b in (*batches_a, *pool_b) for i in b],
    }
    ITEMS.write_text(json.dumps(built, indent=1, default=float) + "\n")
    return built


# Running a batch (paid)


CODE_PROMPT = """You answer a question about one person's daily fitness data by writing ONE pandas
expression over a DataFrame `df`, one row per day, indexed by date (a DatetimeIndex, newest last).
Columns: {columns}. Durations are in minutes. Today is {today}; "today" is the last row.
This is pandas {version}: DataFrame.last() no longer exists, so select days by filtering the index.
Reply with JSON only: {{"code": "<one expression that evaluates to a single number>"}}."""
UNSAFE = re.compile(r"__|import|open\(|exec|eval|os\.|sys\.|subprocess|globals|locals")


def code_baseline(
    llm, frame: pd.DataFrame, question: str, now: datetime, spent: list
) -> tuple:
    """PHIA's code-generation baseline: one expression, run by code, no loop and no checks."""
    budget = Budget(max_calls=1, max_cost_usd=0.01)
    task = CODE_PROMPT.format(
        columns=", ".join(frame.columns),
        today=f"{now:%A %d %b %Y}",
        version=pd.__version__,
    )
    done = llm.complete(
        [{"role": "system", "content": task}, {"role": "user", "content": question}],
        budget=budget,
    )
    spent[0] += budget.cost_usd
    text = done.text or "{}"
    try:
        code = json.loads(text[text.index("{") : text.rindex("}") + 1])["code"]
    except (ValueError, KeyError):
        return None, f"no code: {text[:200]}", budget.cost_usd
    if UNSAFE.search(code):
        return None, f"refused code: {code[:200]}", budget.cost_usd
    try:
        value = eval(
            code, {"__builtins__": {}}, {"df": frame.copy(), "pd": pd, "np": np}
        )
        return float(value), code, budget.cost_usd
    except Exception as exc:  # noqa: BLE001 the baseline's own failure, scored as wrong
        return None, f"{type(exc).__name__}: {code[:200]}", budget.cost_usd


DURATION = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours?)\b(?:\s*(?:and\s*)?(\d+)\s*(?:min|mins|minutes?)\b)?"
    r"|(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?:min|mins|minutes?)\b",
    re.IGNORECASE,
)
NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w,]*\d)")
DATE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2}(?:,? \d{4})?\b"
    r"|\b\d{4}-\d{2}-\d{2}\b|\b(?:19|20)\d{2}\b",
    re.IGNORECASE,
)


def exact(got, want: float) -> bool:
    try:
        return got is not None and abs(float(got) - want) < 0.5
    except (TypeError, ValueError):
        return False


def numbers_in(reply: str) -> list[float]:
    """Every figure a reply states, read by code: durations in minutes ("7 h 22 min" = 442),
    "13,458" as one number, dates left out. A check on the model that reads the answer."""
    text, found = DATE.sub(" ", reply or ""), []
    for m in DURATION.finditer(text):
        if m.group(3):
            found.append(float(m.group(3).replace(",", "")))
        else:
            found.append(float(m.group(1)) * 60 + float(m.group(2) or 0))
            if not m.group(2):
                found.append(float(m.group(1)))  # "6 h" may also be a count of hours
    rest = DURATION.sub(" ", text)
    found += [float(n.replace(",", "")) for n in NUMBER.findall(rest)]
    return found


def ask_one(system, llm, router, guard, item, frame, spent) -> dict:
    now = datetime.combine(frame.index.max().date(), time(20), UTC)
    started, out = clock.monotonic(), {}
    if system == "code":
        value, code, cost = code_baseline(llm, frame, item["q"], now, spent)
        out = {"value": value, "reply": code, "cost": round(cost, 5)}
    else:
        if system == "patterns":
            reply = ask(
                llm,
                router,
                with_scores(frame),
                item["q"],
                today=now,
                now=now,
                guard=guard,
                outside=phia.NoLookups(),
            )
            result = reply.result
            cost = result.budget.cost_usd + sum(
                s.get("cost_usd") or 0 for s in result.trace if s.get("type") == "route"
            )
            out["type"] = reply.route.classification.question_type
            text = result.summary
        elif system == "single_agent":
            result = answer(
                llm,
                with_scores(frame),
                item["q"],
                today=now,
                budget=replace(BUDGETS[Depth.QUICK]),
                guard=guard,
                guide=DEFAULT_GUIDE,
            )
            cost, text = result.budget.cost_usd, result.summary
        else:
            before = spent[0]
            text = real_eval.plain_chatbot(
                llm, frame, list(frame.columns), item["q"], now, spent
            )
            cost = spent[0] - before
            spent[0] = before
        if system != "chatbot":
            # How it got there: the tools it ran, and what the verifier turned down.
            out["stop"] = result.stop_reason
            out["tools"] = [
                s.get("name") for s in walk(result.trace) if s.get("type") == "tool"
            ]
            out["rejected"] = len(result.rejected)
            out["claims"] = len(result.claims)
        spent[0] += cost
        read = real_eval.extract(llm, item["q"], text, spent)
        out |= {"value": read.get("value"), "reply": text[:800], "cost": round(cost, 5)}
    out["seconds"] = round(clock.monotonic() - started, 1)
    right = (
        exact if item["how"] == "count" else real_eval.close
    )  # a count of days is exact
    out["strict"] = right(out["value"], item["label"])
    out["fair"] = out["strict"] or any(
        right(out["value"], a) for a in item["also_accepted"]
    )
    if system != "code":
        # Code's own reading of the reply: does it state the right figure anywhere? Where it and
        # the reading model disagree, the answer is listed for a person to check.
        keys = [item["label"], *item["also_accepted"]]
        asked = set(numbers_in(item["q"]))  # "last 21 days" in the reply is no answer
        stated = [n for n in numbers_in(out["reply"]) if n not in asked or n in keys]
        out["scan_fair"] = any(right(n, k) for n in stated for k in keys)
        out["readers_disagree"] = out["scan_fair"] != out["fair"]
    return out


def walk(steps: list) -> list[dict]:
    """Every step of a trace, with those a consulted expert's run nests."""
    found = []
    for step in steps or []:
        if isinstance(step, dict):
            found.append(step)
            found += walk(step.get("steps") or [])
    return found


def _frame_for(item: dict, cache: dict) -> pd.DataFrame:
    if item["person"] not in cache:
        if item["mode"] == "A":
            cache[item["person"]] = phia.person(int(item["person"]))
        else:
            source = item["person"].split("/", 1)[0]
            loaded = (
                real_data.load_pmdata()
                if source == "pmdata"
                else real_data.load_lifesnaps()
            )
            cache.update({f"{source}/{k}": v for k, v in loaded.items()})
    return cache[item["person"]]


def run(mode: str, batch: int, first: int | None, stop: float, systems: tuple) -> None:
    items = [
        i
        for i in json.loads(ITEMS.read_text())["items"]
        if i["mode"] == mode and i["batch"] == batch
    ]
    out = ANSWERS / f"phia_bench_{mode}{batch}.jsonl"
    done = (
        {json.loads(line)["id"] for line in out.read_text().splitlines()}
        if out.exists()
        else set()
    )
    todo = [i for i in items if i["id"] not in done][: first or None]
    llm = OpenAILLM.from_settings(settings, SpendLedger(cap_usd=stop + 0.5))
    router, guard, spent, cache = (
        default_router(settings),
        default_guard(settings),
        [0.0],
        {},
    )
    failing = Counter()
    print(
        f"{mode}{batch}: {len(todo)} to ask ({len(done)} already answered), systems {systems}"
    )
    for n, item in enumerate(todo, start=1):
        if spent[0] >= stop:
            print("Stopped at the spending limit.")
            break
        frame = _frame_for(item, cache)
        row = {
            k: item[k]
            for k in (
                "id",
                "mode",
                "batch",
                "person",
                "q",
                "label",
                "how",
                "when",
                "metric",
            )
        }
        for system in systems:
            try:
                row[system] = ask_one(system, llm, router, guard, item, frame, spent)
            except Exception as exc:  # noqa: BLE001 a crash is that system's failure, counted
                row[system] = {
                    "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                    "strict": False,
                    "fair": False,
                }
            broken = "error" in row[system] or row[system].get("stop") == "model_error"
            failing[system] = failing[system] + 1 if broken else 0
        with out.open("a") as file:
            file.write(json.dumps(row, default=float) + "\n")
        marks = " ".join(f"{s[:6]}:{'Y' if row[s]['fair'] else '-'}" for s in systems)
        print(f"{n:3d} ${spent[0]:.3f} {marks} | {item['q'][:70]}")
        if bad := [s for s, count in failing.items() if count >= STOP_AFTER]:
            print(
                f"Stopped: {bad} failed {STOP_AFTER} times in a row. Fix before going on."
            )
            break
    print(f"spent ${spent[0]:.3f}")


# Reporting (free)


def wilson(hits: int, n: int) -> list[float]:
    if not n:
        return [0.0, 0.0]
    z, p = 1.96, hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 3), round(centre + half, 3)]


def report() -> dict:
    rows = [
        json.loads(line)
        for path in sorted(ANSWERS.glob("phia_bench_*.jsonl"))
        for line in path.read_text().splitlines()
    ]
    summary: dict = {}
    for mode in ("A", "B"):
        group = [r for r in rows if r["mode"] == mode]
        systems = [s for s in SYSTEMS if all(s in r for r in group)] if group else []
        if not group:
            continue
        part: dict = {"questions": len(group), "systems": {}}
        for system in systems:
            for score in ("strict", "fair"):
                hits = sum(r[system][score] for r in group)
                part["systems"].setdefault(system, {})[score] = {
                    "rate": round(hits / len(group), 3),
                    "wilson_95": wilson(hits, len(group)),
                }
            costs = [r[system].get("cost", 0) for r in group]
            part["systems"][system]["cost_per_answer"] = round(float(np.mean(costs)), 5)
            seconds = [r[system].get("seconds", 0) for r in group]
            part["systems"][system]["seconds_mean"] = round(float(np.mean(seconds)), 1)
        for other in (s for s in systems if s != "patterns" and "patterns" in systems):
            only_p = sum(r["patterns"]["fair"] and not r[other]["fair"] for r in group)
            only_o = sum(r[other]["fair"] and not r["patterns"]["fair"] for r in group)
            part[f"patterns_vs_{other}"] = {
                "only_patterns_right": only_p,
                "only_other_right": only_o,
                "p": round(binomtest(only_p, only_p + only_o).pvalue, 4)
                if only_p + only_o
                else None,
            }
        by_kind = defaultdict(lambda: defaultdict(list))
        for r in group:
            for system in systems:
                by_kind[r["how"]][system].append(r[system]["fair"])
        if "patterns" in systems:
            # Every PHIA question is a value over a period or a day: the router's type for it.
            types = Counter(r["patterns"].get("type") for r in group)
            part["router_types"] = dict(types)
            part["router_type_right"] = round(
                sum(types[t] for t in ("lookup", "day")) / len(group), 3
            )
        for system in (s for s in systems if s in ("patterns", "single_agent")):
            tools = Counter(t for r in group for t in r[system].get("tools", []))
            part["systems"][system]["tools_used"] = dict(tools.most_common(8))
            part["systems"][system]["claims_rejected"] = sum(
                r[system].get("rejected", 0) for r in group
            )
        part["readers_disagree"] = {
            s: sum(r[s].get("readers_disagree", False) for r in group)
            for s in systems
            if s != "code"
        }
        part["fair_by_kind"] = {
            kind: {s: round(sum(v) / len(v), 3) for s, v in d.items()}
            for kind, d in by_kind.items()
        }
        summary[mode] = part
    SUMMARY.write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build")
    go = sub.add_parser("run")
    go.add_argument("--mode", choices=("A", "B"), required=True)
    go.add_argument("--batch", type=int, required=True)
    go.add_argument(
        "--first", type=int, help="ask only this many more questions of the batch"
    )
    go.add_argument("--stop", type=float, default=5.0)
    go.add_argument("--systems", default=",".join(SYSTEMS))
    sub.add_parser("report")
    args = parser.parse_args()
    if args.command == "build":
        built = build()
        print(json.dumps({k: v for k, v in built.items() if k != "items"}, indent=1))
    elif args.command == "run":
        run(
            args.mode, args.batch, args.first, args.stop, tuple(args.systems.split(","))
        )
    else:
        print(json.dumps(report(), indent=1))


if __name__ == "__main__":
    main()
