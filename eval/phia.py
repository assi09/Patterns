"""Routed experts against one general agent, on questions we did not write.

The questions and answer key come from PHIA (Merrill, Paruchuri et al., "Transforming wearable data
into personal health insights using large language model agents", Nature Communications;
https://github.com/yahskapar/personal-health-insights-agent, CC BY-NC 4.0). Its four synthetic users
stand in for a person, so every answer can be published. Files are fetched into the git-ignored
`data/eval/phia`; run from the repository root with `PYTHONPATH=backend:eval python eval/phia.py`.

The general agent has no router, no experts, no consults and no question-type strategy: `answer` with
every tool and metric, and the app's default guide and budget. The claim checker and the medical
guard stay on for both, so what differs is the routing and the experts. It pays; `--stop` caps it.
"""

import argparse
import csv
import json
import operator
import random
import re
import statistics
import zipfile
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from xml.etree import ElementTree

import pandas as pd
import real_eval
from scipy import stats

from app.agent.agent import DEFAULT_GUIDE, answer
from app.agent.ask import ask, default_guard, default_router
from app.agent.experts import BUDGETS, Depth
from app.agent.router import EXPERT_LABELS, GENERAL
from app.agent.llm import OpenAILLM
from app.agent.verifier import MEDICAL
from app.analysis.day import with_scores
from app.config import settings

ROOT = Path("data/eval/phia")
RESULTS = Path("eval/results")
STAMP = "2026-11-10"
USERS = (465, 333, 171, 41)
PERSONAS = ("active_achiver", "health_behavior", "inactive_insomniacs", "sedentary_sleeper")
SEED = 503
EXACT, OPEN_ENDED, BLIND = 100, 60, 25
# PHIA's percent columns and stress score have no daily metric in the app, so those are left out.
COLUMNS = {
    "steps": "steps",
    "resting_heart_rate": "resting_hr",
    "heart_rate_variability": "hrv_ms",
    "active_zone_minutes": "active_zone_minutes",
    "sleep_minutes": "sleep_minutes",
    "deep_sleep_minutes": "deep_sleep_minutes",
    "rem_sleep_minutes": "rem_sleep_minutes",
    "light_sleep_minutes": "light_sleep_minutes",
    "awake_minutes": "awake_in_bed_minutes",
}
SIMPLE = re.compile(
    r"daily_metrics(?:\.query\('(?P<where>[^']+)'\))?(?:\.during\('(?P<when>[^']+)'\))?"
    r"\['(?P<column>\w+)'\](?:\.drop_duplicates\(\))?\.(?P<how>sum|mean|median|max|min|count)\(\)"
)
WHERE = re.compile(r"(\w+)\s*(<=|>=|<|>|==)\s*([\d.]+)(\*60)?")
COMPARE = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
}


def raw(user: int) -> pd.DataFrame:
    frame = pd.read_csv(ROOT / f"summary_df_{user}.csv")
    frame.index = pd.to_datetime(frame["datetime"]).dt.normalize()
    return frame.sort_index()


def person(user: int) -> pd.DataFrame:
    """A PHIA user as the daily table the agent reads."""
    source = raw(user)
    frame = source[list(COLUMNS)].rename(columns=COLUMNS).apply(pd.to_numeric, errors="coerce")
    bed = pd.to_datetime(source["bed_time"], errors="coerce")
    hour = bed.dt.hour + bed.dt.minute / 60
    frame["bedtime_hour"] = hour.where(hour < 12, hour - 24)
    frame["wear_minutes"] = 900.0  # none recorded; assumed worn
    index = pd.date_range(frame.index.min(), frame.index.max(), freq="D", name="date")
    return frame[~frame.index.duplicated()].reindex(index)


def _eligible(code: str) -> re.Match | None:
    """Plain daily questions on metrics the app has. Workouts and compound filters are left out."""
    match = SIMPLE.fullmatch(str(code).strip())
    if not match:
        return None
    if match["column"] != "datetime" and match["column"] not in COLUMNS:
        return None
    if match["where"]:
        condition = WHERE.fullmatch(match["where"].strip())
        if not condition or condition[1] not in COLUMNS:
            return None
    return match


