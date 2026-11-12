"""What is stored about each answer: how it went, how long it took, and the steps that led to it.

The agents already record every step in memory (`AgentResult.trace`, `TeamReply.trace`); this
reduces a run to the figures the operations report counts (outcome, latency per stage, calls,
errors, repairs, rejections) and keeps the steps, so a stored answer can be traced after a restart.
Pure functions: the API measures the wall-clock time and stores what these return.
"""

from collections.abc import Iterator

from app.agent.agent import NO_ANSWER, AgentResult
from app.db.models import TRACE_OUTCOMES as OUTCOMES  # how an answer ended, from the asker's side

__all__ = ["OUTCOMES", "failed_trace", "personal_trace", "team_trace"]

_REFUSALS = {"refused", "urgent"}
_FAILURES = {"model_error", "no_submission", "unavailable"}


def _walk(steps: list[dict]) -> Iterator[dict]:
    """Every step, including those of a consulted expert's run, which nests its own."""
    for step in steps:
        yield step
        nested = step.get("steps")
        if isinstance(nested, list):
            yield from _walk(nested)


def _seconds(steps: list[dict], kind: str) -> float:
    return sum(float(s.get("latency_s") or 0.0) for s in steps if s.get("type") == kind)


def _ms(seconds: float) -> int:
    return max(0, round(seconds * 1000))


def personal_trace(result: AgentResult, latency_s: float, *, refused: bool = False) -> dict:
    """The stored record of one personal answer. `latency_s` is the wall-clock time of `ask()`."""
    steps = list(_walk(result.trace))
    nested = [s for top in result.trace for s in _walk(top.get("steps") or [])]
    checks = [s for s in result.trace if s.get("type") == "verify"]
    fell_back = bool(checks and checks[-1].get("summary_problems"))
    stop = result.stop_reason
    if refused or stop in _REFUSALS:
        outcome = "refused"
    elif stop == "budget":
        outcome = "budget"
    elif stop in _FAILURES and not result.claims:
        outcome = "failed"
    elif fell_back or result.summary == NO_ANSWER:
        outcome = "failed_checks"
    elif result.uncovered or stop in _FAILURES:
        outcome = "answered_in_part"
    else:
        outcome = "answered"
    model_s = _seconds(steps, "llm")
    router_s = _seconds(steps, "route")
    guard_s = _seconds(steps, "guard")
    route = next((s for s in result.trace if s.get("type") == "route"), {})
    return {
        "outcome": outcome,
        "stop_reason": stop,
        "question_type": route.get("question_type"),
        "latency_ms": _ms(latency_s),
        "stages_ms": {
            "model": _ms(model_s),
            "router": _ms(router_s),
            "guard": _ms(guard_s),
            # Tools, the database and the checks: what the wall clock spent outside services.
            "other": _ms(latency_s - model_s - router_s - guard_s),
        },
        "model_calls": result.budget.calls
        + sum(1 for s in nested if s.get("type") == "llm")
        + sum(1 for s in steps if s.get("type") == "reword"),
        # The budget also charges handing in and recording hypotheses: only chosen tools count.
        "tool_calls": max(
            0,
            result.budget.tool_calls
            - sum(1 for s in result.trace if s.get("type") in ("verify", "submit", "hypotheses")),
        )
        + sum(1 for s in nested if s.get("type") == "tool"),
        "tool_errors": sum(
            1 for s in steps if s.get("error") and s.get("type") not in ("route", "guard", "llm")
        ),
        # Every check after the first is a repair: the run was sent back to fix what failed.
        "repair_rounds": max(0, len(checks) - 1),
        "rejected_claims": sum(len(s.get("rejected") or ()) for s in checks),
        "summary_fell_back": fell_back,
        "guard_down": any(s.get("type") == "guard" and s.get("error") for s in steps),
        "cost_usd": round(result.budget.cost_usd, 6),
        "steps": result.trace,
    }


def failed_trace(latency_s: float) -> dict:
    """An answer that raised before it had a result: only its time and the outcome are known."""
    return {
        "outcome": "failed",
        "stop_reason": "error",
        "latency_ms": _ms(latency_s),
        "stages_ms": {"other": _ms(latency_s)},
    }


# The team agent's stop reasons (`TeamReply.stop`) and what they mean for the supervisor.
_TEAM_OUTCOMES = {
    "answered": "answered",
    "answered_in_part": "answered_in_part",
    "about_a_person": "refused",
    "medical": "refused",
    "no_answer": "failed",
    "noted": "answered",  # told something, and noted it or replied
    "not_saved": "refused",  # a note about a person, someone's health, or an instruction
    "about_me": "refused",  # the supervisor's own memory is not the team's
    "subgroup": "refused",  # part of the team, compared with the rest
    "paused": "refused",  # two of the supervisor's teams differ by too few people
}


def team_trace(stop: str, trace: list[dict], cost_usd: float, latency_s: float) -> dict:
    """The stored record of one team-agent answer, from its `TeamReply` fields."""
    errors = [s for s in trace if s.get("error")]
    model_s = sum(float(s.get("latency_s") or 0.0) for s in trace if "model" in s)
    checks = [s for s in trace if "answer" in s]
    outcome = _TEAM_OUTCOMES.get(stop, "failed")
    if outcome == "failed" and any(s.get("error") == "BudgetExceeded" for s in trace):
        outcome = "budget"
    return {
        "outcome": outcome,
        "stop_reason": stop,
        "question_type": None,
        "latency_ms": _ms(latency_s),
        "stages_ms": {"model": _ms(model_s), "other": _ms(latency_s - model_s)},
        "model_calls": sum(1 for s in trace if "model" in s),
        "tool_calls": sum(1 for s in trace if "tool" in s),
        "tool_errors": sum(1 for s in errors if "tool" in s),
        "repair_rounds": max(0, len(checks) - 1),
        "rejected_claims": sum(len(s.get("rejected") or ()) for s in trace),
        "summary_fell_back": False,
        "guard_down": False,
        "cost_usd": round(cost_usd, 6),
        "steps": trace,
    }
