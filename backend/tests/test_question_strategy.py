"""How the agent works on each kind of question: tools, guide, up-front evidence, widening."""

from datetime import date, timedelta

import pytest

from app.agent.agent import NO_ANSWER, SUBMIT, Claim, answer, fallback_summary
from app.agent.ask import ask
from app.agent.intent import Intent
from app.agent.llm import Budget, Completion, ScriptedLLM, ToolCall, Usage
from app.agent.router import EXPERT_LABELS, LABELS, Classification, JevRouter, KeywordRouter
from app.agent.strategy import COACHING_OFFER, STRATEGIES, coaching_evidence, snapshot
from app.analysis.day import with_scores
from app.synthetic import Coupling, generate

START = date(2026, 7, 1)


@pytest.fixture(scope="module")
def frame():
    planted = (Coupling("bedtime_hour", "sleep_efficiency", 0, -0.9),)
    return with_scores(generate(START, 90, planted, seed=2).frame)


class Router:
    def __init__(self, question_type, intent=Intent.READ, **topic):
        self.result = Classification(
            dict.fromkeys(LABELS, 0.0) | (topic or {"sleep": 0.9}),
            dict.fromkeys(EXPERT_LABELS, 0.0),
            source="test",
            intent_probabilities={str(i): float(i == intent) for i in Intent},
            question_types={question_type: 1.0} if question_type else {},
        )

    def classify(self, question, earlier=()):
        return self.result


def submit(summary="Done.", claims=()):
    call = ToolCall("submit", SUBMIT, {"summary": summary, "claims": list(claims)})
    return Completion(None, (call,), "scripted", Usage(), 0.0, 0.0)


def offered_tools(llm):
    return set(llm.requests[0]["tools"])


@pytest.mark.parametrize(
    "question, kind",
    [
        ("How can I sleep better?", "coaching"),
        ("Why is my HRV low?", "why"),
        ("How did I sleep last night?", "day"),
        ("Do I sleep less on weekends?", "pattern"),
        ("Has my resting heart rate changed lately?", "change"),
        ("What was my best sleep this month?", "lookup"),
    ],
)
def test_the_keyword_router_tells_question_types_apart(question, kind):
    assert KeywordRouter().classify(question).question_type == kind


def test_jev_is_asked_the_question_type_in_the_same_call():
    questions = JevRouter("key").payload("How can I sleep better?")["questions"]
    assert questions["question_type"]["type"] == "choice"
    assert set(questions["question_type"]["criteria"]) == {*STRATEGIES, "world"}


def test_a_day_question_starts_with_a_snapshot_it_can_answer_from(frame):
    llm = ScriptedLLM([submit()])
    reply = ask(llm, Router("day"), frame, "How did I sleep last night?")
    task = llm.requests[0]["messages"][1]["content"]
    assert "Snapshot of the latest day" in task and "No hypotheses" in task
    assert offered_tools(llm) >= {"compare_day", "expand_tools"}
    assert "record_hypotheses" in offered_tools(llm)  # always there, just not asked for
    assert "correlate" not in offered_tools(llm)
    # The snapshot's evidence can be cited without a single tool call.
    sleep_id = next(i for i in reply.context.evidence) if reply.context.evidence else None
    assert sleep_id is None  # the conversation context itself is empty here


def evidence_id_for(task: str, name: str, section: str = "") -> str:
    """The evidence id the task lists for a metric (after `section`), as the model reads it."""
    lines = task[task.index(section) :].splitlines() if section else task.splitlines()
    line = next(line for line in lines if line.startswith(f"- {name} (evidence_id "))
    return line.split("evidence_id ")[1].split(")")[0]


def test_a_snapshot_claim_passes_with_no_tool_call(frame):
    found, _ = snapshot(frame, list(frame.columns))
    position = next(e for e in found if e.metrics[0] == "sleep_minutes").stats["position"]
    direction = {"above": "up", "below": "down", "within": None}[position]

    def answer_from_snapshot(messages):
        sleep_id = evidence_id_for(messages[1]["content"], "time asleep")
        claim = {
            "text": f"Last night's time asleep was {position} your usual range.",
            "kind": "day",
            "evidence_ids": [sleep_id],
            "metric": "sleep_minutes",
            "direction": direction,
        }
        return submit("Here is last night.", [claim])

    llm = ScriptedLLM([answer_from_snapshot])
    reply = ask(llm, Router("day"), frame, "How did I sleep last night?")
    assert [c.metric for c in reply.result.claims] == ["sleep_minutes"]
    assert reply.result.budget.calls == 1  # one model call; its only tool call was the submission
    assert reply.result.budget.tool_calls == 1


