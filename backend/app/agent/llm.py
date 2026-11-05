"""The language model behind the agent: one interface, a real OpenAI client and a scripted fake.

The agent only talks to `LLM.complete`. Every call is priced, charged to the run's `Budget` and to
a process-wide `SpendLedger`, and refused up front once either is spent, so a runaway loop cannot
spend real money. `ScriptedLLM` replays canned turns, so tests and CI never need a key.
"""

import json
import time
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

import openai


class Role(StrEnum):
    SMALL = "small"  # tool loops and routine runs
    LARGE = "large"  # final write-ups and hard cross-domain questions


@dataclass(frozen=True)
class ModelPrice:
    """US dollars per million tokens."""

    input: float
    cached_input: float
    output: float


# Published per-token prices (June 2026). Calls to a model missing here are refused, because the
# spending cap could not be enforced for them.
PRICES = {
    "gpt-5.5": ModelPrice(input=5.00, cached_input=0.50, output=30.00),
    "gpt-5.4": ModelPrice(input=2.50, cached_input=0.25, output=15.00),
    "gpt-5.4-mini": ModelPrice(input=0.75, cached_input=0.075, output=4.50),
    "gpt-5.4-nano": ModelPrice(input=0.20, cached_input=0.02, output=1.25),
}


# A web search is priced per call, on top of its tokens. Published figures disagree ($10 or $25 per
# 1,000), so the higher one is counted: the caps must not undercount.
WEB_SEARCH_USD = 0.025


class LLMError(RuntimeError):
    """The model could not be used; the message is safe to show and to log."""


class BudgetExceeded(LLMError):
    """A run's budget or the spending cap is used up."""


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0  # part of input_tokens, billed at the cached rate
    output_tokens: int = 0

    def cost(self, price: ModelPrice) -> float:
        uncached = self.input_tokens - self.cached_input_tokens
        return (
            uncached * price.input
            + self.cached_input_tokens * price.cached_input
            + self.output_tokens * price.output
        ) / 1_000_000


@dataclass(frozen=True)
class WebAnswer:
    text: str
    urls: tuple[str, ...]  # the pages the answer cites
    cost_usd: float = 0.0


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict | None  # None when the model sent arguments that are not a JSON object
    error: str | None = None  # why the arguments were rejected, to send back to the model


@dataclass(frozen=True)
class Completion:
    text: str | None
    tool_calls: tuple[ToolCall, ...]
    model: str
    usage: Usage
    cost_usd: float
    latency_s: float

    def as_message(self) -> dict:
        """The assistant turn to append to the conversation."""
        message: dict = {"role": "assistant", "content": self.text}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments if call.arguments else {}),
                    },
                }
                for call in self.tool_calls
            ]
        return message


@dataclass
class Budget:
    """What one agent run may spend. Checked before each call, charged after it."""

    max_calls: int = 12
    max_tool_calls: int = 20
    max_cost_usd: float = 0.05
    calls: int = 0
    tool_calls: int = 0
    cost_usd: float = 0.0

    def check(self) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(f"The run reached its limit of {self.max_calls} model calls.")
        if self.cost_usd >= self.max_cost_usd:
            raise BudgetExceeded(f"The run reached its cost limit of ${self.max_cost_usd:.2f}.")

    def charge(self, completion: Completion) -> None:
        self.calls += 1
        self.cost_usd += completion.cost_usd
        self.tool_calls += len(completion.tool_calls)

    @property
    def tool_calls_left(self) -> int:
        return max(0, self.max_tool_calls - self.tool_calls)


@dataclass
class SpendLedger:
    """Total spending of this process against a hard cap."""

    cap_usd: float
    spent_usd: float = 0.0

    def check(self) -> None:
        if self.spent_usd >= self.cap_usd:
            raise BudgetExceeded(
                f"Model spending reached the cap of ${self.cap_usd:.2f}; raise "
                "FA_LLM_SPEND_CAP_USD to continue."
            )

    def charge(self, cost_usd: float) -> None:
        self.spent_usd += cost_usd


class LLM(Protocol):
    def complete(
        self,
        messages: list[dict],
        *,
        role: Role = Role.SMALL,
        tools: list[dict] | None = None,
        budget: Budget | None = None,
    ) -> Completion: ...

    def search(
        self, query: str, domains: Sequence[str], *, budget: Budget | None = None
    ) -> WebAnswer: ...


def _tool_call(raw) -> ToolCall:
    name, arguments = raw.function.name, raw.function.arguments
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return ToolCall(raw.id, name, None, "The arguments were not valid JSON.")
    if not isinstance(parsed, dict):
        return ToolCall(raw.id, name, None, "The arguments must be a JSON object.")
    return ToolCall(raw.id, name, parsed)


def _usage(raw) -> Usage:
    if raw is None:
        return Usage()
    details = getattr(raw, "prompt_tokens_details", None)
    return Usage(
        input_tokens=raw.prompt_tokens or 0,
        cached_input_tokens=(getattr(details, "cached_tokens", 0) or 0) if details else 0,
        output_tokens=raw.completion_tokens or 0,
    )


@contextmanager
def _safe_errors() -> Generator[None]:
    """OpenAI's failures as `LLMError`, with a message safe to show and to log."""
    try:
        yield
    except openai.AuthenticationError as exc:
        raise LLMError("OpenAI rejected the API key.") from exc
    except openai.RateLimitError as exc:
        raise LLMError("OpenAI is rate limiting or the account is out of credit.") from exc
    except openai.APITimeoutError as exc:
        raise LLMError("OpenAI took too long to answer.") from exc
    except openai.APIConnectionError as exc:
        raise LLMError("Could not reach OpenAI.") from exc
    except openai.APIStatusError as exc:
        raise LLMError(f"OpenAI returned an error ({exc.status_code}).") from exc


