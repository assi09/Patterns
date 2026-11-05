import json
from datetime import date, timedelta

import pytest

from app.agent.agent import SUBMIT, answer, investigate, run_agent, trace_json
from app.agent.llm import Budget, Completion, ScriptedLLM, ToolCall, Usage
from app.agent.tools import Toolbox
from app.synthetic import Coupling, Step, generate

START = date(2026, 7, 1)
CHANGE = START + timedelta(45)
LAST = START + timedelta(59)


def day(offset: int) -> str:
    return (START + timedelta(offset)).isoformat()


@pytest.fixture(scope="module")
def frame():
    """Sleep drops from day 45, when bedtime moves an hour later: the screen should catch it."""
    effects = (
        Step("bedtime_hour", CHANGE, 1.0),
        Coupling("bedtime_hour", "sleep_minutes", lag_days=0, strength=-0.9),
        Step("sleep_minutes", CHANGE, -45),
    )
    return generate(START, 60, effects, seed=3).frame


def evidence_from(messages: list[dict], tool: str) -> dict:
    """The latest evidence a tool returned in the conversation."""
    for message in reversed(messages):
        if message["role"] == "tool":
            payload = json.loads(message["content"])
            if payload.get("tool") == tool:
                return payload
    raise AssertionError(f"no {tool} evidence in the conversation")


def screened(messages: list[dict]) -> dict:
    """The screen's sleep change, listed in the task."""
    lines = messages[1]["content"].splitlines()
    line = next(text for text in lines if text.startswith("- sleep_minutes: "))
    return json.loads(line.removeprefix("- sleep_minutes: "))


def submit(
    claims: list[dict], summary: str = "Sleep dropped as bedtime moved later."
) -> Completion:
    call = ToolCall("submit", SUBMIT, {"summary": summary, "claims": claims, "hypotheses": []})
    return Completion(None, (call,), "scripted", Usage(), 0.001, 0.0)


def sleep_investigation() -> list:
    def first_submission(messages):
        change = screened(messages)
        link = evidence_from(messages, "correlate")
        drop = abs(change["stats"]["difference"])
        return submit(
            [
                {
                    "text": f"Your sleep fell by about {drop:.0f} minutes a night.",
                    "kind": "change",
                    "evidence_ids": [change["evidence_id"]],
                    "metric": "sleep_minutes",
                    "direction": "down",
                },
                {
                    "text": "Your sleep fell because of your later bedtime.",
                    "kind": "association",
                    "evidence_ids": [link["evidence_id"]],
                    "metric": "sleep_minutes",
                    "direction": "down",
                },
                {
                    "text": "Your sleep fell by 200 minutes.",
                    "kind": "change",
                    "evidence_ids": [change["evidence_id"]],
                    "metric": "sleep_minutes",
                    "direction": "down",
                },
            ]
        )

    def repaired(messages):
        change = screened(messages)
        link = evidence_from(messages, "correlate")
        drop = abs(change["stats"]["difference"])
        return submit(
            [
                {
                    "text": f"Your sleep fell by about {drop:.0f} minutes a night.",
                    "kind": "change",
                    "evidence_ids": [change["evidence_id"]],
                    "metric": "sleep_minutes",
                    "direction": "down",
                },
                {
                    "text": "Nights with a later bedtime went with less sleep.",
                    "kind": "association",
                    "evidence_ids": [link["evidence_id"]],
                    "metric": "sleep_minutes",
                    "direction": "down",
                },
            ]
        )

    return [
        ScriptedLLM.call(
            "record_hypotheses", hypotheses=["later bedtime", "low wear time", "more training"]
        ),
        ScriptedLLM.call("change_point", metric="sleep_minutes", start=day(0), end=day(59)),
        ScriptedLLM.call("coverage", start=day(0), end=day(59)),
        ScriptedLLM.call(
            "correlate", driver="bedtime_hour", target="sleep_minutes", start=day(0), end=day(59)
        ),
        first_submission,
        repaired,
    ]


