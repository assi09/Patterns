import json
from datetime import date, timedelta

import pytest

from app.agent import knowledge
from app.agent.agent import SUBMIT
from app.agent.experts import (
    BUDGETS,
    CONSULT,
    CONSULT_BUDGET,
    EXPERTS,
    SHARED,
    Depth,
    ask_expert,
    lead_budget,
    owner,
    visible_metrics,
    withheld_tools,
)
from app.agent.llm import Budget, Completion, ScriptedLLM, ToolCall, Usage
from app.agent.present import METRICS
from app.agent.retrieval import Retrieved
from app.agent.strategy import CROSS_AREA, expand_tool
from app.agent.tools import Toolbox
from app.analysis.evidence import ToolError
from app.synthetic import Coupling, Step, generate

START = date(2026, 7, 1)
CHANGE = START + timedelta(45)


def day(offset: int) -> str:
    return (START + timedelta(offset)).isoformat()


@pytest.fixture(scope="module")
def frame():
    """Sleep drops from day 45 as bedtime moves later; HRV follows the shorter nights."""
    effects = (
        Step("bedtime_hour", CHANGE, 1.0),
        Step("sleep_minutes", CHANGE, -45),
        Coupling("sleep_minutes", "hrv_ms", lag_days=0, strength=0.8),
    )
    return generate(START, 60, effects, seed=3).frame


def evidence_from(messages: list[dict], tool: str) -> dict:
    for message in reversed(messages):
        if message["role"] == "tool":
            payload = json.loads(message["content"])
            if payload.get("tool") == tool:
                return payload
    raise AssertionError(f"no {tool} evidence in the conversation")


def consulted_evidence(messages: list[dict]) -> dict:
    """The first evidence a consult returned to the lead."""
    for message in reversed(messages):
        if message["role"] == "tool":
            payload = json.loads(message["content"])
            if "expert" in payload and payload.get("evidence"):
                return payload["evidence"][0]
    raise AssertionError("no consult evidence in the conversation")


def submit(claims: list[dict], summary: str = "Here is what your data shows.") -> Completion:
    call = ToolCall("submit", SUBMIT, {"summary": summary, "claims": claims, "hypotheses": []})
    return Completion(None, (call,), "scripted", Usage(), 0.001, 0.0)


def claim(evidence: dict, metric: str, text: str, kind: str = "no_change", **extra) -> dict:
    ids = [evidence["evidence_id"]]
    return {"text": text, "kind": kind, "evidence_ids": ids, "metric": metric} | extra


SLEEP_DROP = ScriptedLLM.call(
    "compare_windows",
    metric="sleep_minutes",
    recent_start=day(45),
    recent_end=day(59),
    baseline_start=day(15),
    baseline_end=day(44),
)


def sleep_drop_claim(messages):
    evidence = evidence_from(messages, "compare_windows")
    return submit(
        [
            claim(
                evidence, "sleep_minutes", "Your time asleep went down.", "change", direction="down"
            )
        ]
    )


def test_every_metric_has_one_owner_except_wear_time():
    for metric in METRICS:
        owners = [e.name for e in EXPERTS.values() if metric in e.owns]
        assert len(owners) == (0 if metric in SHARED else 1), f"{metric}: {owners}"
    for expert in EXPERTS.values():
        assert set(expert.reads) <= set(EXPERTS) and expert.name not in expert.reads


def test_an_expert_sees_only_its_own_metrics():
    sleep = visible_metrics(EXPERTS["sleep"])
    assert "sleep_minutes" in sleep
    assert "steps" not in sleep and "hrv_ms" not in sleep
    assert owner("hrv_ms").name == "recovery" and owner("wear_minutes") is None
    # Nutrition has no columns of its own, so it still reads the others.
    assert "steps" in visible_metrics(EXPERTS["nutrition"])


def test_another_area_comes_only_through_a_consult_the_router_allowed(frame):
    def tools_offered(consult):
        llm = ScriptedLLM([lambda m: submit([])])
        ask_expert(llm, frame, "sleep", "Did it move?", consult=consult)
        return llm.requests[0]["tools"]

    alone, joined = tools_offered([]), tools_offered(["activity"])
    assert "sleep_regularity" in alone and "training_load" not in alone
    assert "training_load" in joined