def test_coaching_gets_tested_habits_up_front_and_an_offer_after(frame):
    _, text = coaching_evidence(frame, "sleep", list(frame.columns))
    assert "supported:" in text

    def suggest(messages):
        task = messages[1]["content"]
        assert "Habits tested on this person's own days" in task
        claim = {
            "text": "On nights you were in bed earlier, your sleep efficiency was higher, so you "
            "could try that.",
            "kind": "suggestion",
            "evidence_ids": [evidence_id_for(task, "sleep efficiency", "Habits tested")],
            "metric": "sleep_efficiency",
        }
        return submit("Your data points to one habit.", [claim])

    reply = ask(ScriptedLLM([suggest]), Router("coaching"), frame, "How can I sleep better?")
    assert [c.kind for c in reply.result.claims] == ["suggestion"]
    assert COACHING_OFFER in reply.result.notes


def test_the_agent_can_widen_its_tools_once(frame):
    def expand(messages):
        return Completion(
            None,
            (ToolCall("x", "expand_tools", {"reason": "need a correlation"}),),
            "scripted",
            Usage(),
            0.0,
            0.0,
        )

    llm = ScriptedLLM([expand, expand, submit()])
    reply = ask(llm, Router("day"), frame, "How did I sleep last night, and why?")
    assert "correlate" not in set(llm.requests[0]["tools"])
    assert "correlate" in set(llm.requests[1]["tools"])  # widened for the next turn
    steps = [s for s in reply.result.trace if s.get("type") == "expand"]
    assert len(steps) == 1 and steps[0]["reason"] == "need a correlation"


def test_logging_keeps_the_full_toolbox(frame):
    llm = ScriptedLLM([submit()])
    ask(llm, Router("coaching", intent=Intent.LOG), frame, "Log a 30 minute run")
    assert "expand_tools" not in offered_tools(llm)


def claim(kind: str, text: str, metric: str = "steps") -> Claim:
    return Claim(text=text, kind=kind, evidence_ids=["e"], metric=metric)


def test_the_fallback_never_leads_with_a_note_on_data_quality():
    claims = [
        claim("data_quality", "Coverage was complete."),
        claim("no_change", "Steps did not clearly differ between weekdays and weekends."),
    ]
    assert fallback_summary(claims) == "Steps did not clearly differ between weekdays and weekends."


def test_a_note_on_data_quality_alone_is_not_passed_off_as_an_answer():
    assert fallback_summary([claim("data_quality", "Coverage was complete.")]) == NO_ANSWER


def test_two_steady_metrics_keep_their_own_words_and_three_are_grouped():
    two = [
        claim("no_change", "Steps did not differ by weekday."),
        claim("no_change", "Distance did not differ by weekday.", "distance_km"),
    ]
    assert (
        fallback_summary(two)
        == "Steps did not differ by weekday. Distance did not differ by weekday."
    )
    three = [*two, claim("no_change", "Sleep held.", "sleep_minutes")]
    assert fallback_summary(three).endswith("showed no clear change.")


@pytest.mark.parametrize("failure", ["budget", "model"])
def test_a_summary_that_failed_its_check_is_never_the_answer(frame, failure):
    bad = ScriptedLLM.call(SUBMIT, summary="Your sleep was 999 minutes.", claims=[])
    # The run ends during the repair: out of budget, or the model is gone.
    turns = [bad] if failure == "model" else [bad, bad]
    budget = Budget(max_calls=1 if failure == "budget" else 5)
    result = answer(ScriptedLLM(turns), frame, "How did I sleep?", budget=budget)
    assert result.stop_reason in ("budget", "model_error")
    assert "999" not in result.summary


