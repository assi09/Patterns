"""Broad questions ("what changed most?", "why do I feel tired?", "how has life been?") name no
metric: code compares every metric first and ranks the clear changes, so the answer cannot be one
area the model happened to pick, and the checks hold it to that ranking. Made-up data."""

from datetime import date, timedelta

import pytest

from app.agent.agent import SUBMIT
from app.agent.ask import ask
from app.agent.intent import Intent
from app.agent.llm import Completion, ScriptedLLM, ToolCall, Usage
from app.agent.periods import asked_period, period, period_range
from app.agent.present import label
from app.agent.router import EXPERT_LABELS, LABELS, Classification
from app.agent.strategy import overview_evidence
from app.agent.verifier import attributed, ranked_problems
from app.analysis.day import with_scores
from app.synthetic import Step, generate

START = date(2026, 7, 1)
DAYS = 110
END = START + timedelta(days=DAYS - 1)
ON = END - timedelta(days=13)  # the last 14 days changed


def planted(*effects, seed=3):
    return with_scores(generate(START, DAYS, effects, seed=seed).frame)


class Router:
    def __init__(self, question_type):
        self.result = Classification(
            dict.fromkeys(LABELS, 0.0) | {"sleep": 0.9},
            dict.fromkeys(EXPERT_LABELS, 0.0),
            source="test",
            intent_probabilities={str(i): float(i == Intent.READ) for i in Intent},
            question_types={question_type: 1.0},
        )

    def classify(self, question, earlier=()):
        return self.result


def submit(summary="Done.", claims=()):
    call = ToolCall("submit", SUBMIT, {"summary": summary, "claims": list(claims)})
    return Completion(None, (call,), "scripted", Usage(), 0.0, 0.0)


@pytest.fixture(scope="module")
def steps_fell():
    return planted(Step("steps", ON, -5000.0))


@pytest.mark.parametrize(
    "question, kind",
    [
        ("What changed most lately?", "change"),
        ("Anything different about me recently?", "change"),
        ("Why do I feel so tired?", "why"),
        ("How am I doing?", "change"),
    ],
)
def test_a_broad_question_gets_every_metric_compared_first(steps_fell, question, kind):
    llm = ScriptedLLM([submit()])
    reply = ask(llm, Router(kind), steps_fell, question)
    task = llm.requests[0]["messages"][1]["content"]
    assert "Overview: all" in task and "corrected for testing them all at once" in task
    assert "1. steps" in task  # the planted change, ranked first
    assert "possible contributors" in task  # the guide for broad questions
    assert reply.route.action == "general"  # it spans areas, so no single-area expert answers it


@pytest.mark.parametrize(
    "question, kind",
    [("Has my resting heart rate changed lately?", "change"), ("Why is my sleep worse?", "why")],
)
def test_a_question_that_names_a_metric_keeps_its_own_path(steps_fell, question, kind):
    llm = ScriptedLLM([submit()])
    ask(llm, Router(kind), steps_fell, question)
    assert "Overview: all" not in llm.requests[0]["messages"][1]["content"]


def test_a_strong_change_ranks_first_across_seeds():
    firsts = 0
    for seed in range(12):
        records, _ = overview_evidence(
            planted(Step("steps", ON, -5000.0), seed=seed), "what changed most lately?", END
        )
        top = [r.metrics[0] for r in records if r.stats.get("overview_rank") == 1]
        firsts += top == ["steps"]
    assert firsts >= 11  # 12 of 12 when written


def test_with_nothing_planted_a_clear_change_is_rare():
    """The correction keeps chance from passing as a change: under no change, the share of people
    with any clear change stays near the 5% the correction allows."""
    seeds = 30
    with_any = sum(
        any(
            "overview_rank" in r.stats
            for r in overview_evidence(planted(seed=seed), "how has my life been lately?", END)[0]
        )
        for seed in range(seeds)
    )
    assert with_any / seeds <= 0.15


def test_the_period_a_question_names_is_the_one_compared(steps_fell):
    records, text = overview_evidence(steps_fell, "what changed most this month?", END)
    assert records[0].windows[0].start == END.replace(day=1)
    assert "Overview: all" in text


def test_period_dates_agree_with_the_period_words_every_day_of_a_year():
    from app.agent.periods import _span

    for offset in range(366):
        today = date(2026, 1, 1) + timedelta(days=offset)
        for name in ("this week", "last week", "this month", "last month", "lately"):
            assert _span(*period_range(name, today)) in period(name, today)
    assert asked_period("how was last night?", date(2026, 11, 18)) is None


