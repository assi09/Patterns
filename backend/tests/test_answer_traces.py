"""What is stored about each answer: the outcome and the counts read from the agent's trace."""

import pytest

from app.agent.agent import NO_ANSWER, AgentResult
from app.agent.llm import Budget
from app.agent.trace import OUTCOMES, failed_trace, personal_trace, team_trace
from app.agent.verifier import Claim


def claim() -> Claim:
    return Claim(text="Time asleep held steady.", kind="no_change", evidence_ids=["e1"])


def verify(rejected: int = 0, summary_problems=()) -> dict:
    return {
        "type": "verify",
        "accepted": 1,
        "rejected": [{"text": "x", "reasons": ["y"]}] * rejected,
        "summary_problems": list(summary_problems),
        "uncovered": [],
    }


def result(stop: str = "submitted", trace=(), claims=None, **fields) -> AgentResult:
    return AgentResult(
        run_id="r1",
        stop_reason=stop,
        summary="Here is what I found.",
        claims=[claim()] if claims is None else list(claims),
        trace=list(trace),
        **fields,
    )


ROUTE = {"type": "route", "question_type": "trend", "latency_s": 0.1}
LLM = {"type": "llm", "latency_s": 1.0, "cost_usd": 0.001}


def test_a_clean_answer_is_answered_with_its_time_split_by_stage():
    record = personal_trace(result(trace=[ROUTE, LLM, LLM, verify()]), 3.0)
    assert record["outcome"] == "answered" and record["question_type"] == "trend"
    assert record["latency_ms"] == 3000
    assert record["stages_ms"] == {"model": 2000, "router": 100, "guard": 0, "other": 900}
    assert record["repair_rounds"] == 0 and record["rejected_claims"] == 0
    assert record["steps"][0] == ROUTE


@pytest.mark.parametrize(
    "made, refused, outcome",
    [
        (result(stop="refused", claims=()), False, "refused"),
        (result(stop="urgent", claims=()), False, "refused"),
        (result(), True, "refused"),  # the router refused: the API knows, the run may not
        (result(stop="budget"), False, "budget"),
        (result(stop="model_error", claims=()), False, "failed"),
        (result(stop="no_submission", claims=()), False, "failed"),
        (result(stop="model_error"), False, "answered_in_part"),  # claims verified before it
        (result(trace=[verify(summary_problems=["x"])]), False, "failed_checks"),
        (result(uncovered=["activity"]), False, "answered_in_part"),
    ],
)
def test_every_way_an_answer_ends_has_one_outcome(made, refused, outcome):
    assert personal_trace(made, 1.0, refused=refused)["outcome"] == outcome
    assert outcome in OUTCOMES


def test_no_answer_after_the_checks_is_a_failed_check():
    made = result(trace=[verify(rejected=2)], claims=())
    made.summary = NO_ANSWER
    assert personal_trace(made, 1.0)["outcome"] == "failed_checks"


def test_repairs_rejections_and_tool_errors_are_counted():
    trace = [
        {"type": "tool", "name": "describe", "error": "unknown metric"},
        {"type": "tool", "name": "describe", "evidence_id": "e1"},
        {"type": "submit", "error": "claims: field required"},
        verify(rejected=2, summary_problems=["overstated"]),
        verify(rejected=1),
        {"type": "guard", "error": "Jev down"},
        {"type": "route", "error": "timeout"},  # a service outage, not a tool error
    ]
    record = personal_trace(result(trace=trace), 1.0)
    assert record["tool_errors"] == 2
    assert record["repair_rounds"] == 1 and record["rejected_claims"] == 3
    assert record["guard_down"] is True and record["summary_fell_back"] is False


def test_a_consulted_experts_own_calls_are_counted_too():
    consult = {
        "type": "consult",
        "expert": "activity",
        "steps": [LLM, LLM, {"type": "tool", "name": "describe", "evidence_id": "e2"}],
    }
    made = result(
        trace=[LLM, consult, {"type": "reword", "problems": []}, verify()],
        budget=Budget(calls=2, tool_calls=2),  # the consult, and handing in
    )
    record = personal_trace(made, 4.0)
    assert record["model_calls"] == 2 + 2 + 1  # its own, the expert's, the reword
    assert record["tool_calls"] == 1 + 1
    assert record["stages_ms"]["model"] == 3000


def test_time_outside_services_is_never_negative():
    assert personal_trace(result(trace=[LLM, LLM]), 0.5)["stages_ms"]["other"] == 0


def test_a_run_that_raised_is_a_failure_with_its_time():
    record = failed_trace(2.5)
    assert record["outcome"] == "failed" and record["latency_ms"] == 2500


@pytest.mark.parametrize(
    "stop, outcome",
    [
        ("answered", "answered"),
        ("answered_in_part", "answered_in_part"),
        ("about_a_person", "refused"),
        ("medical", "refused"),
        ("no_answer", "failed"),
        ("something_new", "failed"),
    ],
)
def test_the_team_agents_stops_map_to_the_same_outcomes(stop, outcome):
    assert team_trace(stop, [], 0.0, 1.0)["outcome"] == outcome


def test_a_team_answer_out_of_budget_says_so_and_counts_its_steps():
    trace = [
        {"model": "m", "latency_s": 0.8, "cost_usd": 0.001},
        {"tool": "team_overview", "error": None},
        {"tool": "team_week", "error": "too few members"},
        {"model": "m", "latency_s": 0.7, "cost_usd": 0.001},
        {"rejected": ["claim 1: x", "summary: y"]},
        {"answer": "rejected"},
        {"answer": "rejected"},
        {"error": "BudgetExceeded"},
    ]
    record = team_trace("no_answer", trace, 0.002, 2.0)
    assert record["outcome"] == "budget"
    assert record["model_calls"] == 2 and record["tool_calls"] == 2 and record["tool_errors"] == 1
    assert record["repair_rounds"] == 1 and record["rejected_claims"] == 2
    assert record["stages_ms"] == {"model": 1500, "other": 500}
