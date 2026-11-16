"""Scores a stored conversation-evaluation run again with the current judge, without asking the
agent anything: `PYTHONPATH=backend:eval python eval/rejudge.py <run.jsonl>`. Lets runs made before
a judge change be compared with runs made after it. Costs only the judge's calls (about $0.04)."""

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from app.agent.llm import OpenAILLM, SpendLedger
from app.config import settings
from conversation_eval import judge


def kept_before(rows: list[dict], turns: dict) -> list[list[str]]:
    """What had been kept at each turn: rows from before `kept` was recorded rebuild it from the
    cards raised on turns the set marks to keep."""
    kept, out = [], []
    for row in rows:
        out.append(list(row.get("kept", kept)))
        if turns.get((row["conversation"], row["m"]), {}).get("keep") and row.get(
            "new_cards"
        ):
            kept = [row["new_cards"][0], *kept]
    return out


def main(path: str) -> None:
    rows = [json.loads(line) for line in Path(path).read_text().splitlines()]
    sets = json.loads((Path(__file__).parent / "conversation_set.json").read_text())
    turns = {(c["name"], t["m"]): t for c in sets["conversations"] for t in c["turns"]}
    spend = SpendLedger(cap_usd=0.15)
    llm = OpenAILLM.from_settings(settings, spend)
    history = defaultdict(list)
    for row, kept in zip(rows, kept_before(rows, turns), strict=True):
        row["judge"] = judge(
            llm, history[row["conversation"]], row["m"], row["reply"], kept
        )
        history[row["conversation"]].append((row["m"], row["reply"]))
    out = Path(path).with_name(Path(path).stem + "_rejudged.jsonl")
    out.write_text("".join(json.dumps(r) + "\n" for r in rows))
    scores = [r["judge"] for r in rows]
    means = {
        k: round(float(np.mean([s[k] for s in scores if isinstance(s.get(k), int)])), 2)
        for k in ("sound", "context", "natural", "honest")
    }
    print(
        json.dumps(
            {
                "means": means,
                "below_4_sound": sum(s.get("sound", 5) < 4 for s in scores),
                "judge_usd": round(spend.spent_usd, 4),
                "out": str(out),
            }
        )
    )


if __name__ == "__main__":
    main(sys.argv[1])