def test_an_unknown_type_works_like_before(frame):
    llm = ScriptedLLM([submit()])
    ask(llm, Router(None), frame, "Tell me about my data")
    task = llm.requests[0]["messages"][1]["content"]
    assert "record_hypotheses" in task and "Snapshot" not in task


def test_the_route_step_records_the_question_type(frame):
    reply = ask(ScriptedLLM([submit()]), Router("pattern"), frame, "Do I sleep less on weekends?")
    route = next(s for s in reply.result.trace if s["type"] == "route")
    assert route["question_type"] == "pattern"


def test_a_failed_summary_is_rebuilt_from_the_claims_grouped():
    claims = [
        Claim(
            text="time asleep did not clearly change",
            kind="no_change",
            evidence_ids=["a"],
            metric="sleep_minutes",
        ),
        Claim(
            text="bedtime did not clearly change",
            kind="no_change",
            evidence_ids=["b"],
            metric="bedtime_hour",
        ),
        Claim(
            text="sleep efficiency went down",
            kind="change",
            evidence_ids=["c"],
            metric="sleep_efficiency",
            direction="down",
        ),
    ]
    assert fallback_summary(claims) == (
        "Sleep efficiency went down. Time asleep did not clearly change. Bedtime did not clearly "
        "change."
    )


def test_two_areas_are_tested_by_code_and_corrected_together():
    from datetime import date

    from app.agent.strategy import cross_area_evidence
    from app.synthetic import generate

    frame = generate(date(2026, 8, 1), 90, seed=2).frame
    frame["strain"] = frame["steps"] / 1000
    records, text = cross_area_evidence(frame, "sleep", ["activity"])
    assert records and "evidence_id" in text
    assert all("tests_in_run" in r.stats for r in records)
    assert cross_area_evidence(frame, "sleep", []) == ([], "")


def test_a_stitched_fallback_is_reworded_when_the_new_words_pass():
    from app.agent.agent import AgentResult, _reword
    from app.agent.llm import Budget, ScriptedLLM
    from app.agent.verifier import Claim

    result = AgentResult(run_id="x", stop_reason="submitted", summary="Stitched.")
    result.claims = [Claim(text="Sleep held steady.", kind="no_change", evidence_ids=["a"])]
    _reword(
        ScriptedLLM([ScriptedLLM.say("Your sleep has held steady.")]),
        result,
        "sleep?",
        None,
        Budget(),
    )
    assert result.summary == "Your sleep has held steady."
    _reword(ScriptedLLM([ScriptedLLM.say("You slept 99 hours.")]), result, "sleep?", None, Budget())
    assert result.summary == "Your sleep has held steady."


def _frame(values):
    import pandas as pd

    days = pd.date_range("2026-09-01", periods=len(values), name="date")
    return pd.DataFrame({"sleep_minutes": values, "sleep_efficiency": values}, index=days)


def test_a_change_that_did_not_happen_is_caught_before_it_is_explained():
    import numpy as np

    from app.agent.strategy import check_premise

    steady = list(420 + np.random.default_rng(1).normal(0, 20, 60))
    premise = check_premise(_frame(steady), "Why is my sleep worse lately?", "sleep")
    assert premise and not premise.holds and "does not hold" in premise.text


def test_a_change_that_did_happen_stands():
    import numpy as np

    from app.agent.strategy import check_premise

    noise = np.random.default_rng(2).normal(0, 10, 60)
    dropped = [420 + n if i < 46 else 330 + n for i, n in enumerate(noise)]
    premise = check_premise(_frame(dropped), "Why is my sleep worse lately?", "sleep")
    assert premise and premise.holds


def test_the_wrong_direction_does_not_confirm_it():
    import numpy as np

    from app.agent.strategy import check_premise

    noise = np.random.default_rng(3).normal(0, 10, 60)
    rose = [330 + n if i < 46 else 420 + n for i, n in enumerate(noise)]
    assert not check_premise(_frame(rose), "Why is my sleep worse?", "sleep").holds


def test_a_question_assuming_nothing_is_not_checked():
    from app.agent.strategy import check_premise

    assert check_premise(_frame([420.0] * 60), "What affects my sleep?", "sleep") is None