def test_investigation_tests_hypotheses_and_keeps_only_verified_claims(frame):
    llm = ScriptedLLM(sleep_investigation())
    result = investigate(llm, frame)
    assert result.stop_reason == "submitted"
    assert result.recorded_hypotheses == ["later bedtime", "low wear time", "more training"]
    assert [c.kind for c in result.claims] == ["change", "association"]
    assert result.rejected == []  # the repaired submission passed
    first_verdict = next(s for s in result.trace if s["type"] == "verify")
    reasons = " ".join(r for c in first_verdict["rejected"] for r in c["reasons"])
    assert "states causation" in reasons and "numbers not found" in reasons
    assert all(i in result.evidence for c in result.claims for i in c.evidence_ids)


def test_the_task_lists_the_screened_change_and_the_tools(frame):
    llm = ScriptedLLM(sleep_investigation())
    investigate(llm, frame)
    task = llm.requests[0]["messages"][1]["content"]
    assert "sleep_minutes" in task and "corrected for testing many metrics" in task
    assert {"change_point", "correlate", "record_hypotheses", SUBMIT} <= set(
        llm.requests[0]["tools"]
    )


def test_the_trace_records_every_step(frame):
    result = investigate(ScriptedLLM(sleep_investigation()), frame)
    kinds = [step["type"] for step in result.trace]
    assert kinds.count("llm") == 6
    assert {"hypotheses", "tool", "verify"} <= set(kinds)
    trace = json.loads(trace_json(result))
    assert trace["stop_reason"] == "submitted" and len(trace["claims"]) == 2
    assert trace["cost_usd"] == pytest.approx(0.002)  # the two scripted submissions


def test_nothing_to_explain_costs_no_model_call():
    calm = generate(START, 60, seed=11).frame
    llm = ScriptedLLM([])
    result = investigate(llm, calm)
    assert result.stop_reason == "nothing_to_explain"
    assert llm.requests == [] and result.budget.calls == 0


def test_tool_errors_go_back_to_the_model(frame):
    llm = ScriptedLLM(
        [
            ScriptedLLM.call("trend", metric="steps", start=day(0), end=day(59)),
            ScriptedLLM.say("ok"),
            ScriptedLLM.say("still no"),
            ScriptedLLM.say("Still no."),
        ]
    )
    result = answer(llm, frame, "How is my sleep?", metrics=["sleep_minutes"])
    tool_reply = json.loads(llm.requests[1]["messages"][-1]["content"])
    assert "not available here" in tool_reply["error"]
    assert result.stop_reason == "no_submission"  # it never submitted


def test_a_reply_without_tools_gets_two_reminders_then_stops(frame):
    llm = ScriptedLLM([ScriptedLLM.say("It is fine.") for _ in range(3)])
    result = answer(llm, frame, "How is my sleep?")
    assert len(llm.requests) == 3
    assert SUBMIT in llm.requests[1]["messages"][-1]["content"]
    assert result.stop_reason == "no_submission" and result.claims == []


def test_a_turn_with_too_many_tool_calls_loses_only_the_excess(frame):
    calls = tuple(
        ToolCall(f"c{i}", "describe", {"metric": "sleep_minutes", "start": day(0), "end": day(9)})
        for i in range(5)
    )
    many = Completion(None, calls, "scripted", Usage(), 0.0, 0.0)
    llm = ScriptedLLM([many, ScriptedLLM.say("done"), ScriptedLLM.say("done")])
    result = answer(llm, frame, "How is my sleep?", budget=Budget(max_tool_calls=3))
    steps = [s for s in result.trace if s["type"] == "tool"]
    assert [("evidence_id" in s) for s in steps] == [True, True, True, False, False]
    assert len(result.evidence) == 3


def test_the_budget_ends_the_run_and_warns_before_the_last_turn(frame):
    turns = [ScriptedLLM.call("describe", metric="sleep_minutes", start=day(0), end=day(59))] * 3
    llm = ScriptedLLM(list(turns))
    result = answer(llm, frame, "How is my sleep?", budget=Budget(max_calls=3))
    assert result.stop_reason == "budget"
    assert "last turn" in llm.requests[2]["messages"][-1]["content"]
    assert len(result.evidence) == 3  # the work done is kept