class OpenAILLM:
    def __init__(
        self,
        client,
        models: dict[Role, str],
        ledger: SpendLedger,
        clock=time.monotonic,
    ):
        unknown = [model for model in models.values() if model not in PRICES]
        if unknown:
            raise LLMError(f"No price is known for {', '.join(unknown)}; add it to PRICES.")
        self._client = client
        self._models = models
        self._ledger = ledger
        self._clock = clock

    @classmethod
    def from_settings(cls, settings, ledger: SpendLedger | None = None) -> "OpenAILLM":
        key = settings.openai_api_key.get_secret_value().strip() if settings.openai_api_key else ""
        if not key:
            raise LLMError("No OpenAI key: set FA_OPENAI_API_KEY in .env.")
        # The SDK retries timeouts, rate limits and server errors with backoff.
        client = openai.OpenAI(api_key=key, timeout=30, max_retries=3)
        models = {Role.SMALL: settings.openai_small_model, Role.LARGE: settings.openai_large_model}
        return cls(client, models, ledger or SpendLedger(cap_usd=settings.llm_spend_cap_usd))

    def complete(
        self,
        messages: list[dict],
        *,
        role: Role = Role.SMALL,
        tools: list[dict] | None = None,
        budget: Budget | None = None,
    ) -> Completion:
        if budget:
            budget.check()
        self._ledger.check()
        model = self._models[role]
        request: dict = {"model": model, "messages": messages}
        if tools:
            request["tools"] = tools
        started = self._clock()
        with _safe_errors():
            response = self._client.chat.completions.create(**request)

        message = response.choices[0].message
        usage = _usage(response.usage)
        completion = Completion(
            text=message.content,
            tool_calls=tuple(_tool_call(call) for call in message.tool_calls or ()),
            model=model,
            usage=usage,
            cost_usd=usage.cost(PRICES[model]),
            latency_s=self._clock() - started,
        )
        self._ledger.charge(completion.cost_usd)
        if budget:
            budget.charge(completion)
        return completion

    def search(
        self, query: str, domains: Sequence[str], *, budget: Budget | None = None
    ) -> WebAnswer:
        """One web search limited to `domains`, on the Responses API; its cost is charged here."""
        if budget:
            budget.check()
        self._ledger.check()
        model = self._models[Role.SMALL]
        with _safe_errors():
            response = self._client.responses.create(
                model=model,
                input=query,
                instructions="Answer in two or three plain sentences, from what you find.",
                tools=[{"type": "web_search", "filters": {"allowed_domains": list(domains)}}],
            )
        searches = sum(
            item.type == "web_search_call" and getattr(item.action, "type", "") == "search"
            for item in response.output
        )
        details = getattr(response.usage, "input_tokens_details", None)
        usage = Usage(
            input_tokens=response.usage.input_tokens,
            cached_input_tokens=(getattr(details, "cached_tokens", 0) or 0) if details else 0,
            output_tokens=response.usage.output_tokens,
        )
        cost = usage.cost(PRICES[model]) + searches * WEB_SEARCH_USD
        self._ledger.charge(cost)
        if budget:
            budget.calls += 1
            budget.cost_usd += cost
        urls = tuple(
            note.url
            for item in response.output
            if item.type == "message"
            for part in item.content
            for note in getattr(part, "annotations", None) or ()
            if note.type == "url_citation"
        )
        return WebAnswer(response.output_text or "", urls, cost)


@dataclass
class ScriptedLLM:
    """Replays prepared turns in order and records what it was asked. For tests and CI.

    A turn is a completion, or a function of the conversation so far that returns one (to cite
    evidence ids that only exist once tools have run).
    """

    turns: list[Completion | Callable[[list[dict]], Completion]] = field(default_factory=list)
    requests: list[dict] = field(default_factory=list)
    searches: list[WebAnswer] = field(default_factory=list)  # what `search` returns, in order
    searched: list[str] = field(default_factory=list)

    @staticmethod
    def say(text: str, cost_usd: float = 0.0) -> Completion:
        return Completion(text, (), "scripted", Usage(), cost_usd, 0.0)

    @staticmethod
    def call(
        name: str, call_id: str | None = None, cost_usd: float = 0.0, **arguments
    ) -> Completion:
        tool_call = ToolCall(call_id or f"call_{name}", name, arguments)
        return Completion(None, (tool_call,), "scripted", Usage(), cost_usd, 0.0)

    def complete(
        self,
        messages: list[dict],
        *,
        role: Role = Role.SMALL,
        tools: list[dict] | None = None,
        budget: Budget | None = None,
    ) -> Completion:
        if budget:
            budget.check()
        self.requests.append(
            {
                "messages": [dict(m) for m in messages],
                "role": role,
                "tools": [t["function"]["name"] for t in tools or ()],
            }
        )
        if not self.turns:
            raise LLMError("The script has no more turns.")
        turn = self.turns.pop(0)
        completion = turn(messages) if callable(turn) else turn
        if budget:
            budget.charge(completion)
        return completion

    def search(
        self, query: str, domains: Sequence[str], *, budget: Budget | None = None
    ) -> WebAnswer:
        if budget:
            budget.check()
        self.searched.append(query)
        if not self.searches:
            raise LLMError("The script has no more searches.")
        answer = self.searches.pop(0)
        if budget:
            budget.calls += 1
            budget.cost_usd += answer.cost_usd
        return answer