def test_widening_the_tools_does_not_bring_back_another_experts(frame):
    toolbox = Toolbox(frame, ["sleep_minutes"], ("describe",))
    toolbox.withhold(withheld_tools(EXPERTS["sleep"]))
    expand_tool(toolbox, Budget(), []).run({"reason": "need more"})
    assert "compare_windows" in toolbox.tools and "training_load" not in toolbox.tools


def test_an_expert_answers_with_claims_about_its_own_metrics(frame):
    llm = ScriptedLLM([SLEEP_DROP, sleep_drop_claim])
    result = ask_expert(llm, frame, "sleep", "Has my sleep changed?")
    assert result.stop_reason == "submitted" and result.expert == "sleep"
    assert [c.metric for c in result.claims] == ["sleep_minutes"]
    request = llm.requests[0]
    assert "You are the sleep expert" in request["messages"][0]["content"]
    assert CONSULT not in request["tools"]  # only when the router allows a consult


def test_the_prompt_says_who_owns_the_metrics_the_expert_cannot_see(frame):
    llm = ScriptedLLM([lambda m: submit([])])
    ask_expert(llm, frame, "sleep", "Did my HRV move with my sleep?", consult=["recovery"])
    prompt = llm.requests[0]["messages"][0]["content"]
    assert "recovery: heart rate variability (HRV)" in prompt
    assert "nutrition" not in prompt  # no data, so not offered
    assert f"also concerns recovery: call {CONSULT}" in prompt


def test_claims_about_another_experts_metric_are_sent_back_then_dropped(frame):
    def about_steps(messages):
        evidence = evidence_from(messages, "describe")
        return submit([claim(evidence, "steps", "Your steps held steady.")])

    llm = ScriptedLLM(
        [
            ScriptedLLM.call("describe", metric="steps", start=day(0), end=day(59)),
            about_steps,
            about_steps,
        ]
    )
    result = ask_expert(llm, frame, "sleep", "How are my steps?", consult=["activity"])
    assert result.claims == [] and len(result.rejected) == 1
    assert "activity expert's metric" in result.rejected[0].reasons[0]
    assert "activity expert's metric" in llm.requests[2]["messages"][-1]["content"]


def test_a_claim_naming_its_metric_as_people_do_is_checked_as_that_metric(frame):
    def by_label(messages):
        evidence = evidence_from(messages, "compare_windows")
        return submit(
            [
                claim(
                    evidence,
                    "time asleep",
                    "Your time asleep went down.",
                    "change",
                    direction="down",
                )
            ]
        )

    result = ask_expert(
        ScriptedLLM([SLEEP_DROP, by_label]), frame, "sleep", "Has my sleep changed?"
    )
    assert [c.metric for c in result.claims] == ["sleep_minutes"] and result.rejected == []


def test_the_prompt_gives_the_metric_names_claims_must_use(frame):
    llm = ScriptedLLM([lambda m: submit([])])
    ask_expert(llm, frame, "recovery", "How is my HRV?")
    prompt = llm.requests[0]["messages"][0]["content"]
    assert "hrv_ms (heart rate variability (HRV))" in prompt
    assert "names before the parentheses" in prompt


def test_wear_time_and_data_quality_claims_are_open_to_every_expert(frame):
    def quality(messages):
        evidence = evidence_from(messages, "coverage")
        return submit([claim(evidence, None, "Your device was worn on most days.", "data_quality")])

    llm = ScriptedLLM([ScriptedLLM.call("coverage", start=day(0), end=day(59)), quality])
    result = ask_expert(llm, frame, "recovery", "Is my data complete?")
    assert len(result.claims) == 1 and result.rejected == []


def test_a_claim_must_name_its_metric(frame):
    def unnamed(messages):
        evidence = evidence_from(messages, "describe")
        return submit([claim(evidence, None, "Your HRV held steady.")])

    llm = ScriptedLLM(
        [
            ScriptedLLM.call("describe", metric="hrv_ms", start=day(0), end=day(59)),
            unnamed,
            unnamed,
        ]
    )
    result = ask_expert(llm, frame, "recovery", "How is my HRV?")
    assert result.claims == [] and "which of your metrics" in result.rejected[0].reasons[0]


