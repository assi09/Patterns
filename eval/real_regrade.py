"""Regrade the stored answers of `real_eval.py`, at no cost, with two grader faults fixed.

Reading the wrong answers showed the grader, not the agent, had failed some: an honest "I can’t
tell" missed its keyword because of the curly apostrophe, and "did not clearly change, a little
lower" was read as a claimed drop. The same rule is applied to both systems. The first score is
kept beside this one. Run from the repository root with `PYTHONPATH=backend:eval`.
"""

import glob
import json
import random
import re
import statistics
from collections import defaultdict
from pathlib import Path

import oracle
import real_data
import real_eval

NO_CLEAR = re.compile(
    r"\b(?:no|not|n['’]t|without)\b[^.;]{0,40}?\b(?:clear(?:ly)?|meaningful(?:ly)?|significant(?:ly)?|"
    r"reliabl[ey]|definite|obvious(?:ly)?|strong)\b|n['’]t (?:differ|change)|\bheld steady\b|"
    r"\bno (?:difference|change|link)\b",
    re.I,
)


def regraded(item: dict, text: str, read: dict, refused: bool) -> bool | None:
    want = item["want"]
    if "expect" in want:
        low = text.lower().replace("’", "'")
        if want["expect"] == "no_data":
            return not refused and any(w in low for w in want["words"])
        return real_eval.score(item, read, text, refused).get("correct")
    if not want:
        return None
    fixed = dict(read)
    # Only the opening sentence is the verdict; later ones may be about something else.
    opening = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    if not opening.lower().startswith("yes") and NO_CLEAR.search(opening):
        if "direction" in want:
            fixed["direction"] = "none"
        if "link" in want:
            fixed["link"] = "none"
    return real_eval.score(item, fixed, text, refused).get("correct")


def wilson(hits: int, n: int) -> list[float]:
    if not n:
        return [0.0, 0.0]
    z, p = 1.96, hits / n
    middle = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5 / (1 + z * z / n)
    return [round(middle - half, 3), round(middle + half, 3)]


def by_person_interval(rows: list[tuple[str, bool]]) -> list[float]:
    """Answers from one person are not independent, so resample people, not answers."""
    people = defaultdict(list)
    for person, hit in rows:
        people[person].append(hit)
    names, rng, rates = sorted(people), random.Random(503), []
    for _ in range(2000):
        hits = [h for n in rng.choices(names, k=len(names)) for h in people[n]]
        rates.append(sum(hits) / len(hits))
    rates.sort()
    return [round(rates[50], 3), round(rates[1949], 3)]


def rate(values: list[bool]) -> dict:
    return {
        "n": len(values),
        "rate": round(sum(values) / len(values), 3) if values else None,
        "wilson_95": wilson(sum(values), len(values)),
    }


def main() -> None:
    path = sorted(glob.glob("data/eval/results/real_eval_*_full.jsonl"))[-1]
    rows = [json.loads(line) for line in open(path)]
    people = real_data.load_pmdata() | real_data.choose_lifesnaps(real_data.load_lifesnaps())
    items = [
        q for name, frame in sorted(people.items()) for q in real_eval.questions_for(name, frame)
    ]
    items += real_eval.edge_cases(people)
    keys = {(i["person"], i["kind"], i["q"]): i for i in items}

    done, kinds, both = [], defaultdict(list), []
    alarms = {"agent": [], "plain_chatbot": []}
    found = {"agent": [], "plain_chatbot": []}
    for row in rows:
        item = keys[(row["person"], row["kind"], row["q"])]
        refused = row["stop"] == "refused"
        hit = regraded(item, row["agent"], row["read"], refused)
        if hit is None:
            continue
        done.append((row["person"], hit))
        kinds[row["kind"]].append(hit)
        other = None
        if "plain" in row:
            other = regraded(item, row["plain"], row["plain_read"], False)
            both.append((hit, other))
        verdict = item["want"].get("direction", item["want"].get("link"))
        if verdict is None or row["kind"] == "planted":
            continue
        group = alarms if verdict == "none" else found
        group["agent"].append(hit)
        if other is not None:
            group["plain_chatbot"].append(other)

    power, wrong_way = [], 0
    for item in items:
        if item["kind"] != "planted":
            continue
        frame, way = real_eval.plant(
            people[item["person"]], item["metric"], random.Random(f"503:{item['person']}:plant")
        )
        verdict = oracle.change(frame, item["metric"], frame.index.max(), 14, 28)
        power.append(verdict == way)
        wrong_way += verdict not in (way, "none", None)

    numeric = [h for k, v in kinds.items() if k in real_eval.WEIGHTS for h in v]
    summary = {
        "note": "Regraded with the same rule for both systems; see real_eval_*_full.json for the "
        "first score (0.777 agent, 0.604 plain on shared questions).",
        "agent_all": rate([h for _, h in done]) | {"by_person_95": by_person_interval(done)},
        "agent_data_questions_only": rate(numeric),
        "by_kind": {k: rate(v) for k, v in sorted(kinds.items())},
        "same_questions": {
            "agent": rate([a for a, _ in both]),
            "plain_chatbot": rate([b for _, b in both]),
            "only_agent_right": sum(a and not b for a, b in both),
            "only_plain_right": sum(b and not a for a, b in both),
        },
        "correct_when_key_says_no_effect": {k: rate(v) for k, v in alarms.items()},
        "correct_when_key_says_an_effect": {k: rate(v) for k, v in found.items()},
        "planted_change_found_by_the_answer_key": rate(power) | {"opposite": wrong_way},
        "mean_hit_per_person": round(
            statistics.mean(
                statistics.mean(h for p, h in done if p == name) for name in {p for p, _ in done}
            ),
            3,
        ),
    }
    out = Path(
        path.replace("data/eval/results", "eval/results").replace(".jsonl", "_regraded.json")
    )
    out.write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
