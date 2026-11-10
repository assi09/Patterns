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