def test_the_answer_must_open_by_correcting_it():
    from app.agent.strategy import premise_answer_check

    assert premise_answer_check([], "Your late bedtimes explain it.")
    assert premise_answer_check([], "Your sleep hasn't got worse. It looks steady.") == []


def test_a_question_that_assumes_no_change_is_not_checked_for_one():
    import numpy as np

    from app.agent.strategy import check_premise

    frame = _frame(list(420 + np.random.default_rng(4).normal(0, 20, 60)))
    assert check_premise(frame, "Which one is higher?", "sleep") is None
    assert check_premise(frame, "Does going to bed late go with worse sleep?", "sleep") is None
    assert check_premise(frame, "Has my sleep been getting worse lately?", "sleep") is not None


def test_the_premise_check_starts_where_a_change_began():
    # Time asleep fell 21 days before the end: with a fixed 14 days, a week of it sits in the
    # baseline. Found over many seeds, not one lucky one.
    from app.agent.strategy import check_premise
    from app.synthetic import Step

    end_offset = 90
    held = 0
    for seed in range(30):
        start = date(2026, 6, 1)
        frame = generate(
            start, end_offset, (Step("sleep_minutes", start + timedelta(days=69), -45.0),), seed
        ).frame
        premise = check_premise(frame, "Why am I sleeping less lately?", "sleep")
        held += bool(premise and premise.holds)
    assert held >= 27


def test_the_premise_check_does_not_find_a_change_that_is_not_there():
    from app.agent.strategy import check_premise

    wrong = 0
    for seed in range(60):
        frame = generate(date(2026, 6, 1), 90, seed=seed).frame
        premise = check_premise(frame, "Why am I sleeping less lately?", "sleep")
        wrong += bool(premise and premise.holds)
    assert wrong / 60 < 0.12


def test_a_named_day_is_read_in_every_form_and_only_once():
    from app.agent.strategy import named_day

    end = date(2026, 11, 11)
    for question in (
        "Why did my sleep drop around August 15?",
        "why worse on 15 Aug",
        "why lower on 2026-08-15",
    ):
        assert named_day(question, end) == date(2026, 8, 15)
    assert named_day("Why on Dec 20?", end) == date(2025, 12, 20)  # the latest one already past
    assert named_day("Why is my sleep worse lately?", end) is None
    assert named_day("Between Aug 1 and Aug 9?", end) is None  # two days: not one period
    assert named_day("Why on Feb 30?", end) is None


def test_the_premise_check_looks_at_the_day_the_question_names():
    """A dip months ago, then nothing: asked about its date, it holds; asked about lately, it
    does not. Over many seeds."""
    from app.agent.strategy import check_premise
    from app.synthetic import Step

    start = date(2026, 6, 1)
    dip = start + timedelta(days=40)
    held_then = held_lately = 0
    for seed in range(30):
        effects = (  # a week of short sleep that began on the day they name
            Step("sleep_minutes", dip, -90.0),
            Step("sleep_minutes", dip + timedelta(days=7), 90.0),
        )
        frame = generate(start, 120, effects, seed).frame
        then = check_premise(frame, f"Why did my sleep drop around {dip:%B} {dip.day}?", "sleep")
        lately = check_premise(frame, "Why did my sleep drop lately?", "sleep")
        held_then += bool(then and then.holds)
        held_lately += bool(lately and lately.holds)
        assert then is not None and f"{dip:%b} {dip.day}" in then.text
    # 80% power is the usual bar; 26 of 30 measured (one normal day sits in the week).
    assert held_then >= 24 and held_lately <= 4


def test_the_day_strategy_counts_relative_days_from_the_earlier_answer():
    assert "the day before that" in STRATEGIES["day"].guide


def test_the_snapshot_covers_the_day_the_question_names():
    from app.agent.strategy import asked_day

    frame = _frame([420.0] * 60)
    end = frame.index.max().date()
    today = end + timedelta(days=1)
    two_back = end - timedelta(days=1)
    asked = f"How many steps did I take on {two_back:%A} {two_back:%b} {two_back.day}?"
    assert asked_day(asked, today, frame) == two_back
    assert asked_day("And the day before yesterday?", today, frame) == two_back
    assert asked_day("How did I sleep yesterday?", today, frame) == end
    assert asked_day("How did I sleep?", today, frame) is None