def recompute(frame: pd.DataFrame, match: re.Match, window: str = "published") -> float:
    """PHIA's stored code, followed by hand rather than executed: a check on our reading of it.

    Its key reads "last 7 days" as eight calendar days ending today ("published"; this reproduces
    every such answer). A person means seven, ending today or ending yesterday, so a reply using
    either of those is accepted in the fair score, and only the published one in the strict score."""
    rows, last = frame, frame.index.max()
    if match["where"]:
        column, sign, number, minutes = WHERE.fullmatch(match["where"].strip()).groups()
        rows = rows[COMPARE[sign](rows[column], float(number) * (60 if minutes else 1))]
    if when := match["when"]:
        days = re.fullmatch(r"last (\d+) days", when)
        if when == "yesterday":
            start = end = last - timedelta(days=1)
        elif when == "today":
            start = end = last
        elif days:
            end = last - timedelta(days=1) if window == "before_today" else last
            extra = 1 if window == "published" else 0
            start = end - timedelta(days=int(days[1]) - 1 + extra)
        else:
            return float("nan")
        rows = rows.loc[start:end]
    values = (
        rows["datetime"].drop_duplicates()
        if match["column"] == "datetime"
        else rows[match["column"]]
    )
    return float(getattr(values, match["how"])())


def _same(mine: float, published: float) -> bool:
    return abs(mine - published) <= max(0.02, abs(published) * 0.0001)  # their rounding of sums


def exact_questions() -> tuple[list[dict], dict]:
    """The eligible questions with PHIA's own answers, and which user each file belongs to."""
    frames = {user: raw(user) for user in USERS}
    items, facts, taken = [], {"published": 0, "eligible": 0, "agree": 0, "owners": {}}, set()
    for persona in PERSONAS:
        table = pd.read_csv(ROOT / f"{persona}_final.csv")
        usable = [(r, m) for r in table.itertuples() if (m := _eligible(r.code))]
        scores = {
            user: sum(_same(recompute(frame, m), float(r.label)) for r, m in usable)
            for user, frame in frames.items()
        }
        owner = max(scores, key=scores.get)
        facts["owners"][persona] = owner
        facts["published"] += len(table)
        facts["eligible"] += len(usable)
        facts["agree"] += scores[owner]
        for row, match in usable:
            if (owner, row.question) not in taken:
                taken.add((owner, row.question))
                items.append(
                    {
                        "set": "exact",
                        "user": owner,
                        "q": str(row.question).strip(),
                        "label": float(row.label),
                        "also_accepted": [
                            recompute(frames[owner], match, w)
                            for w in ("including_today", "before_today")
                        ],
                        "how": match["how"],
                        "filtered": bool(match["where"]),
                    }
                )
    return items, facts


def open_questions() -> list[str]:
    space = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    book = zipfile.ZipFile(ROOT / "open.xlsx")
    shared = [
        "".join(t.text or "" for t in item.iter(f"{space}t"))
        for item in ElementTree.fromstring(book.read("xl/sharedStrings.xml")).findall(f"{space}si")
    ]
    found = []
    for row in ElementTree.fromstring(book.read("xl/worksheets/sheet1.xml")).iter(f"{space}row"):
        cell = row.find(f"{space}c")
        value = None if cell is None else cell.find(f"{space}v")
        if value is not None and cell.get("t") == "s":
            found.append(shared[int(value.text)].strip())
    return [q for q in found if q != "Question"]


class NoExperts:
    """The router's answer with every expert's share moved to the general agent: the same pipeline
    (question types, automatic RAG, premise check, refusals) with no expert behind it."""

    def __init__(self, router) -> None:
        self.router = router

    def classify(self, question: str, earlier=()):
        found = self.router.classify(question, earlier)
        topics = dict(found.probabilities)
        topics[GENERAL] = topics.get(GENERAL, 0.0) + sum(topics.pop(e, 0.0) for e in EXPERT_LABELS)
        topics |= dict.fromkeys(EXPERT_LABELS, 0.0)
        return replace(found, probabilities=topics, needs=dict.fromkeys(found.needs, 0.0))


