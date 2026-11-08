"""Finding the passages that answer a question: exact words and meaning, merged.

BM25 finds rare exact words ("Romanian deadlift"); embeddings find meaning across different words
("I sit at a desk all day" and "breaking up long sitting"). They are merged by reciprocal rank, with
meaning counted more because it ranked better when measured (`eval/rag_eval.py`). A thousand
passages are searched in memory with
NumPy: a vector database would add a service and a Postgres extension to save nothing at this size.

Passages are quoted data, never instructions. A question on what is off limits finds nothing, and a
weak best match returns nothing, so an answer never leans on a passage that is merely the closest.
Without the embeddings API the search still works, on words alone, and says so.
"""

import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.agent.llm import LLM, Budget, LLMError
from app.agent.verifier import MEDICAL
from app.knowledge.build import EVERYDAY, OFF_LIMITS, Passage

INDEX_DIR = Path(__file__).parent.parent / "knowledge" / "index"
TOP = 50  # how far down each list the merge looks
RRF_K = 60  # the usual constant: rank 1 counts little more than rank 5, so neither list dominates
MEANING_WEIGHT = 2.0  # how much more a place in the meaning list counts than one in the words list
BM25_K1, BM25_B = 1.5, 0.75
MIN_COSINE = 0.38  # below this the best passage is only the closest, not an answer
MIN_WORD_SHARE = 0.6  # without vectors, how much of the question the best passage must contain
AREAS = {
    "sleep": ("sleep", "recovery"),
    "recovery": ("recovery", "sleep"),
    "activity": ("activity", "exercise"),
    "nutrition": ("nutrition",),
}
STOP = set(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "get",
        "got",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "should",
        "so",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "they",
        "this",
        "to",
        "up",
        "was",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "about",
        "much",
        "many",
        "some",
        "any",
        "more",
        "most",
        "very",
        "just",
        "really",
        "good",
        "best",
        "need",
        "want",
        "try",
    ]
)
WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    """Words that say what a text is about, with common endings taken off."""
    found = []
    for word in WORD.findall(text.lower()):
        if word in STOP or len(word) < 2:
            continue
        for ending in ("ing", "ed", "es", "s"):
            if word.endswith(ending) and len(word) - len(ending) >= 3:
                word = word[: -len(ending)]
                break
        found.append(word)
    return found


@dataclass(frozen=True)
class Found:
    passage: Passage
    score: float  # for the trace; not comparable between methods


@dataclass
class Retrieved:
    found: list[Found] = field(default_factory=list)
    method: str = "hybrid"  # hybrid, words (no embeddings), or refused
    widened: bool = False  # nothing fit in the expert's own area
    best_cosine: float | None = None

    def trace(self, query: str) -> dict:
        return {
            "type": "retrieval",
            "query": query[:200],
            "method": self.method,
            "widened": self.widened,
            "best_cosine": None if self.best_cosine is None else round(self.best_cosine, 3),
            "passages": [{"id": f.passage.id, "score": round(f.score, 4)} for f in self.found],
        }


class Index:
    def __init__(self, passages: Sequence[Passage], vectors: np.ndarray | None):
        self.passages = list(passages)
        self.vectors = vectors
        self.areas = np.array([p.area for p in self.passages])
        documents = [Counter(tokens(f"{p.title} {p.title} {p.text}")) for p in self.passages]
        self.lengths = np.array([sum(d.values()) for d in documents], dtype=float)
        self.average = float(self.lengths.mean()) if len(documents) else 1.0
        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for at, document in enumerate(documents):
            for word, count in document.items():
                postings[word].append((at, count))
        self.postings = postings

    def bm25(self, words: Sequence[str]) -> np.ndarray:
        scores = np.zeros(len(self.passages))
        total = len(self.passages)
        for word in set(words):
            posting = self.postings.get(word)
            if not posting:
                continue
            idf = math.log(1 + (total - len(posting) + 0.5) / (len(posting) + 0.5))
            for at, count in posting:
                norm = 1 - BM25_B + BM25_B * self.lengths[at] / self.average
                scores[at] += idf * count * (BM25_K1 + 1) / (count + BM25_K1 * norm)
        return scores

    def covers(self, at: int, words: Sequence[str]) -> float:
        """The share of the question's words this passage contains."""
        unique = set(words)
        held = {word for word in unique if any(a == at for a, _ in self.postings.get(word, ()))}
        return len(held) / len(unique) if unique else 0.0


def load_passages(path: Path) -> list[Passage]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [
        Passage(
            **{**r, "metrics": tuple(r.get("metrics", ())), "levers": tuple(r.get("levers", ()))}
        )
        for r in rows
    ]


@lru_cache(maxsize=1)
def load_index() -> Index:
    vectors_path = INDEX_DIR / "vectors.npy"
    vectors = np.load(vectors_path) if vectors_path.exists() else None
    return Index(load_passages(INDEX_DIR / "passages.jsonl"), vectors)


def off_limits(question: str) -> bool:
    plain = EVERYDAY.sub("", question)
    return bool(MEDICAL.search(plain) or OFF_LIMITS.search(plain))


def _ranked(scores: np.ndarray, allowed: np.ndarray) -> list[int]:
    order = np.argsort(-scores, kind="stable")
    return [int(i) for i in order if allowed[i] and scores[i] > 0][:TOP]


def _query_vector(llm: LLM, question: str, budget: Budget | None) -> np.ndarray | None:
    try:
        embedded = llm.embed([question], budget=budget)
    except LLMError:
        return None
    return np.asarray(embedded.vectors[0], dtype=np.float32)


def search(
    question: str,
    *,
    llm: LLM | None = None,
    budget: Budget | None = None,
    area: str | None = None,
    k: int = 3,
    index: Index | None = None,
    use_words: bool = True,
    use_vectors: bool = True,
) -> Retrieved:
    """The best `k` passages, in the routed expert's area if `area` is given, and everywhere if
    nothing there fits."""
    if off_limits(question):
        return Retrieved(method="refused")
    index = index or load_index()
    words = tokens(question)
    query = None
    if llm is not None and use_vectors and index.vectors is not None:
        query = _query_vector(llm, question, budget)
    cosines = None if query is None else index.vectors @ query
    keyword = index.bm25(words) if use_words else np.zeros(len(index.passages))

    def attempt(allowed: np.ndarray) -> tuple[list[Found], float | None]:
        lists = [(1.0, _ranked(keyword, allowed))] if use_words else []
        if cosines is not None:
            lists.append((MEANING_WEIGHT, _ranked(cosines, allowed)))
        merged: dict[int, float] = defaultdict(float)
        for weight, ranked in lists:
            for rank, at in enumerate(ranked):
                merged[at] += weight / (RRF_K + rank + 1)
        best = sorted(merged, key=lambda at: (-merged[at], at))
        cosine = None if cosines is None or not allowed.any() else float(cosines[allowed].max())
        strong = (
            cosine >= MIN_COSINE
            if cosine is not None
            else bool(best) and index.covers(best[0], words) >= MIN_WORD_SHARE
        )
        return (
            [Found(index.passages[at], merged[at]) for at in best[:k]] if strong else []
        ), cosine

    wanted = AREAS.get(area or "")
    everywhere = np.ones(len(index.passages), dtype=bool)
    allowed = np.isin(index.areas, wanted) if wanted else everywhere
    found, cosine = attempt(allowed)
    widened = False
    if not found and wanted:
        found, cosine = attempt(everywhere)
        widened = bool(found)
    method = (
        "hybrid"
        if cosines is not None and use_words
        else "vectors"
        if cosines is not None
        else "words"
    )
    return Retrieved(found, method, widened, cosine)
