"""The rules a fact must meet to be proposed, shared by the agent's tool and the memory store.

A fact is something the person told the agent about themselves (a routine, goal, preference,
context, a dated event or a commitment), at most 120 characters, about known metrics, and never
text that reads like an instruction or names a condition. It is kept only once the person approves
it.
"""

from collections.abc import Iterable

from app.agent.present import METRICS
from app.agent.sanitize import clean, reads_like_instruction
from app.agent.verifier import MEDICAL

FACT_KINDS = ("routine", "goal", "preference", "context", "event", "commitment")
MAX_FACT_CHARS = 120


class FactRejected(ValueError):
    """A fact the rules do not allow; the message is safe to show, also to the model."""


def validate_fact(kind: str, text: str, metrics: Iterable[str] = ()) -> tuple[str, list[str]]:
    """The fact's cleaned text and metrics, or `FactRejected` with the reason."""
    if kind not in FACT_KINDS:
        raise FactRejected(f"A fact is one of: {', '.join(FACT_KINDS)}.")
    cleaned = clean(text, 10 * MAX_FACT_CHARS)
    if not cleaned:
        raise FactRejected("A fact needs text.")
    if len(cleaned) > MAX_FACT_CHARS:
        raise FactRejected(f"A fact is at most {MAX_FACT_CHARS} characters.")
    if reads_like_instruction(cleaned):
        raise FactRejected("This reads like an instruction, so it is not kept as a fact.")
    if MEDICAL.search(cleaned):
        raise FactRejected("Patterns does not keep medical details.")
    concerned = list(dict.fromkeys(metrics))
    if unknown := [m for m in concerned if m not in METRICS]:
        raise FactRejected(f"Unknown metrics: {', '.join(unknown)}.")
    return cleaned, concerned
