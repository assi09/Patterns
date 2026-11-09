"""A draft must say what the person said: the checks behind the logging tools."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.actions import schemas
from app.actions.schemas import FoodLog, WorkoutLog
from app.actions.stated import clock_times, durations, mismatch

BEIRUT = timezone(timedelta(hours=2))
NOW = datetime(2026, 11, 8, 18, 30, tzinfo=BEIRUT)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(schemas, "now", lambda: NOW)


def workout(start: datetime, minutes: int) -> WorkoutLog:
    return WorkoutLog(
        exercise_type="WEIGHTLIFTING",
        start_time=start,
        end_time=start + timedelta(minutes=minutes),
        active_seconds=minutes * 60,
    )


@pytest.mark.parametrize(
    "text, seconds",
    [
        ("duration 1 hour 30min", 5400),
        ("1h 30 mins", 5400),
        ("an hour and a half", 5400),
        ("1.5 hours", 5400),
        ("45 min", 2700),
        ("half an hour", 1800),
        ("an hour", 3600),
        ("two hours", 7200),
    ],
)
def test_durations_are_read_in_everyday_forms(text, seconds):
    assert durations(text) == {seconds}


def test_a_distance_in_metres_is_not_a_duration():
    assert durations("swam 500m") == set()


def test_clock_times_are_read():
    assert clock_times("started at 3 pm") == {(15, 0)}
    assert clock_times("12:30am") == {(0, 30)}
    assert clock_times("at 15:45") == {(15, 45)}
    assert clock_times("at 3:30") == {(3, 30), (15, 30)}


SAID = ["Log a workout im doing weightlifting started at 3 pm duration 1 hour 30min"]
AT_THREE = datetime(2026, 11, 8, 15, 0, tzinfo=BEIRUT)


def test_a_draft_matching_the_words_passes():
    assert mismatch(workout(AT_THREE, 90), SAID, NOW) is None


def test_a_shortened_workout_is_refused():
    assert "duration" in mismatch(workout(AT_THREE, 45), SAID, NOW)


def test_a_workout_moved_to_the_day_before_is_refused():
    problem = mismatch(workout(AT_THREE - timedelta(days=1), 90), SAID, NOW)
    assert "earlier day" in problem


def test_the_wrong_clock_time_is_refused_even_through_another_offset():
    # Right number on the wrong clock: 15:00 UTC is 17:00 for this person.
    start = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)
    assert "time" in mismatch(workout(start, 90), SAID, NOW)


def test_a_named_day_may_be_further_back():
    said = ["Log weightlifting yesterday at 3 pm for 90 minutes"]
    earlier = AT_THREE - timedelta(days=1)
    assert mismatch(workout(earlier, 90), said, NOW + timedelta(days=1)) is None


def test_a_correction_in_a_later_reply_counts():
    said = [*SAID, "sorry it was 45 min"]
    assert mismatch(workout(AT_THREE, 45), said, NOW) is None


def test_an_end_time_stated_instead_of_a_start_passes():
    assert mismatch(workout(AT_THREE, 90), ["weights, finished at 4:30 pm, 90 min"], NOW) is None


def test_a_workout_with_no_duration_is_refused():
    assert "how long" in mismatch(workout(AT_THREE, 37), ["log my weights session at 3 pm"], NOW)


def test_a_workout_up_to_now_needs_no_duration():
    start = NOW - timedelta(minutes=37)
    assert mismatch(workout(start, 37), ["log my weights, just finished"], NOW) is None


def test_two_clock_times_give_the_duration():
    assert mismatch(workout(AT_THREE, 90), ["weights from 3 pm to 4:30 pm"], NOW) is None


def test_a_workout_with_no_kind_is_refused():
    log = workout(AT_THREE, 90).model_copy(update={"exercise_type": "WORKOUT"})
    assert "what kind" in mismatch(log, ["Log a workout at 3 pm for 90 minutes"], NOW)
    assert mismatch(log, ["Log a circuit class at 3 pm for 90 minutes"], NOW) is None


def test_a_meal_at_the_wrong_time_is_refused():
    meal = FoodLog(
        food_name="apple",
        consumed_at=datetime(2026, 11, 8, 11, 0, tzinfo=BEIRUT),
        meal_type="SNACK",
        energy_kcal=95,
    )
    assert "time" in mismatch(meal, ["Log an apple at 10:30, 95 kcal"], NOW)
    assert mismatch(meal, ["Log an apple at 11:00, 95 kcal"], NOW) is None


def test_a_draft_is_described_from_its_own_values():
    from app.actions.tools import draft_sentence

    payload = {
        "kind": "workout",
        "exerciseType": "WEIGHTLIFTING",
        "startTime": "2026-11-07T15:00:00+02:00",
        "activeSeconds": 5400,
    }
    text = draft_sentence(payload, NOW)
    assert "yesterday at 15:00 for 1 h 30 min" in text


def test_a_reply_with_no_duration_is_noticed_before_a_draft_is_tried():
    from app.actions.stated import lacks_a_duration

    assert lacks_a_duration(["Log a workout", "Weightlifting"])
    assert not lacks_a_duration(["Log a workout", "45 minutes"])
    assert not lacks_a_duration(["weights, just finished"])


def test_a_time_that_has_not_come_yet_today_means_yesterday():
    from app.actions.stated import latest_past

    just_after_midnight = datetime(2026, 11, 9, 0, 20, tzinfo=BEIRUT)
    given = {"startTime": "2026-11-09T07:00:00+02:00", "endTime": "2026-11-09T07:30:00+02:00"}
    moved = latest_past(given, ["Log a run at 7 am for 30 minutes"], just_after_midnight)
    assert moved["startTime"].startswith("2026-11-08T07:00")
    assert moved["endTime"].startswith("2026-11-08T07:30")


def test_a_workout_already_started_is_not_moved():
    from app.actions.stated import latest_past

    given = {"startTime": "2026-11-08T15:00:00+02:00", "endTime": "2026-11-08T19:00:00+02:00"}
    assert latest_past(given, ["weights at 3 pm for 4 hours"], NOW) == given


def test_a_named_day_is_left_alone():
    from app.actions.stated import latest_past

    given = {"consumedAt": "2026-11-10T07:00:00+02:00"}
    assert latest_past(given, ["breakfast on Nov 10 at 7 am"], NOW) == given


def test_after_a_correction_only_the_corrected_duration_counts():
    said = ["Log a swim at 3 pm", "40 minutes, no wait it was 50 minutes"]
    assert "duration" in mismatch(workout(AT_THREE, 40), said, NOW)
    assert mismatch(workout(AT_THREE, 50), said, NOW) is None


def test_a_workout_just_finished_ends_now_not_later():
    from app.actions.stated import latest_past

    given = {"startTime": NOW.isoformat(), "endTime": (NOW + timedelta(minutes=20)).isoformat()}
    moved = latest_past(given, ["Log a 20 minute walk just now"], NOW)
    assert datetime.fromisoformat(moved["endTime"]) == NOW
    assert datetime.fromisoformat(moved["startTime"]) == NOW - timedelta(minutes=20)
