"""Where the last answer came from, from what that answer stored: never written by the model.

A guidance answer keeps the public passages it cited (`Turn.sources`); a data answer keeps the
results it computed (`Turn.request_state`), each with its metrics and days. "Where did that advice
come from?" had no place in the reading and was answered from saved memory (the Fitbit replay of
2026-11-22); this answers it from the answer itself.
"""

from collections.abc import Sequence
from datetime import date

from pydantic import ValidationError

from app.agent.context import Turn
from app.agent.present import label
from app.agent.requested import _when
from app.agent.requests import ResolvedPart

NO_EARLIER = "There's no earlier answer in this chat to say the source of."
NEITHER = "That last answer didn't draw on a public source or on your records."


def _names(sources: Sequence[dict]) -> str:
    named = list(dict.fromkeys(f"{s['title']} ({s['source']})" for s in sources))
    return named[0] if len(named) == 1 else f"{', '.join(named[:-1])} and {named[-1]}"


def _results(turn: Turn) -> list[ResolvedPart]:
    """The results the answer gave, as its request state stored them."""
    found = []
    for raw in turn.request_state.get("data", []) if turn.request_state else []:
        try:
            found.append(ResolvedPart.model_validate(raw))
        except ValidationError:
            continue
    return found


def _read(part: ResolvedPart, today: date) -> str:
    if part.operation == "food" or part.metrics == ["food_logs"]:
        what = "the meals you logged"
    elif part.every_metric or not part.metrics:
        what = "every measure in your records"
    else:
        names = [label(m) for m in part.metrics]
        what = names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
    when = " and ".join(_when(w, today) for w in part.windows) or "over all of your data"
    return f"{what} {when}"


def answer_source(history: Sequence[Turn], today: date) -> tuple[str, list[dict]]:
    """(the reply, the source links to show with it) for the last answer of the chat."""
    if not history:
        return NO_EARLIER, []
    last = history[-1]
    if last.sources:
        links = [dict(s) for s in last.sources]
        return (
            f"That came from {_names(links)}: general public guidance, not from your data.",
            links,
        )
    results = _results(last)
    if results and (last.evidence_ids or last.claims):
        reads = "; ".join(dict.fromkeys(_read(p, today) for p in results))
        return (
            f"That came from your own records: {reads}. The numbers were computed from them by "
            "code, and the evidence under that answer shows each one.",
            [],
        )
    return NEITHER, []