class NoLookups:
    """Paid web search and food data are off: this measures the agent, within a small budget."""

    def web(self, llm, query, budget) -> dict:
        return {"error": "off"}

    def food(self, query, grams=None) -> dict:
        return {"error": "off"}


def rate(values: list[bool]) -> dict:
    n = len(values)
    if not n:
        return {"n": 0, "rate": None}
    p, z = sum(values) / n, 1.96
    middle = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5 / (1 + z * z / n)
    return {
        "n": n,
        "rate": round(p, 3),
        "wilson_95": [round(middle - half, 3), round(middle + half, 3)],
    }


def paired(first: list[bool], second: list[bool]) -> dict:
    """Exact McNemar test: only the questions where the two differ carry information."""
    a = sum(x and not y for x, y in zip(first, second, strict=True))
    b = sum(y and not x for x, y in zip(first, second, strict=True))
    return {
        "only_experts_right": a,
        "only_general_right": b,
        "p": round(float(stats.binomtest(a, a + b, 0.5).pvalue), 4) if a + b else None,
    }


def run_one(system, llm, router, guard, item, frame, spent) -> dict:
    now = datetime.combine(frame.index.max().date(), time(20), UTC)
    scored = with_scores(frame)
    if system in ("experts", "pipeline"):
        chosen = router if system == "experts" else NoExperts(router)
        reply = ask(
            llm, chosen, scored, item["q"], today=now, now=now, guard=guard, outside=NoLookups()
        )
        result, route = reply.result, reply.route
        jev = sum(s.get("cost_usd") or 0 for s in result.trace if s.get("type") == "route")
        done = {"route": route.expert or route.action, "type": route.classification.question_type}
    else:
        result = answer(
            llm,
            scored,
            item["q"],
            today=now,
            budget=replace(BUDGETS[Depth.QUICK]),
            guard=guard,
            guide=DEFAULT_GUIDE,
        )
        jev, done = 0.0, {}
    cost = result.budget.cost_usd + jev
    spent[0] += cost
    read = real_eval.extract(llm, item["q"], result.summary, spent)
    done |= {
        "answer": result.summary,
        "notes": list(result.notes),
        "stop": result.stop_reason,
        "calls": result.budget.calls,
        "cost": round(cost, 5),
        "claims": len(result.claims),
        "rejected": len(result.rejected),
        "medical": bool(MEDICAL.search(result.summary)) and result.stop_reason != "refused",
        "read": read,
    }
    if item["set"] == "exact":
        done["correct"] = real_eval.close(read.get("value"), item["label"])
        done["correct_fair"] = done["correct"] or any(
            real_eval.close(read.get("value"), value) for value in item["also_accepted"]
        )
    return done


def summarise(rows: list[dict], spent: float, facts: dict, tag: str) -> dict:
    both = [r for r in rows if "answer" in r["experts"] and "answer" in r["general"]]
    exact = [r for r in both if r["set"] == "exact"]
    opened = [r for r in both if r["set"] == "open"]

    def system(group: list[dict], name: str) -> dict:
        items = [r[name] for r in group]
        judged = [i["read"] for i in items if i["read"].get("useful")]
        return {
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
            "auto_judge_useful": round(statistics.mean(j["useful"] for j in judged), 2)
            if judged
            else None,
        }

    def correct(group: list[dict], name: str, key: str = "correct") -> list[bool]:
        return [bool(r[name][key]) for r in group]

    groups = defaultdict(list)
    for row in exact:
        groups["filtered: how many days" if row["filtered"] else row["how"]].append(row)
    summary = {
        "source": "PHIA questions and answer key, CC BY-NC 4.0; four synthetic users, about 30 days",
        "spent_usd": round(spent, 3),
        "questions_asked": len(rows),
        "failed_to_run": len(rows) - len(both),
        "phia_files": facts,
        "exact": {
            "experts": rate(correct(exact, "experts")),
            "general_agent": rate(correct(exact, "general")),
            "paired_test": paired(correct(exact, "experts"), correct(exact, "general")),
            "fair_score_any_reading_of_last_n_days": {
                "experts": rate(correct(exact, "experts", "correct_fair")),
                "general_agent": rate(correct(exact, "general", "correct_fair")),
                "paired_test": paired(
                    correct(exact, "experts", "correct_fair"),
                    correct(exact, "general", "correct_fair"),
                ),
            },
            "by_kind": {
                k: {
                    "experts": rate(correct(g, "experts")),
                    "general_agent": rate(correct(g, "general")),
                }
                for k, g in sorted(groups.items())
            },
            "experts_detail": system(exact, "experts"),
            "general_detail": system(exact, "general"),
        },
        "open_ended": {
            "n": len(opened),
            "experts_detail": system(opened, "experts"),
            "general_detail": system(opened, "general"),
            "note": "No answer key. The auto judge is unvalidated: people grade the blind sheet.",
        },
    }
    (RESULTS / f"phia_{STAMP}{tag}.json").write_text(json.dumps(summary, indent=1))
    return summary


