"""A how-to follow-up keeps its subject, and lets it change (the audit of 2026-11-18): "what
should I do with my hips during it?" after a plank question got hip-circle instructions."""

from types import SimpleNamespace

from test_broad_questions import END, Router, planted

from app.agent.ask import ask
from app.agent.context import Turn
from app.agent.llm import Completion, ScriptedLLM, Usage
from app.agent.world import WHICH, answer_world, for_topic

PLANK = "How do I do a basic plank? Give the source for the instructions."


def says(text):
    return Completion(text, (), "scripted", Usage(), 0.0, 0.0)


def lookup_task(llm):
    return llm.requests[0]["messages"][1]["content"]


def test_the_lookup_is_told_what_it_refers_to():
    llm = ScriptedLLM([says("no")])
    answer_world(llm, "What should I do with my hips during it?", None, earlier=PLANK)
    assert "basic plank" in lookup_task(llm)


def test_without_an_earlier_question_nothing_is_added():
    llm = ScriptedLLM([says("no")])
    answer_world(llm, "How do I do a squat?", None)
    assert "just before" not in lookup_task(llm)


def test_when_it_could_mean_two_things_the_person_is_asked():
    llm = ScriptedLLM([says("which")])
    result = answer_world(llm, "What about my hips during it?", None, earlier="Plank or bridge?")
    assert result.summary == WHICH and result.stop_reason == "lookup_unclear"


def ask_after_plank(question):
    llm = ScriptedLLM([says("no")])
    history = [Turn(PLANK, "Hold a straight line from head to heels.", answered_by="general")]
    outside = SimpleNamespace(web=None, food=None)
    ask(llm, Router("world"), planted(), question, today=END, history=history, outside=outside)
    return lookup_task(llm)


def test_a_follow_up_about_it_carries_the_plank():
    assert "basic plank" in ask_after_plank("What should I do with my hips during it?")


def test_a_new_exercise_replaces_the_topic():
    """Naming another exercise is a new question: the plank is not passed along."""
    assert "basic plank" not in ask_after_plank("How do I do a squat properly?")


def test_matching_variants_are_selected_without_a_list_of_exercise_names():
    def found(title):
        return SimpleNamespace(passage=SimpleNamespace(title=title, kind="exercise"))

    bodyweight, weighted, dumbbell = map(
        found, ["Bodyweight Squat", "Weighted Squat", "Dumbbell Squat"]
    )
    assert for_topic([weighted, bodyweight, dumbbell], "bodyweight squats") == [bodyweight]
    regular, qualified = map(found, ["Plank", "RKC Plank"])
    assert for_topic([qualified, regular], "plank form") == [regular]
    assert for_topic([regular, qualified], "RKC plank form") == [qualified]
    assert for_topic([weighted], "unmatched exercise") == [weighted]


def test_a_failed_grounded_reply_cannot_fall_back_to_the_first_exercise_variant():
    from app.agent.knowledge import KNOWLEDGE_LOOKUP

    llm = ScriptedLLM(
        [
            ScriptedLLM.call(KNOWLEDGE_LOOKUP, query="glute bridge"),
            ScriptedLLM.say("Hold the bridge for 99999 seconds."),
        ],
        embeddings_fail=True,
    )
    outside = SimpleNamespace(web=lambda *args: {"error": "disabled"})
    result = answer_world(llm, "Where do my feet go in the bridge?", outside, topic="glute bridge")
    assert any(s.get("type") == "reply" and s.get("problems") for s in result.trace)
    assert result.stop_reason == "lookup_failed" and "couldn't confirm" in result.summary
