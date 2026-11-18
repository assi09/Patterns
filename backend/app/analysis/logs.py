"""Read confirmed food entries supplied by the account-scoped store; no inferred meals."""

import math
from collections.abc import Sequence
from datetime import datetime

from app.analysis.evidence import Evidence, Window


def food_entries(
    entries: Sequence[dict], window: Window, zone, meal_type: str | None = None
) -> Evidence:
    selected = []
    for entry in entries:
        if meal_type is not None and entry.get("mealType") != meal_type:
            continue
        try:
            moment = datetime.fromisoformat(entry["consumedAt"])
            if (
                moment.tzinfo is None
                or not window.start <= moment.astimezone(zone).date() <= window.end
            ):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        selected.append(entry)
    totals, measured = {}, {}
    for field in ("energyKcal", "proteinG", "carbohydrateG", "fatG"):
        values = [
            e[field]
            for e in selected
            if isinstance(e.get(field), (int, float))
            and not isinstance(e[field], bool)
            and math.isfinite(e[field])
        ]
        totals[field] = round(sum(values), 4) if values else None
        measured[field] = len(values)
    return Evidence(
        tool="food_log",
        metrics=("food_logs",),
        windows=(window,),
        n=len(selected),
        sufficient=True,
        stats={
            "meals_logged": len(selected),
            "totals": totals,
            "entries_with_values": measured,
            "names": [str(e.get("foodName", "food")) for e in selected],
            "meal_type": meal_type,
        },
    )
