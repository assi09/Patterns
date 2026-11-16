from types import SimpleNamespace

import httpx2
import openai
import pytest

from app.agent.llm import (
    PRICES,
    Budget,
    BudgetExceeded,
    LLMError,
    OpenAILLM,
    Role,
    ScriptedLLM,
    SpendLedger,
    Usage,
)

MODELS = {Role.SMALL: "gpt-5.4-mini", Role.LARGE: "gpt-5.5"}
REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


def response(content=None, tool_calls=(), prompt=1000, cached=0, completion=200):
    calls = [
        SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=name, arguments=args))
        for i, (name, args) in enumerate(tool_calls)
    ]
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls or None))
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
        ),
    )


class FakeClient:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def llm(*outcomes, cap=20.0) -> tuple[OpenAILLM, FakeClient, SpendLedger]:
    client = FakeClient(*outcomes)
    ledger = SpendLedger(cap_usd=cap)
    ticks = iter([0.0, 1.5] * 10)
    return OpenAILLM(client, MODELS, ledger, clock=lambda: next(ticks)), client, ledger


def test_text_answer_with_cost_and_latency():
    model, client, ledger = llm(response(content="Hello", prompt=1000, completion=200))
    completion = model.complete([{"role": "user", "content": "hi"}])
    assert completion.text == "Hello" and completion.tool_calls == ()
    assert completion.model == "gpt-5.4-mini"
    assert completion.cost_usd == pytest.approx((1000 * 0.75 + 200 * 4.50) / 1e6)
    assert completion.latency_s == 1.5
    assert ledger.spent_usd == pytest.approx(completion.cost_usd)
    assert "tools" not in client.requests[0]


def test_cached_input_is_billed_at_the_cached_rate():
    usage = Usage(input_tokens=1000, cached_input_tokens=800, output_tokens=0)
    price = PRICES["gpt-5.4-mini"]
    assert usage.cost(price) == pytest.approx((200 * 0.75 + 800 * 0.075) / 1e6)


def test_the_role_chooses_the_model_and_tools_are_sent():
    model, client, _ = llm(response(content="ok"))
    tools = [{"type": "function", "function": {"name": "trend", "parameters": {}}}]
    model.complete([], role=Role.LARGE, tools=tools)
    assert client.requests[0]["model"] == "gpt-5.5"
    assert client.requests[0]["tools"] == tools


def test_tool_calls_are_parsed_and_bad_arguments_flagged():
    model, _, _ = llm(
        response(
            tool_calls=[("trend", '{"metric": "steps"}'), ("trend", "{oops"), ("trend", "[1]")]
        )
    )
    good, broken, not_object = model.complete([]).tool_calls
    assert good.arguments == {"metric": "steps"} and good.error is None
    assert broken.arguments is None and "not valid JSON" in broken.error
    assert not_object.arguments is None and "JSON object" in not_object.error


def test_assistant_message_round_trips_tool_calls():
    model, _, _ = llm(response(tool_calls=[("trend", '{"metric": "steps"}')]))
    message = model.complete([]).as_message()
    assert message["role"] == "assistant"
    assert message["tool_calls"][0]["function"] == {
        "name": "trend",
        "arguments": '{"metric": "steps"}',
    }


def test_run_budget_is_charged_and_enforced_before_calling():
    model, client, _ = llm(response(content="a"), response(content="b"))
    budget = Budget(max_calls=1)
    model.complete([], budget=budget)
    assert budget.calls == 1 and budget.cost_usd > 0
    with pytest.raises(BudgetExceeded, match="1 model calls"):
        model.complete([], budget=budget)
    assert len(client.requests) == 1  # the second call never reached OpenAI


def test_run_cost_limit_stops_the_loop():
    model, _, _ = llm(response(content="a", prompt=100_000))
    budget = Budget(max_cost_usd=0.01)
    model.complete([], budget=budget)  # $0.075 + output, over the limit once spent
    with pytest.raises(BudgetExceeded, match="cost limit"):
        model.complete([], budget=budget)


def test_spending_cap_refuses_further_calls():
    model, client, ledger = llm(response(content="a", prompt=10_000_000), cap=1.0)
    model.complete([])  # $7.50 + output: over the $1 cap
    with pytest.raises(BudgetExceeded, match="FA_LLM_SPEND_CAP_USD"):
        model.complete([])
    assert len(client.requests) == 1


@pytest.mark.parametrize(
    "error, message",
    [
        (
            openai.AuthenticationError(
                "bad", response=httpx2.Response(401, request=REQUEST), body=None
            ),
            "API key",
        ),
        (
            openai.RateLimitError(
                "slow", response=httpx2.Response(429, request=REQUEST), body=None
            ),
            "rate limiting",
        ),
        (openai.APITimeoutError(request=REQUEST), "too long"),
        (openai.APIConnectionError(request=REQUEST), "reach OpenAI"),
        (
            openai.InternalServerError(
                "x", response=httpx2.Response(500, request=REQUEST), body=None
            ),
            "(500)",
        ),
    ],
)
def test_openai_errors_become_safe_messages(error, message):
    model, _, ledger = llm(error)
    with pytest.raises(LLMError, match=message):
        model.complete([])
    assert ledger.spent_usd == 0


def test_models_without_a_known_price_are_refused():
    with pytest.raises(LLMError, match="No price"):
        OpenAILLM(FakeClient(), {Role.SMALL: "mystery-model"}, SpendLedger(cap_usd=1))


def test_missing_key_is_reported():
    settings = SimpleNamespace(
        openai_api_key=None,
        openai_small_model="gpt-5.4-mini",
        openai_large_model="gpt-5.5",
        llm_spend_cap_usd=20.0,
    )
    with pytest.raises(LLMError, match="FA_OPENAI_API_KEY"):
        OpenAILLM.from_settings(settings)


def test_scripted_llm_replays_turns_and_records_requests():
    scripted = ScriptedLLM([ScriptedLLM.call("trend", metric="steps"), ScriptedLLM.say("done")])
    tools = [{"type": "function", "function": {"name": "trend", "parameters": {}}}]
    first = scripted.complete([{"role": "user", "content": "go"}], tools=tools)
    assert first.tool_calls[0].arguments == {"metric": "steps"}
    assert scripted.complete([]).text == "done"
    assert scripted.requests[0]["tools"] == ["trend"]
    with pytest.raises(LLMError, match="no more turns"):
        scripted.complete([])


def test_scripted_llm_respects_the_budget():
    scripted = ScriptedLLM([ScriptedLLM.say("a"), ScriptedLLM.say("b")])
    budget = Budget(max_calls=1)
    scripted.complete([], budget=budget)
    with pytest.raises(BudgetExceeded):
        scripted.complete([], budget=budget)


def test_the_agents_settings_go_only_with_its_own_calls():
    client = FakeClient(response("ok"), response("ok"))
    agent = {Role.AGENT: {"reasoning_effort": "low", "temperature": 0.4}}
    model = OpenAILLM(client, MODELS, SpendLedger(cap_usd=1), options=agent)
    model.complete([{"role": "user", "content": "hi"}], role=Role.AGENT)
    model.complete([{"role": "user", "content": "hi"}])  # a small job keeps the defaults
    first, second = client.requests
    assert first["reasoning_effort"] == "low" and first["temperature"] == 0.4
    assert first["model"] == MODELS[Role.SMALL]  # the agent's model is the small one unless set
    assert "reasoning_effort" not in second and "temperature" not in second
