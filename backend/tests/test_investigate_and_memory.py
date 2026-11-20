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


# ---- an investigation keeps the scope it names or points at ----


def earlier(*parts):
    from app.agent.requests import ResolvedPart
    from app.analysis.evidence import Window

    return {
        "data": [
            ResolvedPart(
                metrics=[metric], operation="mean", windows=[Window(start=start, end=end)]
            ).model_dump(mode="json")
            for metric, start, end in parts
        ]
    }


def investigate(*parts, state=None, today=END):
    from app.agent.requests import Part, resolve

    reading = Reading(kind="investigate", focus="why", parts=[Part(**p) for p in parts])
    return resolve(reading, state or {}, today)


STEPS_OCT = ("steps", date(2026, 10, 1), date(2026, 10, 14))
SLEEP_SEP = ("sleep_minutes", date(2026, 9, 1), date(2026, 9, 30))


def test_why_did_that_happen_keeps_the_earlier_metric_and_days():
    got = investigate({"periods": [{"kind": "inherit"}]}, state=earlier(STEPS_OCT))
    assert got.parts[0].metrics == ["steps"]
    assert (got.parts[0].windows[0].start, got.parts[0].windows[0].end) == STEPS_OCT[1:]


def test_a_chosen_earlier_part_is_the_one_investigated():
    got = investigate(
        {"reference": 1, "periods": [{"kind": "inherit"}]}, state=earlier(STEPS_OCT, SLEEP_SEP)
    )
    assert got.parts[0].metrics == ["sleep_minutes"]


def test_two_earlier_parts_and_no_choice_is_asked_about():
    from app.agent.requests import Ambiguous

    with pytest.raises(Ambiguous):
        investigate({"periods": [{"kind": "inherit"}]}, state=earlier(STEPS_OCT, SLEEP_SEP))


def test_every_metric_over_the_earlier_days_is_not_narrowed_to_one():
    got = investigate(
        {"periods": [{"kind": "inherit"}], "every_metric": True}, state=earlier(STEPS_OCT)
    )
    assert got.parts[0].metrics == [] and got.parts[0].windows[0].start == STEPS_OCT[1]


def test_an_unknown_metric_beside_a_known_one_is_asked_about_not_dropped():
    from app.agent.requests import Ambiguous

    with pytest.raises(Ambiguous):
        investigate({"metrics": ["steps", "made_up_metric"], "periods": []})


def test_two_named_periods_are_both_kept():
    sep = {"kind": "explicit", "start": "2026-09-01", "end": "2026-09-30"}
    aug = {"kind": "explicit", "start": "2026-08-01", "end": "2026-08-31"}
    got = investigate({"metrics": ["steps"], "periods": [sep, aug]})
    assert [w.start.month for w in got.parts[0].windows] == [9, 8]


# ---- the named days are the days answered ----


def test_days_the_data_never_reaches_are_answered_so_by_code(steps_fell):
    december = {"kind": "explicit", "start": "2026-12-01", "end": "2026-12-14"}
    llm = reading_llm(
        kind="investigate", focus="what_changed", parts=[{"metrics": [], "periods": [december]}]
    )
    reply = ask(llm, Router("lookup"), steps_fell, "What changed Dec 1 to 14?", today=END)
    assert reply.result.summary.startswith("Your data has no days from")
    assert len(llm.requests) == 1  # only the reader: no agent to wander off to October


def test_a_short_named_period_is_described_on_exactly_its_days(steps_fell):
    from app.agent.strategy import overview_evidence
    from app.analysis.evidence import Window

    days = Window(start=date(2026, 9, 1), end=date(2026, 9, 3))
    records, text = overview_evidence(steps_fell, "What changed?", END, days)
    assert records and all(e.tool == "describe" and e.windows == (days,) for e in records)
    assert "Too few days" in text


def test_a_second_named_period_is_the_baseline(steps_fell):
    from app.agent.strategy import overview_evidence
    from app.analysis.evidence import Window

    sep = Window(start=date(2026, 9, 1), end=date(2026, 9, 30))
    jul = Window(start=date(2026, 7, 1), end=date(2026, 7, 31))
    records, _ = overview_evidence(
        steps_fell, "How did September compare with July?", END, sep, jul
    )
    assert records and all(e.windows == (sep, jul) for e in records)


def test_coaching_on_a_named_month_uses_that_month_and_no_latest_day(steps_fell):
    from test_broad_questions import submit

    september = {"kind": "explicit", "start": "2026-09-01", "end": "2026-09-30"}
    llm = reading_llm(
        submit(),
        kind="investigate",
        focus="coaching",
        parts=[{"metrics": ["sleep_minutes"], "periods": [september]}],
    )
    question = "What could I try for my short sleep in September?"
    reply = ask(llm, Router("lookup"), steps_fell, question, today=END)
    personal = [e for e in reply.result.evidence.values() if e.tool != "public_guidance"]
    assert personal and all(
        w.start >= date(2026, 9, 1) and w.end <= date(2026, 9, 30)
        for e in personal
        for w in e.windows
    )


# ---- the answer does what was asked: an option for coaching, the limits for a why ----


def test_coaching_that_gives_no_option_gets_one_from_code_or_says_why_not(steps_fell):
    from test_broad_questions import submit

    from app.agent.ask import coaching_fallback

    llm = reading_llm(
        submit(),
        kind="investigate",
        focus="coaching",
        parts=[{"metrics": ["sleep_minutes"], "operation": "describe", "periods": []}],
    )
    reply = ask(llm, Router("lookup"), steps_fell, "What could I try for my sleep?", today=END)
    habits = [e for e in reply.result.evidence.values() if e.tool == "habit_options"]
    # Code's conclusion is the reply's, not a note beside the model's words (review of 1e29f3a).
    assert reply.result.summary.endswith(coaching_fallback(habits))
    assert coaching_fallback(habits) not in reply.result.notes


def test_a_why_with_no_tested_relationship_says_what_it_cannot_tell(steps_fell):
    from test_broad_questions import submit

    from app.agent.ask import WHY_LIMIT

    llm = reading_llm(submit(), kind="investigate", focus="why", parts=[])
    reply = ask(llm, Router("lookup"), steps_fell, "Why do I feel so drained?", today=END)
    assert WHY_LIMIT in reply.result.notes


def test_the_coaching_fallback_names_a_supported_habit_first():
    from app.agent.ask import coaching_fallback
    from app.analysis.evidence import Evidence, Window

    record = Evidence(
        tool="habit_options",
        metrics=("sleep_minutes",),
        windows=(Window(start=date(2026, 9, 1), end=date(2026, 10, 10)),),
        n=40,
        sufficient=True,
        stats={
            "levers": [
                {"habit": "a later wake time", "supported": False},
                {"habit": "an earlier bedtime", "supported": True},
            ]
        },
    )
    assert "an earlier bedtime" in coaching_fallback([record])
    assert coaching_fallback([]).startswith("Your data over those days isn't enough")
