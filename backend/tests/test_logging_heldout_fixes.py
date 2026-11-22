"""The held-out logging run of 2026-11-22: a log for a day to come and a workout with no length
were answered "I couldn't pin that down"; "1h15" and "three quarters of an hour" were not read
as durations, so right drafts were refused; and HIIT, boxing and squash were carded as strength
training. Each case is one of the run's own requests, with its control; made-up data only."""

from datetime import UTC, datetime, timedelta

import pytest
from test_action_api import setup, sign_in  # noqa: F401 (the fixture)
from test_v5_reliability import reader_said, walk

from app.actions.exercises import in_sentence, named_type
from app.actions.stated import durations, lacks_a_duration
from app.agent.agent import NO_ANSWER, SUBMIT
from app.agent.ask import HOW_LONG, NOT_YET_LOGGABLE
from app.agent.llm import ScriptedLLM


@pytest.mark.parametrize(
    "said, minutes",
    [
        ("record a jog: yesterday, 15:15, 1h15, 12 km", 75),
        ("a 1h30m ride", 90),
        ("lasted three quarters of an hour", 45),
        ("three-quarters of an hour", 45),
        ("a quarter of an hour of stretching", 15),
        ("an hour and a quarter", 75),
        ("two and a half hours", 150),
        ("2 and a half hours", 150),
    ],
)
def test_quarters_and_run_together_hours_are_durations(said, minutes):
    assert durations(said) == {minutes * 60} and not lacks_a_duration([said])


def test_a_clock_time_is_still_no_duration():
    assert durations("yesterday at 15:15") == set() and lacks_a_duration(["yesterday at 15:15"])


@pytest.mark.parametrize(
    "said, exercise_type",
    [
        ("record a HIIT workout: yesterday, 7:45pm, 40 min", "HIIT"),
        ("I did a boxing session at 11:45am for 1.5 hours", "BOXING"),
        ("can you add a squash game I did yesterday at 15:30?", "SQUASH"),
        ("log a rowing machine session from yesterday", "ROWING_MACHINE"),  # not ROWING
        ("I did kickboxing for an hour", "KICKBOXING"),  # not BOXING
        ("log a run yesterday, 30 minutes", "RUNNING"),
    ],
)
def test_the_type_the_person_names_is_found(said, exercise_type):
    assert named_type(said) == exercise_type


@pytest.mark.parametrize(
    "said",
    [
        "a run on the treadmill",  # two types: the model decides
        "log my workout, 30 minutes",  # too general
        "a football game",  # soccer or American football: not decided by code
        "a spin class",  # no type's name
    ],
)
def test_no_type_or_several_leave_it_to_the_model(said):
    assert named_type(said) is None


def log_reading(words, entry="workout", duration=None, days=None, exercise_type=None):
    clause = {
        "type": "log",
        "said": words,
        "entry": entry,
        "duration_minutes": duration,
        "on_date": None,
        "days_from_today": days,
    }
    if exercise_type:
        clause["exercise_type"] = exercise_type
    return reader_said(clause)


@pytest.mark.parametrize(
    "words, entry, duration, days",
    [
        ("log a treadmill walk tomorrow at 11am, 40 minutes", "workout", 40, 1),
        ("record a veggie burger for dinner the day after tomorrow", "food", None, 2),
    ],
)
def test_a_log_for_a_day_to_come_says_so_without_the_model(setup, words, entry, duration, days):  # noqa: F811
    client, _, agent = setup
    headers = sign_in(setup)
    agent.llm.request_turns = [log_reading(words, entry, duration, days)]
    agent.llm.turns = []  # no model call: a draft is impossible, so code says why
    reply = client.post("/chat", headers=headers, json={"text": words}).json()[-1]
    assert reply["text"] == NOT_YET_LOGGABLE and not reply.get("actionIds")
    assert client.get("/actions", headers=headers).json() == []


def test_a_workout_with_no_length_is_asked_and_the_answer_finishes_it(setup):  # noqa: F811
    client, _, agent = setup
    headers = sign_in(setup)
    words = "log a spin class from two days ago"
    agent.llm.request_turns = [log_reading(words, days=-2)]
    agent.llm.turns = []
    first = client.post("/chat", headers=headers, json={"text": words}).json()[-1]
    assert first["text"] == HOW_LONG and not first.get("actionIds")

    start = (datetime.now(UTC) - timedelta(days=2)).replace(microsecond=0)
    agent.llm.request_turns = [log_reading("45 minutes", duration=45, days=-2)]
    agent.llm.turns = [
        ScriptedLLM.call("propose_workout_log", **(walk(start, 45) | {"exerciseType": "SPINNING"})),
        ScriptedLLM.call(SUBMIT, summary="Draft ready.", claims=[]),
    ]
    second = client.post(
        "/chat",
        headers=headers,
        json={"text": "45 minutes", "conversationId": first["conversationId"]},
    ).json()[-1]
    assert second.get("actionIds") and second["text"] != NO_ANSWER
    (entry,) = client.get("/actions", headers=headers).json()
    assert entry["log"]["activeSeconds"] == 45 * 60


def test_a_workout_with_its_length_is_not_asked_again(setup):  # noqa: F811
    """The control: "1h15" is a length, so the draft is made, never "how long?"."""
    client, _, agent = setup
    headers = sign_in(setup)
    words = "record a jog: yesterday, 15:15, 1h15, 12 km"
    start = (datetime.now(UTC) - timedelta(days=1)).replace(hour=15, minute=15, microsecond=0)
    agent.llm.request_turns = [log_reading(words, duration=75, days=-1, exercise_type="RUNNING")]
    agent.llm.turns = [
        ScriptedLLM.call("propose_workout_log", **(walk(start, 75) | {"exerciseType": "RUNNING"})),
        ScriptedLLM.call(SUBMIT, summary="Draft ready.", claims=[]),
    ]
    reply = client.post("/chat", headers=headers, json={"text": words}).json()[-1]
    assert reply.get("actionIds") and reply["text"] != HOW_LONG


def test_the_named_type_wins_over_the_models_choice(setup):  # noqa: F811
    client, _, agent = setup
    headers = sign_in(setup)
    words = "record a HIIT workout: yesterday, 7:45pm, 40 min"
    start = (datetime.now(UTC) - timedelta(days=1)).replace(hour=19, minute=45, microsecond=0)
    agent.llm.request_turns = [log_reading(words, duration=40, days=-1)]
    agent.llm.turns = [
        ScriptedLLM.call(
            "propose_workout_log", **(walk(start, 40) | {"exerciseType": "STRENGTH_TRAINING"})
        ),
        ScriptedLLM.call(SUBMIT, summary="Draft ready.", claims=[]),
    ]
    client.post("/chat", headers=headers, json={"text": words})
    (entry,) = client.get("/actions", headers=headers).json()
    assert entry["log"]["exerciseType"] == "HIIT"


@pytest.mark.parametrize(
    "exercise_type, said",
    [("HIIT", "HIIT"), ("TRX", "TRX"), ("RUNNING", "run"), ("ROWING_MACHINE", "rowing machine")],
)
def test_a_name_inside_a_sentence_keeps_an_acronym(exercise_type, said):
    assert in_sentence(exercise_type) == said