def test_model_errors_end_the_run_with_the_reason(frame):
    result = answer(ScriptedLLM([]), frame, "How is my sleep?")
    assert result.stop_reason == "model_error" and "no more turns" in result.error


def test_an_invalid_submission_is_explained(frame):
    bad = Completion(None, (ToolCall("s", SUBMIT, {"claims": "none"}),), "scripted", Usage(), 0, 0)
    llm = ScriptedLLM([bad, ScriptedLLM.say("giving up"), ScriptedLLM.say("done")])
    answer(llm, frame, "How is my sleep?")
    assert "Invalid submission" in json.loads(llm.requests[1]["messages"][-1]["content"])["error"]


def test_claims_still_failing_after_the_repair_round_are_dropped(frame):
    def bad_claim(messages):
        evidence = evidence_from(messages, "describe")
        return submit(
            [
                {
                    "text": "Your sleep fell by 500 minutes.",
                    "kind": "change",
                    "evidence_ids": [evidence["evidence_id"]],
                    "metric": "sleep_minutes",
                    "direction": "down",
                }
            ]
        )

    llm = ScriptedLLM(
        [
            ScriptedLLM.call("describe", metric="sleep_minutes", start=day(0), end=day(59)),
            bad_claim,
            bad_claim,
        ]
    )
    result = answer(llm, frame, "How is my sleep?")
    assert result.stop_reason == "submitted"
    assert result.claims == [] and len(result.rejected) == 1


def test_every_tool_call_gets_a_reply_so_the_conversation_stays_valid(frame):
    llm = ScriptedLLM(sleep_investigation())
    investigate(llm, frame)
    for request in llm.requests:
        pending = set()
        for message in request["messages"]:
            if message["role"] == "assistant":
                assert not pending, "a tool call was left without a reply"
                pending = {c["id"] for c in message.get("tool_calls", [])}
            elif message["role"] == "tool":
                pending.discard(message["tool_call_id"])


def test_run_agent_shares_evidence_with_the_toolbox(frame):
    box = Toolbox(frame, ["sleep_minutes"])
    llm = ScriptedLLM(
        [ScriptedLLM.call("describe", metric="sleep_minutes", start=day(0), end=day(9))]
    )
    result = run_agent(llm, box, "Describe my sleep.")
    assert result.evidence is box.evidence and len(box.evidence) == 1


def test_evidence_shows_the_model_readable_values_and_names(frame):
    llm = ScriptedLLM(
        [
            ScriptedLLM.call("describe", metric="bedtime_hour", start=day(0), end=day(59)),
            ScriptedLLM.say("x"),
            ScriptedLLM.say("y"),
        ]
    )
    answer(llm, frame, "When do I go to bed?")
    payload = json.loads(llm.requests[1]["messages"][-1]["content"])
    assert payload["labels"] == {"bedtime_hour": "bedtime"}
    assert ":" in payload["display"]["mean"]  # a clock time, while stats keep hours
    assert isinstance(payload["stats"]["mean"], float)
    assert "bedtime_hour (bedtime)" in llm.requests[0]["messages"][1]["content"]


def test_an_unsupported_summary_is_repaired_then_replaced(frame):
    def with_summary(text):
        def turn(messages):
            evidence = evidence_from(messages, "describe")
            return submit(
                [
                    {
                        "text": "Your sleep stayed about the same.",
                        "kind": "no_change",
                        "evidence_ids": [evidence["evidence_id"]],
                        "metric": "sleep_minutes",
                    }
                ],
                summary=text,
            )

        return turn

    llm = ScriptedLLM(
        [
            ScriptedLLM.call("describe", metric="sleep_minutes", start=day(0), end=day(59)),
            with_summary("You lost 3 h 3 min of sleep."),
            with_summary("You lost 3 h 3 min of sleep, really."),
        ]
    )
    result = answer(llm, frame, "How is my sleep?")
    repair = json.loads(llm.requests[2]["messages"][-1]["content"])
    assert "durations not found" in " ".join(repair["summary_problems"])
    assert result.summary == "Your sleep stayed about the same."  # the verified claim instead
