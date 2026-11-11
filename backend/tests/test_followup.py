"""Short follow-ups, and points and drafts that were asked for."""

from app.agent.context import Turn
from app.agent.followup import needs_rewriting, standalone
from app.agent.knowledge import passage_evidence
from app.agent.llm import ScriptedLLM
from app.agent.personal import as_points, draft_check, top_up
from app.knowledge.build import Passage

LAST = Turn("Compare my steps on weekdays and weekends", "Weekdays 8,212, weekends 7,548.")


def test_only_a_short_message_that_refers_back_is_rewritten():
    assert needs_rewriting("Which one is higher?", [LAST])
    assert not needs_rewriting("Which one is higher?", [])
    assert not needs_rewriting("How many steps did I do on my best day last month?", [LAST])
    assert not needs_rewriting("what did you say about that?", [LAST])
    assert not needs_rewriting("Earlier request: x\nThat one", [LAST])


def test_a_follow_up_is_said_in_full():
    llm = ScriptedLLM([ScriptedLLM.say("Are my steps higher on weekdays or weekends?")])
    text, _ = standalone(llm, "Which one is higher?", [LAST])
    assert text == "Are my steps higher on weekdays or weekends?"


def test_a_rewrite_that_adds_numbers_is_not_used():
    llm = ScriptedLLM([ScriptedLLM.say("Is 8,212 higher than 7,548?")])
    assert standalone(llm, "Which one is higher?", [LAST])[0] == "Which one is higher?"


def test_when_the_model_is_down_the_question_stands():
    assert standalone(ScriptedLLM([]), "Which one is higher?", [LAST])[0] == "Which one is higher?"


def record(text, pid="p"):
    url = "https://example.com"
    return passage_evidence(Passage(pid, "t", text, "A guide", url, "p", "sleep", "guideline"))


def test_short_answers_are_filled_with_what_the_sources_say():
    records = [
        record("Keep your bedroom dark and quiet at night.", "a"),
        record("Sleep is a basic need of the body.", "b"),
        record("Avoid large meals close to bedtime.", "c"),
    ]
    added = top_up("You could try an earlier bedtime.", 3, 1, records)
    assert [a.tip for a in added] == [
        "Keep your bedroom dark and quiet at night.",
        "Avoid large meals close to bedtime.",
    ]


def test_a_point_already_made_is_not_repeated():
    records = [record("Keep your bedroom dark and quiet at night.")]
    assert top_up("Keep your bedroom dark and quiet at night.", 3, 1, records) == []


def test_enough_points_add_nothing():
    assert top_up("x", 2, 2, [record("Avoid large meals close to bedtime.")]) == []


def test_points_are_one_per_line():
    assert as_points("You could try one. You could try two.") == (
        "- You could try one.\n- You could try two."
    )


def test_a_log_request_must_end_in_a_draft_or_a_question():
    check = draft_check(lambda: False)
    assert check([], "Please confirm this draft.")
    assert check([], "How much did you eat?") == []
    assert draft_check(lambda: True)([], "Ready.") == []


# "The day before that"


def _day_turn(answer: str) -> list[Turn]:
    claim = {"text": "x", "kind": "day", "evidence_ids": ["e1"]}
    return [Turn("How many steps did I take yesterday?", answer, (claim,), "activity")]


def test_the_day_before_that_counts_from_the_answers_day_not_today():
    from datetime import date

    from app.agent.followup import with_relative_day

    turns = _day_turn("You took 9,504 steps yesterday, on Nov 10.")
    today = date(2026, 11, 11)
    assert with_relative_day("Sorry, I meant the day before that.", turns, today) == (
        "Sorry, I meant Monday Nov 9."
    )
    assert with_relative_day("and the previous day?", turns, today) == "and Monday Nov 9?"
    assert with_relative_day("And the next day?", turns, today) == "And Wednesday Nov 11?"


def test_a_relative_day_is_left_alone_when_it_cannot_be_placed():
    from datetime import date

    from app.agent.followup import with_relative_day

    today = date(2026, 11, 11)
    two = _day_turn("Nov 9 had 3,291 steps and Nov 10 had 9,504.")
    assert with_relative_day("and the day before that?", two, today) == "and the day before that?"
    none = _day_turn("You walked a lot yesterday.")
    assert with_relative_day("and the day before that?", none, today) == "and the day before that?"
    future = _day_turn("Today, Nov 11, you took 2,000 steps.")
    assert with_relative_day("and the day after that?", future, today) == "and the day after that?"
    assert with_relative_day("and last week?", future, today) == "and last week?"
    assert with_relative_day("the day before that?", [], today) == "the day before that?"


# What the person told us, lined up with the change they ask about


def test_an_event_during_the_change_is_put_in_front_of_the_agent():
    from datetime import UTC, date, datetime

    from app.agent.ask import events_during
    from app.agent.context import MemoryItem
    from app.analysis.evidence import Evidence, Window

    tested = [
        Evidence(
            tool="compare_windows",
            metrics=("sleep_minutes",),
            windows=(
                Window(start=date(2026, 8, 14), end=date(2026, 8, 20)),
                Window(start=date(2026, 7, 17), end=date(2026, 8, 13)),
            ),
            n=35,
            sufficient=True,
            stats={},
        )
    ]

    def item(text, start, end):
        return MemoryItem("event", text, text, (), datetime.now(UTC), 1.0, start, end)

    exams = item("Had exams", date(2026, 8, 15), date(2026, 8, 21))
    trip = item("Work trip", date(2026, 9, 17), date(2026, 9, 23))
    routine = MemoryItem("fact", "Works day shifts", "Works day shifts", (), datetime.now(UTC), 1.0)
    told = events_during([trip, routine, exams], tested)
    assert "Had exams (Aug 15 to Aug 21)" in told and "lined up" in told
    assert "Work trip" not in told and "day shifts" not in told
    assert events_during([trip, routine], tested) == ""


def test_the_rewrite_may_use_the_worked_out_day_and_falls_back_to_it():
    turns = _day_turn("You took 9,504 steps yesterday, on Nov 10.")
    means = "Sorry, I meant Monday Nov 9."
    rewrite = ScriptedLLM([ScriptedLLM.say("How many steps did I take on Monday Nov 9?")])
    asked, _ = standalone(rewrite, "Sorry, I meant the day before that.", turns, means)
    assert asked == "How many steps did I take on Monday Nov 9?"
    assert (
        "worked out from the answer: Sorry, I meant Monday Nov 9."
        in (rewrite.requests[0]["messages"][1]["content"])
    )
    # A rewrite adding any other number is refused; the worked-out day still goes on.
    wrong = ScriptedLLM([ScriptedLLM.say("How many steps did I take on Nov 8?")])
    assert standalone(wrong, "the day before that", turns, means)[0] == means
    assert standalone(ScriptedLLM([]), "the day before that", turns, means)[0] == means
