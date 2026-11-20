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


# ---- the same variant by meaning, and the passages already shown (the audit of 2026-11-19) ----


def exercise(title, kind="exercise"):
    return SimpleNamespace(passage=SimpleNamespace(title=title, kind=kind, id=title))


def picker(*items):
    from app.agent.world import PICK_VARIANT

    return ScriptedLLM([ScriptedLLM.call(PICK_VARIANT, items=list(items))])


def test_an_unweighted_squat_is_the_bodyweight_squat_by_meaning():
    from app.agent.llm import Budget

    weighted, bodyweight, barbell = map(
        exercise, ["Weighted Squat", "Bodyweight Squat", "Olympic Squat"]
    )
    guideline = exercise("Muscle-strengthening activity", kind="guideline")
    llm = picker(2)
    kept = for_topic([weighted, bodyweight, barbell, guideline], "unweighted squat", llm, Budget())
    assert kept == [bodyweight, guideline]
    assert "Bodyweight Squat" in llm.requests[0]["messages"][1]["content"]


def test_no_matching_variant_leaves_out_every_other_exercise():
    from app.agent.llm import Budget

    weighted, guideline = exercise("Weighted Squat"), exercise("Strength", kind="guideline")
    assert for_topic([weighted, guideline], "unweighted squat", picker(), Budget()) == [guideline]


def test_a_failed_pick_changes_nothing():
    from app.agent.llm import Budget

    weighted = exercise("Weighted Squat")
    llm = ScriptedLLM([says("not a tool call")])
    assert for_topic([weighted], "unweighted squat", llm, Budget()) == [weighted]


def test_a_word_for_word_title_is_the_fallback_without_a_model():
    """The pick is the model's whenever one is there (a word-for-word match once kept a variant
    the person did not ask for, v7); without one, titles matching the topic still decide."""
    bodyweight, weighted = exercise("Bodyweight Squat"), exercise("Weighted Squat")
    assert for_topic([weighted, bodyweight], "bodyweight squat") == [bodyweight]


BRIDGE = "exercises-2c4ee5687a74"  # "Butt Lift (Bridge)", whose text covers breathing


def test_a_follow_up_reads_the_passages_already_shown_first():
    from app.agent.knowledge import KNOWLEDGE_LOOKUP

    llm = ScriptedLLM(
        [
            ScriptedLLM.call(KNOWLEDGE_LOOKUP, query="bridge breathing"),
            says("Breathe out as you lift your hips."),
        ],
        embeddings_fail=True,
    )
    outside = SimpleNamespace(web=lambda *args: {"error": "disabled"})
    result = answer_world(llm, "And how do I breathe during it?", outside, active=[BRIDGE])
    [used] = [s["passage_ids"] for s in result.trace if s.get("type") == "guidance_passages"]
    assert used[0] == BRIDGE


def guidance_turn(topic, passages):
    state = {"guidance": [topic], "guidance_passages": passages}
    return Turn(f"How do I do a {topic}?", "Lift your hips.", request_state=state)


def asked_with(history, topic, reference):
    from app.agent.knowledge import KNOWLEDGE_LOOKUP

    llm = ScriptedLLM(
        [ScriptedLLM.call(KNOWLEDGE_LOOKUP, query="breathing"), says("Breathe out as you lift.")],
        request_turns=[
            ScriptedLLM.call(
                "read_request",
                kind="guidance",
                topics=[] if reference else [topic],
                guidance_reference=reference,
                guidance_question="How do I breathe during it?",
            )
        ]
        * 2,
        embeddings_fail=True,
    )
    outside = SimpleNamespace(web=lambda *args: {"error": "disabled"}, food=None)
    answer = ask(
        llm,
        Router("world"),
        planted(),
        "How do I breathe?",
        today=END,
        history=history,
        outside=outside,
    )
    ids = [s["passage_ids"] for s in answer.result.trace if s.get("type") == "guidance_passages"]
    request = next(s for s in answer.result.trace if s.get("type") == "request")
    return (ids[0] if ids else []), request["state"]


def test_the_same_movement_keeps_its_passages_and_saves_them_again():
    history = [guidance_turn("bridge", [BRIDGE])]
    used, state = asked_with(history, "bridge", reference=True)
    assert used[0] == BRIDGE and state["guidance_passages"][0] == BRIDGE


def test_another_movement_does_not_get_the_earlier_passages():
    history = [guidance_turn("bridge", [BRIDGE])]
    used, _ = asked_with(history, "plank", reference=False)
    assert BRIDGE not in used


# ---- a found passage is answered, not refused for its wording (the v4 audit) ----

PUSHUP = "exercises-45d94106bd20"


def lookup(query):
    from app.agent.knowledge import KNOWLEDGE_LOOKUP

    return ScriptedLLM.call(KNOWLEDGE_LOOKUP, query=query)


def test_a_reply_failing_its_check_is_rewritten_once_from_the_passages():
    llm = ScriptedLLM(
        [
            lookup("push-up"),
            says("Do 99999 push-ups every morning."),  # fails: a number in no passage
            says("Keep your body straight and lower your chest to the floor."),
        ],
        embeddings_fail=True,
    )
    outside = SimpleNamespace(web=lambda *args: {"error": "disabled"})
    result = answer_world(llm, "How do I do a push-up?", outside, active=[PUSHUP])
    assert result.stop_reason == "looked_up" and result.summary.startswith("Keep your body")
    assert "Your draft had these problems" in llm.requests[-1]["messages"][-1]["content"]


def test_the_prescribed_number_of_repetitions_is_not_a_medical_word():
    from app.agent.world import reply_problems

    reply = "Repeat for the prescribed number of repetitions."
    assert reply_problems(reply, {}) == []
    assert reply_problems("Take the prescribed medication.", {}) == ["uses medical words"]


def test_a_known_topic_is_looked_up_instead_of_asking_which():
    llm = ScriptedLLM(
        [says("Which routine do you mean?"), says("A book and dim lights can be part of it.")],
        embeddings_fail=True,
    )
    outside = SimpleNamespace(web=lambda *args: {"error": "disabled"})
    result = answer_world(
        llm, "Could that routine include a book and dimmer lighting?", outside, topic="wind-down"
    )
    assert result.summary != WHICH and result.stop_reason != "lookup_unclear"
