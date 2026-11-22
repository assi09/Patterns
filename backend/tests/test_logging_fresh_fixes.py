"""The second held-out logging run of 2026-11-22: durations with a number said in words ("an hour
and ten minutes", "thirty-five minutes") or "an hour and three quarters" were read as an hour or
as none, and refused right drafts; and one time of day with no am or pm ("from 10:50") counted as
two, so a draft of 7 minutes active in 70 was kept. Made-up data only."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.actions.schemas import WorkoutLog
from app.actions.stated import (
    clock_mentions,
    durations,
    lacks_a_duration,
    mismatch,
    with_stated_interval,
)


@pytest.mark.parametrize(
    "said, minutes",
    [
        ("it lasted an hour and ten minutes", 70),
        ("went for an hour and three quarters", 105),
        ("A volleyball game 2 days ago from 14:10, thirty-five minutes, add it", 35),
        ("thirty five minutes", 35),
        ("fifteen mins", 15),
        ("two hours", 120),
    ],
)
def test_a_number_said_in_words_is_a_duration(said, minutes):
    assert durations(said) == {minutes * 60} and not lacks_a_duration([said])


def test_a_number_word_without_a_unit_is_no_duration():
    assert durations("ten past nine, with three friends") == set()


def test_one_time_of_day_is_one_mention_however_it_reads():
    assert clock_mentions("from 10:50, 1h10") == 1
    assert clock_mentions("from 10:50 to 12:00") == 2
    # One start time alone gives no length: asked, never drafted with a made-up one.
    assert lacks_a_duration(["log a walk at 10:50"])
    assert not lacks_a_duration(["a walk from 10:50 to 11:30"])


def test_seven_minutes_active_in_seventy_is_refused_when_seventy_was_said():
    zone = ZoneInfo("Asia/Beirut")
    start = datetime(2026, 11, 20, 10, 50, tzinfo=zone)
    said = ["A volleyball game 2 days ago from 10:50, 1h10, add it"]
    drafted = WorkoutLog.model_validate(
        {
            "exercise_type": "VOLLEYBALL",
            "start_time": start,
            "end_time": start + timedelta(minutes=70),
            "active_seconds": 7 * 60,
        }
    )
    rebuilt = with_stated_interval(drafted, said)
    assert rebuilt.end_time == start + timedelta(minutes=7)  # no pause was said
    now = datetime(2026, 11, 22, 18, 0, tzinfo=zone)
    assert "does not match" in mismatch(rebuilt, said, now, day_known=True)
    right = with_stated_interval(drafted.model_copy(update={"active_seconds": 70 * 60}), said)
    assert mismatch(right, said, now, day_known=True) is None
