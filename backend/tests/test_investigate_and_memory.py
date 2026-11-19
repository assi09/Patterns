"""Investigations and memory requests reach their own paths (the audit of 2026-11-19: broad
why/coaching passed 5 of 16 and memory 0 of 5, as the request reader had no kind for either).
Made-up data and scripted model replies only."""

from datetime import UTC, date, datetime

import pytest
from test_broad_questions import END, ON, Router, planted, submit

from app.agent.ask import MEMORY_WHICH, NOT_KEPT_ASKED, NOTED, ask, recalled
from app.agent.context import ChatState, MemoryItem, Turn
from app.agent.llm import ScriptedLLM
from app.agent.requests import Reading, anchored_by_code
from app.synthetic import Step


def reading_llm(*agent_turns, **fields):
    """A model whose request reader returns `fields`, then the agent's scripted turns."""
    return ScriptedLLM(
        list(agent_turns), request_turns=[ScriptedLLM.call("read_request", **fields)] * 2
    )


@pytest.fixture(scope="module")
def steps_fell():
    return planted(Step("steps", ON, -5000.0))


# ---- investigations ----


def test_an_investigation_naming_nothing_gets_every_metric_compared(steps_fell):
    llm = reading_llm(submit(), kind="investigate", focus="why", parts=[])
    reply = ask(llm, Router("lookup"), steps_fell, "Why do I feel so drained?", today=END)
    task = llm.requests[-1]["messages"][1]["content"]
    assert "Overview: all" in task and reply.route.action == "general"


def test_an_investigation_keeps_the_days_it_named(steps_fell):
    period = {"kind": "explicit", "start": "2026-09-01", "end": "2026-09-30"}
    llm = reading_llm(
        submit(),
        kind="investigate",
        focus="what_changed",
        parts=[{"metrics": [], "operation": "describe", "periods": [period]}],
    )
    reply = ask(llm, Router("lookup"), steps_fell, "What changed in September?", today=END)
    recent = {
        (e.windows[0].start, e.windows[0].end)
        for e in reply.result.evidence.values()
        if e.stats.get("overview") and e.tool == "compare_windows"
    }
    assert recent == {(date(2026, 9, 1), date(2026, 9, 30))}


def test_an_investigation_of_one_metric_keeps_that_metric_and_runs_no_overview(steps_fell):
    llm = reading_llm(
        submit(),
        kind="investigate",
        focus="why",
        parts=[{"metrics": ["sleep_minutes"], "operation": "describe", "periods": []}],
    )
    ask(llm, Router("lookup"), steps_fell, "Why has my sleep been short?", today=END)
    task = llm.requests[-1]["messages"][1]["content"]
    assert "Overview: all" not in task and "time asleep" in task


# ---- memory ----


def test_remember_raises_the_card_whatever_else_the_reader_thought():
    llm = reading_llm(kind="guidance", memory="deny", topics=["walking"])
    reply = ask(llm, Router("chat"), planted(), "Remember that I prefer walking.", today=END)
    assert reply.result.stop_reason == "noted" and reply.result.summary == NOTED


def test_do_not_save_wins_even_beside_remember():
    llm = reading_llm(kind="memory", memory_action="remember")
    said = "Remember this but don't save it: I run on Mondays."
    reply = ask(llm, Router("chat"), planted(), said, today=END)
    assert reply.result.stop_reason != "noted" and reply.result.summary == NOT_KEPT_ASKED


@pytest.mark.parametrize(
    "said, model, code",
    [
        ("Remember that I prefer walking", "deny", "unspecified"),
        ("Don't save this: I work nights", "unspecified", "deny"),
        ("Remember it, but do not store it", "unspecified", "deny"),
    ],
)
def test_code_reads_save_and_do_not_save_itself(said, model, code):
    reading = Reading(kind="memory", memory=model, memory_action="remember")
    assert anchored_by_code(reading, said).memory == code


def test_an_unclear_memory_request_is_asked_about():
    llm = reading_llm(kind="memory")
    reply = ask(llm, Router("chat"), planted(), "What about my memory thing?", today=END)
    assert reply.result.summary == MEMORY_WHICH


def kept(text, kind="fact"):
    return MemoryItem(kind, "id-" + text[:4], text, (), datetime(2026, 11, 1, tzinfo=UTC), 1.0)


def test_recall_keeps_kept_waiting_and_said_here_apart():
    chat = ChatState(kept=("I'm training for a 10k",), pending=("I prefer walking",))
    history = [Turn("I'm a student and I had projects this week.", "Noted.")]
    text = recalled([kept("I go to bed late on Fridays")], chat, history)
    kept_part, rest = text.split("Waiting for your tap", 1)
    assert "10k" in kept_part and "Fridays" in kept_part and "walking" not in kept_part
    waiting_part, said_part = rest.split("You mentioned in this chat", 1)
    assert "walking" in waiting_part and "student" in said_part
    assert "student" not in kept_part  # said here is never presented as kept


def test_recall_with_nothing_says_so():
    assert recalled([], ChatState(), []).startswith("I haven't kept anything")


def test_a_recall_question_is_answered_from_memory_without_the_agent():
    llm = reading_llm(kind="memory", memory_action="recall")
    chat = ChatState(kept=("I'm training for a 10k",))
    reply = ask(
        llm, Router("chat"), planted(), "What do you remember about me?", today=END, chat=chat
    )
    assert "10k" in reply.result.summary and len(llm.requests) == 1  # only the reader


def test_an_inferred_interest_is_never_presented_as_kept():
    """The profile also holds "Often looks at: ...", worked out from use, never approved."""
    chat = ChatState(profile=("Often looks at: sleep, steps",), kept=())
    assert "Often looks at" not in recalled([], chat, [])


def test_the_reader_s_cost_and_reading_are_kept_on_the_remember_path():
    llm = reading_llm(kind="memory", memory_action="remember")
    reply = ask(
        llm, Router("chat"), planted(), "Could you remember that I prefer walking?", today=END
    )
    assert reply.result.stop_reason == "noted"
    assert reply.result.budget.calls >= 1
    assert any(step.get("type") == "request" for step in reply.result.trace)


def test_a_polite_or_forget_request_reaches_its_action_not_a_question():
    for said, action in (
        ("Could you remember that I prefer walking?", "remember"),
        ("Please forget my old running goal.", "forget"),
    ):
        llm = reading_llm(kind="memory", memory_action=action)
        reply = ask(llm, Router("chat"), planted(), said, today=END)
        assert reply.result.summary != MEMORY_WHICH and reply.result.stop_reason == "noted"
