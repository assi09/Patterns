"""Finding passages: words, meaning, their merge, and when to find nothing."""

import numpy as np
import pytest

from app.agent.llm import Budget, ScriptedLLM
from app.agent.retrieval import Index, load_index, off_limits, search, tokens
from app.knowledge.build import Passage


def passage(pid, title, text, area="sleep"):
    return Passage(pid, title, text, "A source", "https://example.com", "public", area, "guideline")


PASSAGES = [
    passage("dark", "A dark room", "Keep the bedroom dark and quiet at night."),
    passage(
        "nap", "Short naps", "A short nap in the early afternoon restores alertness.", "recovery"
    ),
    passage("dead", "Romanian Deadlift", "Hinge at the hips and lower the bar.", "exercise"),
    passage("walk", "Walking", "Walking most days builds fitness gradually.", "activity"),
]


@pytest.fixture
def index():
    llm = ScriptedLLM([])
    vectors = llm.embed([f"{p.title} {p.text}" for p in PASSAGES]).vectors
    return Index(PASSAGES, np.asarray(vectors, dtype=np.float32))


def test_tokens_drop_filler_and_endings():
    assert tokens("How do I keep walking?") == ["keep", "walk"]


def test_words_find_an_exact_name(index):
    done = search("romanian deadlift", index=index)
    assert done.found[0].passage.id == "dead" and done.method == "words"


def test_the_merge_finds_it_and_says_how(index):
    done = search("dark bedroom at night", llm=ScriptedLLM([]), index=index)
    assert done.found[0].passage.id == "dark" and done.method == "hybrid"


def test_no_embeddings_still_answers_from_words(index):
    done = search("dark bedroom", llm=ScriptedLLM(embeddings_fail=True), index=index)
    assert done.found[0].passage.id == "dark" and done.method == "words"


def test_a_question_the_passages_cannot_answer_finds_nothing(index):
    assert search("capital of France", llm=ScriptedLLM([]), index=index).found == []


def test_the_experts_area_comes_first_and_widens_when_empty(index):
    done = search("walking fitness", llm=ScriptedLLM([]), area="activity", index=index)
    assert done.found[0].passage.id == "walk" and not done.widened
    done = search("romanian deadlift hips bar", llm=ScriptedLLM([]), area="sleep", index=index)
    assert done.found[0].passage.id == "dead" and done.widened


@pytest.mark.parametrize(
    "question",
    [
        "what medication helps me sleep",
        "do I have sleep apnea",
        "supplements for recovery",
        "a plan to lose weight",
    ],
)
def test_what_is_off_limits_finds_nothing(question, index):
    done = search(question, llm=ScriptedLLM([]), index=index)
    assert done.method == "refused" and done.found == []


def test_a_medicine_ball_is_not_off_limits():
    assert not off_limits("how do I use a medicine ball")


def test_the_cost_of_a_query_is_charged_to_the_budget(index):
    class Priced(ScriptedLLM):
        def embed(self, texts, *, budget=None):
            done = super().embed(texts, budget=budget)
            if budget:
                budget.cost_usd += 0.001
            return done

    budget = Budget()
    search("dark room", llm=Priced([]), budget=budget, index=index)
    assert budget.cost_usd == pytest.approx(0.001) and budget.calls == 0


def test_the_trace_names_what_was_found(index):
    done = search("romanian deadlift", index=index)
    step = done.trace("romanian deadlift")
    assert step["type"] == "retrieval" and step["passages"][0]["id"] == "dead"


def test_the_committed_vectors_match_the_passages():
    index = load_index()
    assert index.vectors is not None and index.vectors.shape[0] == len(index.passages)
    norms = np.linalg.norm(index.vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=0.01)
