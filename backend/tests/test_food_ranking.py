"""USDA's matches ranked by meaning, then the food described picked by a model; each step falls
back to the one before when it fails, and the values always stay USDA's."""

from app.agent.llm import LLMError
from app.outside import FoodData, by_meaning


def entries(*names: str) -> list[dict]:
    return [{"food": n, "per_100g": {"energy_kcal": float(i)}} for i, n in enumerate(names)]


def embed_by_shared_letters(texts: list[str]) -> list[list[float]]:
    """A stand-in for embeddings: texts sharing more words come out closer."""
    vocabulary = sorted({w for t in texts for w in t.lower().replace(",", " ").split()})
    return [[float(w in t.lower()) for w in vocabulary] for t in texts]


def data(found: list[dict], embed=None, choose=None) -> FoodData:
    class Fixed(FoodData):
        def candidates(self, query: str) -> list[dict]:
            return [dict(e) for e in found]

    return Fixed("key", None, embed, choose)


FOUND = entries("Bratwurst, chicken, cooked", "Rice noodles, cooked", "Chicken, breast, roasted")


def test_matches_are_ordered_by_meaning():
    ranked = by_meaning("roasted chicken breast", FOUND, embed_by_shared_letters)
    assert ranked[0]["food"] == "Chicken, breast, roasted"


def test_the_models_choice_comes_first_and_the_values_stay_usdas():
    chooser = data(FOUND, None, lambda q, names: 2)
    assert chooser.search("chicken")[0] == FOUND[2]  # the third, with its own values
    ranked_then_picked = data(FOUND, embed_by_shared_letters, lambda q, names: 0)
    assert ranked_then_picked.search("roasted chicken breast")[0] == FOUND[2]


def test_each_step_falls_back_when_it_fails_or_finds_nothing():
    def broken(*_):
        raise LLMError("down")

    assert data(FOUND, broken, broken).search("chicken")[0] == FOUND[0]  # USDA's own order
    assert data(FOUND, None, lambda q, names: None).search("chicken")[0] == FOUND[0]
    assert data(FOUND, None, lambda q, names: 99).search("chicken")[0] == FOUND[0]
    assert len(data(FOUND).search("chicken")) == 3
