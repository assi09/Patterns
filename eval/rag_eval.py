"""How well each search finds the right passage. Run from the repository root:
`PYTHONPATH=backend python eval/rag_eval.py [--final]`. About a thousandth of a dollar.

Scores the labelled questions in `rag_set.json`: Recall@1, @3, @5 and MRR, for the old keyword
cards, words alone, meaning alone, both, and both within the expert's area; and how often a question the
passages cannot answer finds nothing. A quarter of the questions are held out: tune on the rest, and
pass `--final` once, at the end. `--set FILE` scores every question of another labelled set (such
as the second held-out set, `rag_heldout_2026-11-16.json`) and saves the totals to `eval/results`.
"""

import json
import sys
from pathlib import Path

from app.agent.knowledge import load_cards, rank_cards
from app.agent.llm import OpenAILLM
from app.agent.retrieval import load_index, search
from app.config import settings

SET = json.loads((Path(__file__).parent / "rag_set.json").read_text())


def relevant(passage, item) -> bool:
    if item.get("source") and not passage.source.startswith(item["source"]):
        return False
    title, text = passage.title.lower(), passage.text.lower()
    return any(t in title for t in item.get("titles", ())) or any(
        t in text for t in item.get("text", ())
    )


def score(ranks: list[int | None]) -> dict:
    n = len(ranks)
    return {
        "recall@1": round(sum(r == 1 for r in ranks) / n, 3),
        "recall@3": round(sum(r is not None and r <= 3 for r in ranks) / n, 3),
        "recall@5": round(sum(r is not None and r <= 5 for r in ranks) / n, 3),
        "mrr": round(sum(1 / r for r in ranks if r) / n, 3),
    }


def rank(found, item) -> int | None:
    return next((i + 1 for i, p in enumerate(found) if relevant(p, item)), None)


def main() -> None:
    final = "--final" in sys.argv
    other = sys.argv[sys.argv.index("--set") + 1] if "--set" in sys.argv else None
    labelled = json.loads(Path(other).read_text()) if other else SET
    llm = OpenAILLM.from_settings(settings)
    load_index()
    answerable = [q for q in labelled["questions"] if not q.get("none")]
    chosen = (
        answerable
        if other
        else [q for i, q in enumerate(answerable) if (i % 4 == 3) == final]
    )
    methods = {
        "words": {"use_vectors": False},
        "meaning": {"use_words": False},
        "both": {},
    }
    results: dict = {}
    cards = load_cards()
    ranks = []
    for item in chosen:
        found = rank_cards(item["q"], (), cards)
        wanted = item.get("titles", ())
        titles = [c.title.lower() for c in found]
        ranks.append(
            next(
                (i + 1 for i, t in enumerate(titles) if any(w in t for w in wanted)),
                None,
            )
        )
    results["old cards"] = score(ranks)
    misses: list = []
    for name, options in methods.items():
        ranks = []
        for item in chosen:
            done = search(item["q"], llm=llm, k=5, **options)
            ranks.append(rank([f.passage for f in done.found], item))
        results[name] = score(ranks)
    ranks = []
    for item in chosen:
        done = search(item["q"], llm=llm, k=5, area=item["area"])
        at = rank([f.passage for f in done.found], item)
        ranks.append(at)
        if at is None or at > 3:
            misses.append(
                {"q": item["q"], "got": [f.passage.title[:40] for f in done.found[:3]]}
            )
    results["both, in the expert's area"] = score(ranks)
    empty = [q for q in labelled["questions"] if q.get("none")]
    silent = sum(not search(q["q"], llm=llm).found for q in empty)
    refused = sum(not search(q, llm=llm).found for q in labelled["medical"])
    print(other or ("HELD OUT" if final else "TUNING SET"), len(chosen), "questions")
    print(json.dumps(results, indent=1))
    print(f"no answer found for unanswerable questions: {silent}/{len(empty)}")
    print(f"medical questions returning nothing: {refused}/{len(labelled['medical'])}")
    if other:
        out = Path("eval/results") / f"rag_eval_{Path(other).stem}.json"
        totals = {"questions": len(chosen), "scores": results, "misses_top3": misses}
        totals |= {"unanswerable_silent": [silent, len(empty)]}
        totals |= {"medical_silent": [refused, len(labelled["medical"])]}
        out.write_text(json.dumps(totals, indent=1, ensure_ascii=False) + "\n")
    if not final:
        print("misses:", json.dumps(misses, indent=0)[:3500])


if __name__ == "__main__":
    main()