def blind_sheet(rows: list[dict], tag: str) -> None:
    """Both systems' answers to a random set of open questions, shuffled and unlabeled."""
    opened = [
        r
        for r in rows
        if r["set"] == "open" and "answer" in r["experts"] and "answer" in r["general"]
    ]
    rng = random.Random(f"{SEED}:blind")
    sheet = [
        (r, name)
        for r in rng.sample(opened, min(BLIND, len(opened)))
        for name in ("experts", "general")
    ]
    rng.shuffle(sheet)
    with (RESULTS / f"phia_blind_{STAMP}{tag}.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            ["id", "question", "answer", "correct_1_to_5", "useful_1_to_5", "clear_1_to_5", "notes"]
        )
        for at, (row, name) in enumerate(sheet, 1):
            writer.writerow([at, row["q"], row[name]["answer"], "", "", "", ""])
    key = {at: name for at, (_, name) in enumerate(sheet, 1)}
    (RESULTS / f"phia_blind_key_{STAMP}{tag}.json").write_text(json.dumps(key, indent=0))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", type=float, default=3.1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--tag", default="")
    parser.add_argument("--dry-run", action="store_true")
    options = parser.parse_args()

    exact, facts = exact_questions()
    print(json.dumps(facts))
    rng = random.Random(SEED)
    items = rng.sample(exact, min(EXACT, len(exact)))
    every_open = open_questions()
    items += [
        {"set": "open", "user": rng.choice(USERS), "q": q}
        for q in rng.sample(every_open, min(OPEN_ENDED, len(every_open)))
    ]
    rng.shuffle(items)
    if options.limit:
        items = items[: options.limit]
    print("questions:", len(items), "of them open:", sum(i["set"] == "open" for i in items))
    if options.dry_run:
        for item in items[:12]:
            print(" -", item["set"], item["user"], item["q"][:90], item.get("label"))
        return

    frames = {user: person(user) for user in USERS}
    llm = OpenAILLM.from_settings(settings)
    router, guard = default_router(settings), default_guard(settings)
    spent, rows = [0.0], []
    RESULTS.mkdir(exist_ok=True)
    with (RESULTS / f"phia_answers_{STAMP}{options.tag}.jsonl").open("w") as file:
        for item in items:
            if spent[0] >= options.stop:
                print("Stopped at the spending limit.")
                break
            row = dict(item)
            stop = False
            for name in ("experts", "general"):
                try:
                    row[name] = run_one(name, llm, router, guard, item, frames[item["user"]], spent)
                except Exception as error:
                    message = str(error)[:160]
                    print("failed:", name, type(error).__name__, message)
                    row[name] = {"error": type(error).__name__}
                    stop = stop or "quota" in message.lower() or "credit" in message.lower()
            rows.append(row)
            file.write(json.dumps(row, default=str) + "\n")
            file.flush()
            print(
                f"${spent[0]:.3f} {item['set']} experts={row['experts'].get('correct')} general={row['general'].get('correct')}"
            )
            if stop:
                print("Out of OpenAI credit.")
                break
    print(json.dumps(summarise(rows, spent[0], facts, options.tag), indent=1))
    blind_sheet(rows, options.tag)


if __name__ == "__main__":
    main()