def consulting_recovery(lead_claim) -> list:
    """Recovery leads, consults sleep (which runs its own two turns), then submits."""
    return [
        ScriptedLLM.call(CONSULT, expert="sleep", question="Did time asleep change recently?"),
        SLEEP_DROP,  # the sleep expert's turns
        sleep_drop_claim,
        lead_claim,  # back to the lead
    ]


def test_a_lead_may_cite_what_a_consulted_expert_found(frame):
    def lead_claim(messages):
        evidence = consulted_evidence(messages)
        return submit(
            [
                claim(
                    evidence,
                    "sleep_minutes",
                    "Your time asleep went down.",
                    "change",
                    direction="down",
                )
            ]
        )

    llm = ScriptedLLM(consulting_recovery(lead_claim))
    result = ask_expert(llm, frame, "recovery", "Why is my HRV lower?", consult=["sleep"])
    assert result.stop_reason == "submitted"
    assert result.consulted == ["sleep"]
    assert [c.metric for c in result.claims] == ["sleep_minutes"] and result.rejected == []
    assert CONSULT in llm.requests[0]["tools"]
    assert "You are the sleep expert" in llm.requests[1]["messages"][0]["content"]
    assert CONSULT not in llm.requests[1]["tools"]  # consulted experts cannot consult
    step = next(s for s in result.trace if s["type"] == CONSULT)
    assert step["expert"] == "sleep" and step["claims"] == 1 and step["steps"]


def test_consults_are_charged_to_the_lead(frame):
    llm = ScriptedLLM(consulting_recovery(lambda messages: submit([])))
    result = ask_expert(llm, frame, "recovery", "Why is my HRV lower?", consult=["sleep"])
    assert result.budget.calls == 4  # two lead turns and two consulted ones
    assert result.budget.cost_usd == pytest.approx(0.002)  # both submissions


def test_the_lead_cannot_use_its_own_evidence_for_another_experts_metric(frame):
    def own_evidence(messages):
        evidence = evidence_from(messages, "compare_windows")  # the lead computed it itself
        return submit(
            [
                claim(
                    evidence,
                    "sleep_minutes",
                    "Your time asleep went down.",
                    "change",
                    direction="down",
                )
            ]
        )

    llm = ScriptedLLM([SLEEP_DROP, own_evidence, own_evidence])
    result = ask_expert(llm, frame, "recovery", "Why is my HRV lower?", consult=["sleep"])
    assert result.claims == [] and "sleep expert's metric" in result.rejected[0].reasons[0]


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ({"expert": "recovery", "question": "x"}, "Consult one of: sleep."),  # itself
        ({"expert": "nutrition", "question": "x"}, "Consult one of: sleep."),  # no data
        ({"expert": "activity", "question": "x"}, "Consult one of: sleep."),  # not routed
        ({"expert": "sleep"}, "Give an expert and a short question"),
    ],
)
def test_bad_consults_are_explained_to_the_model(frame, arguments, error):
    llm = ScriptedLLM([ScriptedLLM.call(CONSULT, **arguments), lambda m: submit([])])
    allowed = ["recovery", "nutrition", "sleep"]
    result = ask_expert(llm, frame, "recovery", "Why?", consult=allowed)
    assert error in json.loads(llm.requests[1]["messages"][-1]["content"])["error"]
    assert result.consulted == []


def test_the_same_expert_is_consulted_once(frame):
    again = ScriptedLLM.call(CONSULT, "again", expert="sleep", question="And bedtime?")
    llm = ScriptedLLM([*consulting_recovery(again)[:3], again, lambda m: submit([])])
    result = ask_expert(llm, frame, "recovery", "Why?", consult=["sleep"])
    assert "already consulted" in json.loads(llm.requests[4]["messages"][-1]["content"])["error"]
    assert result.consulted == ["sleep"]


def test_a_consult_leaves_the_lead_enough_budget_to_submit(frame):
    llm = ScriptedLLM(
        [ScriptedLLM.call(CONSULT, expert="sleep", question="x"), lambda m: submit([])]
    )
    budget = Budget(max_calls=4)
    result = ask_expert(llm, frame, "recovery", "Why?", consult=["sleep"], budget=budget)
    assert "Not enough budget" in json.loads(llm.requests[1]["messages"][-1]["content"])["error"]
    assert result.stop_reason == "submitted"