def test_only_the_first_ranked_change_may_be_called_the_biggest(steps_fell):
    records, _ = overview_evidence(steps_fell, "what changed most lately?", END)
    assert ranked_problems("Your biggest change was in steps, down to about 2,600.", records) == []
    assert ranked_problems("The main change was in your time asleep.", records)
    # Without an overview nothing ranked every metric, so nothing is checked.
    assert ranked_problems("The main change was in your time asleep.", []) == []


def test_a_metric_is_never_given_as_the_reason_for_a_feeling():
    assert attributed("You're probably tired mainly because you've been sleeping less.")
    assert attributed("That's why you feel drained.")
    assert attributed("Your time asleep is down, which could be adding to feeling tired.") == []


def test_an_answer_saying_because_you_is_sent_back(steps_fell):
    bad = submit("You feel tired mainly because you have been walking less.")
    good = submit("Your steps are down, which could be adding to feeling tired.")
    llm = ScriptedLLM([bad, good])
    reply = ask(llm, Router("why"), steps_fell, "Why do I feel tired?")
    assert "because you" not in reply.result.summary
    assert any("reason for how they feel" in str(m) for m in llm.requests[-1]["messages"])


def test_retesting_one_metric_does_not_escape_the_overview_correction():
    """A follow-up test joins the overview's family: a metric unclear across every metric stays
    unclear when the agent tests it again on its own."""
    quiet = planted(seed=7)  # nothing planted; one metric moves by chance
    records, _ = overview_evidence(quiet, "anything different recently?", END)
    chance = max(
        (r for r in records if r.stats.get("overview_possible")),
        key=lambda r: abs(r.stats["cliffs_delta"]),
    )
    metric, (recent, baseline) = chance.metrics[0], chance.windows
    retest = ToolCall(
        "c1",
        "compare_windows",
        {
            "metric": metric,
            "recent_start": str(recent.start),
            "recent_end": str(recent.end),
            "baseline_start": str(baseline.start),
            "baseline_end": str(baseline.end),
        },
    )
    claim_it = submit(f"Your {label(metric)} was lower.")
    hedge_it = submit(f"Your {label(metric)} looked lower, though that could be normal variation.")
    llm = ScriptedLLM(
        [Completion(None, (retest,), "scripted", Usage(), 0.0, 0.0), claim_it, hedge_it]
    )
    ask(llm, Router("change"), quiet, "Anything different recently?", today=END)
    assert any("no significant evidence" in str(m) for m in llm.requests[-1]["messages"])


@pytest.mark.parametrize(
    "question, broad",
    [
        ("Summarise how I've been.", True),
        ("Give me the big picture of the last two weeks", True),
        ("What was my average this week?", False),  # a statistic: a lookup
        ("How many steps did I take?", False),  # names a metric
    ],
)
def test_a_lookup_is_broad_only_without_a_metric_or_a_statistic(steps_fell, question, broad):
    llm = ScriptedLLM([submit()])
    ask(llm, Router("lookup"), steps_fell, question)
    assert ("Overview: all" in llm.requests[0]["messages"][1]["content"]) is broad


def test_a_claim_that_states_an_unclear_change_is_turned_back():
    """A no_change claim worded as a change would read as one when the summary is rebuilt."""
    quiet = planted(seed=7)
    records, _ = overview_evidence(quiet, "anything different recently?", END)
    chance = next(r for r in records if r.stats.get("overview_possible"))
    worded = {
        "text": f"Your {label(chance.metrics[0])} was down.",
        "kind": "no_change",
        "evidence_ids": [chance.id],
        "metric": chance.metrics[0],
    }
    llm = ScriptedLLM(
        [submit("Nothing changed clearly.", [worded]), submit("Nothing changed clearly.")]
    )
    reply = ask(llm, Router("change"), quiet, "Anything different recently?", today=END)
    assert all(c.text != worded["text"] for c in reply.result.claims)


def test_main_as_a_plain_adjective_ranks_nothing(steps_fell):
    """'The main recovery measures held steady' describes metrics; it calls nothing the biggest."""
    records, _ = overview_evidence(steps_fell, "what changed most lately?", END)
    steady = "Bedtime, sleep efficiency, and the main recovery and activity measures held steady."
    assert ranked_problems(steady, records) == []
    assert ranked_problems("The main change was in your time asleep.", records)
