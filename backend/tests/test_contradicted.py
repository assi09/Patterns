"""A summary may not say the opposite of the run's own tests (the audit of 2026-11-18): "time
asleep showed no clear change" over a clear drop, or an opening "sleep increased"."""

import pytest
from test_broad_questions import END, ON, Router, planted, submit

from app.agent.ask import ask
from app.agent.llm import ScriptedLLM
from app.agent.strategy import overview_evidence
from app.agent.verifier import contradicted
from app.synthetic import Step


@pytest.fixture(scope="module")
def sleep_fell():
    return planted(Step("sleep_minutes", ON, -70.0), seed=7)


@pytest.fixture(scope="module")
def evidence(sleep_fell):
    records, _ = overview_evidence(sleep_fell, "anything different lately?", END)
    asleep = [e for e in records if e.metrics[0] == "sleep_minutes"]
    assert asleep and asleep[0].stats.get("overview_rank")  # the drop is clear
    return records


@pytest.mark.parametrize(
    "summary",
    [
        "Time asleep and sleep efficiency both showed no clear change.",
        "Your time asleep held steady.",
        "Time asleep increased over the last two weeks.",
        "You slept longer recently.",
    ],
)
def test_saying_the_opposite_of_a_clear_drop_is_sent_back(evidence, summary):
    assert contradicted(summary, evidence)


@pytest.mark.parametrize(
    "summary",
    [
        "Time asleep went down from 6 h 52 min to 5 h 49 min.",
        "You slept less recently, while steps held steady.",
        "Hold a plank for 30 seconds, keeping your hips level.",  # guidance: no statistic
        "Ready to log: a 35 min walk at 18:15.",
        "I'll remind you at 22:30.",
    ],
)
def test_what_agrees_or_is_not_about_a_tested_metric_passes(evidence, summary):
    assert contradicted(summary, evidence) == []


def test_a_metric_whose_tests_disagree_may_be_described_either_way(evidence, sleep_fell):
    """Steady this week but changed over the weeks before: both can be true, so neither wording is
    a contradiction."""
    last_days, _ = overview_evidence(sleep_fell, "anything different in the last 3 days?", END)
    short = [e for e in last_days if e.metrics[0] == "sleep_minutes"]
    unclear = short[0].model_copy(update={"stats": {**short[0].stats, "p_value_run_adjusted": 0.4}})
    both = [*evidence, unclear]
    assert contradicted("Your time asleep held steady over the last 3 days.", both) == []


def test_the_answer_saying_no_change_over_a_clear_drop_is_turned_back(sleep_fell):
    """Through ask(): the first summary is sent back with the reason, the second is kept."""
    wrong = submit("Time asleep showed no clear change.")
    right = submit("Time asleep went down.")
    llm = ScriptedLLM([wrong, right])
    reply = ask(llm, Router("change"), sleep_fell, "Anything different lately?", today=END)
    sent_back = llm.requests[1]["messages"][-1]["content"]
    assert "time asleep (called steady)" in sent_back
    # An overview's answer is then said by code from its tests, each cited (findings.py).
    assert "Time asleep went down" in reply.result.summary
    assert "no clear change" not in reply.result.summary.split("Time asleep")[1].split(".")[0]
