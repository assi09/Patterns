"""A meal of several foods: each looked up with its own grams, and the total added up by code."""

import json

from app.agent.world import meal


class Foods:
    VALUES = {
        "chicken breast cooked": {
            "energy_kcal": 165,
            "protein_g": 31,
            "carbohydrate_g": 0,
            "fat_g": 3.6,
        },
        "white rice cooked": {
            "energy_kcal": 130,
            "protein_g": 2.7,
            "carbohydrate_g": 28,
            "fat_g": 0.3,
        },
    }

    def food(self, query, grams=None):
        values = self.VALUES.get(query)
        if values is None:
            return {"error": "Nothing found."}
        food = {"food": query.title(), "per_100g": dict(values)}
        if grams:
            food[f"for_{grams:g}g"] = {k: round(v * grams / 100, 1) for k, v in values.items()}
        return {"foods": [food], "source": "USDA FoodData Central"}


def test_each_food_is_scaled_and_the_meal_is_added_up_by_code():
    estimates: list[str] = []
    content, info = meal(
        Foods(),
        [
            {"query": "chicken breast cooked", "grams": 100},
            {"query": "white rice cooked", "grams": 150},
        ],
        estimates,
    )
    found = json.loads(content)
    assert info["found"] is True and len(estimates) == 2
    assert info["matched"] == ["Chicken Breast Cooked (100 g)", "White Rice Cooked (150 g)"]
    assert found["meal_total"] == {
        "energy_kcal": 360.0,
        "protein_g": 35.0,
        "carbohydrate_g": 42.0,
        "fat_g": 4.1,  # 3.6 + 0.45, rounded per food
    }


def test_a_food_without_grams_or_without_a_match_is_not_guessed():
    for items in (
        [{"query": "chicken breast cooked"}, {"query": "white rice cooked", "grams": 100}],
        [{"query": "mystery stew", "grams": 100}],
    ):
        content, info = meal(Foods(), items, [])
        assert info["found"] is False and "missing" in json.loads(content)