def test_an_expert_without_data_answers_without_calling_the_model(frame):
    llm = ScriptedLLM([])
    result = ask_expert(llm, frame, "nutrition", "How much protein do I eat?")
    assert result.stop_reason == "unavailable" and llm.requests == []


def test_depths_have_their_own_budgets(frame):
    llm = ScriptedLLM([lambda m: submit([])])
    result = ask_expert(llm, frame, "sleep", "How is my sleep?", depth=Depth.QUICK)
    assert result.budget.max_calls == BUDGETS[Depth.QUICK].max_calls
    assert BUDGETS[Depth.QUICK].calls == 0  # the shared default was copied, not spent
    assert BUDGETS[Depth.DEEP].max_tool_calls > BUDGETS[Depth.QUICK].max_tool_calls


def test_deep_alone_does_not_allow_consulting(frame):
    llm = ScriptedLLM([lambda m: submit([])])
    ask_expert(llm, frame, "recovery", "Why is my HRV lower?", depth=Depth.DEEP)
    assert CONSULT not in llm.requests[0]["tools"]


def test_each_allowed_consult_adds_its_budget_to_the_lead():
    quick, with_two = lead_budget(Depth.QUICK, 0), lead_budget(Depth.QUICK, 2)
    assert quick.max_calls == BUDGETS[Depth.QUICK].max_calls
    assert with_two.max_calls == quick.max_calls + 2 * CONSULT_BUDGET.max_calls
    assert with_two.max_cost_usd == pytest.approx(
        quick.max_cost_usd + 2 * CONSULT_BUDGET.max_cost_usd
    )


def test_a_quick_answer_still_consults_when_the_router_says_so(frame):
    llm = ScriptedLLM(consulting_recovery(lambda messages: submit([])))
    result = ask_expert(llm, frame, "recovery", "Why?", depth=Depth.QUICK, consult=["sleep"])
    assert result.consulted == ["sleep"] and result.stop_reason == "submitted"


def test_a_summary_about_a_metric_no_evidence_covers_is_sent_back(frame):
    def hrv_summary(messages):
        evidence = evidence_from(messages, "compare_windows")
        drop = claim(
            evidence, "sleep_minutes", "Your time asleep went down.", "change", direction="down"
        )
        return submit([drop], summary="Your time asleep went down, but your HRV held steady.")

    llm = ScriptedLLM([SLEEP_DROP, hrv_summary, hrv_summary])
    result = ask_expert(llm, frame, "sleep", "Did my HRV move with my sleep?")
    repair = json.loads(llm.requests[2]["messages"][-1]["content"])
    assert "heart rate variability (HRV)" in repair["summary_problems"][0]
    assert result.summary == "Your time asleep went down."  # replaced by a verified claim


def test_no_cross_area_test_measures_a_score_against_its_own_inputs():
    # The recovery score is built partly from sleep, so sleep would always seem to explain it.
    pairs = [pair for group in CROSS_AREA.values() for pair in group]
    assert not any(target == "recovery_score" for _, target, _ in pairs)
    assert ("active_zone_minutes", "resting_hr", 1) in pairs


def test_guidance_is_searched_within_the_experts_topics(monkeypatch):
    seen = []

    def search(question, **kwargs):
        seen.append(kwargs.get("area"))
        return Retrieved(method="words")

    monkeypatch.setattr(knowledge, "search", search)
    knowledge.guidance_for("How can I sleep better?", [], None, "works nights", area="sleep")
    assert seen == ["sleep", None]  # their situation may reach beyond the expert's topics


def test_a_score_is_never_explained_by_its_own_inputs(frame):
    from app.agent.tools import _not_built_from

    with pytest.raises(ToolError, match="built partly from resting_hr"):
        _not_built_from("resting_hr", "recovery_score")
    with pytest.raises(ToolError):
        _not_built_from("strain", "active_zone_minutes")
    assert _not_built_from("sleep_minutes", "resting_hr") == ("sleep_minutes", "resting_hr")
