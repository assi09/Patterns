"""A how-to follow-up keeps its subject, and lets it change (the audit of 2026-11-18): "what
should I do with my hips during it?" after a plank question got hip-circle instructions."""

from types import SimpleNamespace

from test_broad_questions import END, Router, planted

from app.agent.ask import ask
from app.agent.context import Turn
from app.agent.llm import Completion, ScriptedLLM, Usage
from app.agent.world import WHICH, answer_world

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
