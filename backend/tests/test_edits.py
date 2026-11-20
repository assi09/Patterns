"""A follow-up edits an earlier result or the waiting card: the reader sees the object as it is
and says only what changes, and code applies the change and keeps the rest (the a196 audit and
its root-cause review). Made-up data only."""

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from test_action_api import setup, sign_in  # noqa: F401 (the fixture)
from test_clauses import data, dates, earlier, read, said, windows
from test_v5_reliability import log_first, reader_said, walk

from app.actions.schemas import WorkoutLog
from app.actions.tools import _untouched_changed
from app.agent.context import Turn
from app.agent.llm import ScriptedLLM
from app.agent.requests import Request, interpret
from app.api import chat

TODAY = date(2026, 11, 19)


def from_earlier(landmark, offset, boundary, length):
    return {
        "kind": "from_earlier",
        "landmark": landmark,
        "offset": offset,
        "boundary": boundary,
        "length": length,
    }


# ---- an earlier result's days: one computation for every edit ----

OCT = earlier("2026-10-13", "2026-10-17", "resting_hr", "mean")  # five days


@pytest.mark.parametrize(
    "span, start, end",
    [
        # the a196 families: forward block, block ending before, trailing narrowing, second day
        (from_earlier("its_last_day", 1, "starts_there", 4), "2026-10-18", "2026-10-21"),
        (from_earlier("its_first_day", -1, "ends_there", 4), "2026-10-09", "2026-10-12"),
        (from_earlier("its_last_day", 0, "ends_there", 3), "2026-10-15", "2026-10-17"),
        (from_earlier("its_first_day", 1, "starts_there", 4), "2026-10-14", "2026-10-17"),
        # no number of days said: the reader writes the earlier five (a shift, the same days)
        (from_earlier("its_first_day", 1, "starts_there", 5), "2026-10-14", "2026-10-18"),
        (from_earlier("its_first_day", -2, "starts_there", 5), "2026-10-11", "2026-10-15"),
        (from_earlier("its_first_day", 0, "starts_there", 5), "2026-10-13", "2026-10-17"),
    ],
)
def test_every_edit_of_an_earlier_period_is_one_computation(span, start, end):
    words = "Same measure, new days."
    clause = data(words, ["resting_hr"], "mean", span, earlier_result=0)
    request, calls = read(words, said(clause), history=[OCT])
    assert windows(request) == [(date.fromisoformat(start), date.fromisoformat(end))]
    assert calls == 1


def test_a_day_one_of_four_is_not_the_whole_period_moved():
    """ "Move one day on from the first date; that day is day one of my new four-day average"
    was read as the five-day period shifted (a196): with the length said, it is four days."""
    four = from_earlier("its_first_day", 1, "starts_there", 4)
    shifted = from_earlier("its_first_day", 1, "starts_there", 5)
    request, _ = read(
        "x", said(data("x", ["resting_hr"], "mean", four, earlier_result=0)), history=[OCT]
    )
    moved, _ = read(
        "x", said(data("x", ["resting_hr"], "mean", shifted, earlier_result=0)), history=[OCT]
    )
    assert windows(request) == [(date(2026, 10, 14), date(2026, 10, 17))]
    assert windows(moved) == [(date(2026, 10, 14), date(2026, 10, 18))]


def test_the_reader_sees_each_earlier_result_with_its_days_and_the_card_with_its_fields():
    llm = ScriptedLLM(
        request_turns=[
            ScriptedLLM.call(
                "read_request",
                **said(data("x", ["resting_hr"], "mean", dates("2026-10-01"), earlier_result=0)),
            )
        ]
    )
    card = {"kind": "workout", "day": "2026-10-21 (Wed)", "active_minutes": 38.0}
    interpret(llm, "x", [OCT], TODAY, pending_draft=True, draft=card, read_back=False)
    shown = json.loads(llm.requests[0]["messages"][1]["content"])
    (result,) = shown["earlier_results"]
    assert result["earlier_result"] == 0 and result["metrics"] == ["resting_hr"]
    assert result["periods"] == [
        {"first_day": "2026-10-13 (Tue)", "last_day": "2026-10-17 (Sat)", "days": 5}
    ]
    assert shown["pending_draft"] == card and "data" not in shown["state"]


# ---- the waiting card: the change is said against the card, the rest is kept ----

ZONE = ZoneInfo("UTC")


def paused(start: datetime) -> dict:
    return walk(start, 50, active=38)  # 12 minutes paused


@pytest.mark.parametrize(
    "said_minutes, offset, minutes, moved",
    [
        (50, 1, None, 1),  # the a196 reading: the elapsed 50 minutes is no change
        (38, 1, None, 1),  # nor the active 38
        (None, -2, None, -2),  # counted from the card, not from today
        (45, None, 45, 0),  # a new duration is a change
    ],
)
def test_a_correction_is_worked_out_against_the_card(said_minutes, offset, minutes, moved):
    start = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)
    typed = Request(kind="correction", duration_minutes=said_minutes, card_day_offset=offset)
    got_minutes, day = chat.card_edit(paused(start), typed, ZONE)
    assert got_minutes == minutes
    assert day == (date(2026, 10, 21) + timedelta(days=moved) if moved else None)


def test_an_explicit_date_wins_over_the_card():
    typed = Request(kind="correction", log_day=date(2026, 10, 25), card_day_offset=1)
    _, day = chat.card_edit(paused(datetime(2026, 10, 21, 15, tzinfo=UTC)), typed, ZONE)
    assert day == date(2026, 10, 25)


def test_a_replacement_that_changes_an_untouched_duration_is_named():
    start = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)
    prior = paused(start)
    moved = start + timedelta(days=1)

    def log(active, elapsed):
        return WorkoutLog.model_validate(
            {
                "exercise_type": "WALKING",
                "start_time": moved,
                "end_time": moved + timedelta(minutes=elapsed),
                "active_seconds": active * 60,
            }
        )

    assert _untouched_changed(log(38, 50), prior) is None
    assert _untouched_changed(log(50, 50), prior) == "active time"
    assert _untouched_changed(log(38, 38), prior) == "elapsed time"


MOVE = "Move that walk to one day later. Keep everything else the same."


def move(client, headers, agent, first, clause):
    agent.llm.request_turns = [reader_said(clause)]
    # A drafting model that would lose the pause, if it were asked: it is not.
    agent.llm.turns = [
        ScriptedLLM.call("propose_workout_log", kind="workout", exerciseType="WALKING")
    ] * 3
    return client.post(
        "/chat", headers=headers, json={"text": MOVE, "conversationId": first["conversationId"]}
    ).json()[-1]


@pytest.mark.parametrize("duration", [50, None])
def test_moving_a_paused_workout_a_day_keeps_its_pause_and_clock(setup, duration):  # noqa: F811
    """Both a196 date-only edits failed: one turned the pause into active time, one moved the
    card to the day after the clock. Code applies the edit to the stored card first."""
    client, _, agent = setup
    headers = sign_in(setup)
    start = (datetime.now(UTC) - timedelta(days=4)).replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    words = f"Log my walk on {start:%B} {start.day}: 50 minutes in all, 12 of them paused."
    first = log_first(client, headers, agent, paused(start), words)
    clause = {
        "type": "correct",
        "said": MOVE,
        "duration_minutes": duration,
        "on_date": None,
        "days_from_today": None,
        "days_from_card": 1,
    }
    before = len(agent.llm.requests)
    second = move(client, headers, agent, first, clause)
    assert second["actionIds"] and second["actionIds"] != first["actionIds"], second["text"]
    assert "Ready to log" in second["text"]
    entries = {e["id"]: e for e in client.get("/actions", headers=headers).json()}
    old, new = entries[first["actionIds"][0]], entries[second["actionIds"][0]]
    assert old["status"] == "cancelled" and new["status"] == "draft"
    began = datetime.fromisoformat(new["log"]["startTime"])
    ended = datetime.fromisoformat(new["log"]["endTime"])
    assert began == start + timedelta(days=1)
    assert ended - began == timedelta(minutes=50) and new["log"]["activeSeconds"] == 38 * 60
    reopened = client.get(
        "/chat", headers=headers, params={"conversation": first["conversationId"]}
    ).json()[-1]
    assert reopened["actionIds"] == second["actionIds"]
    drafted = [r for r in agent.llm.requests[before:] if "propose_workout_log" in str(r["tools"])]
    assert not drafted  # no drafting model was asked to touch the card


def test_with_no_card_waiting_a_correction_reading_goes_back_once():
    """ "Start at the next date and cover three days" with no card waiting was read as moving a
    card a day (the matched comparison): a correction needs a card, so the reading is sent back."""
    words = "Leave the measure and calculation alone. Start at the next date and cover three days."
    card_move = {"type": "correct", "said": words, "days_from_card": 1}
    block = data(words, ["resting_hr"], "mean", from_earlier("its_last_day", 1, "starts_there", 3))
    block["earlier_result"] = 0
    request, calls = read(words, said(card_move), said(block), history=[OCT])
    assert request.kind == "data" and calls == 2
    assert windows(request) == [(date(2026, 10, 18), date(2026, 10, 20))]


# ---- explaining or coaching keeps the comparison; what changed is later against earlier ----

LATER = {"start": "2026-10-10", "end": "2026-10-30"}
SOONER = {"start": "2026-09-19", "end": "2026-10-09"}
LOOKED = Turn(
    "What changed from Oct 10-30 against the three weeks before?",
    "Steps went up.",
    request_state={"data": [{"metrics": [], "operation": "describe", "windows": [LATER, SOONER]}]},
)


def investigate(words, focus, *periods):
    return {
        "type": "investigate",
        "said": words,
        "focus": focus,
        "metrics": [],
        "periods": list(periods),
        "earlier_result": None,
        "every_metric": False,
    }


@pytest.mark.parametrize("focus", ["why", "coaching"])
def test_a_goal_only_follow_up_keeps_the_comparison_under_discussion(focus):
    """ "Give me three distinct ideas" widened Oct 10-30 to two months (the a196 audit)."""
    words = "Give me three distinct ideas from that."
    request, calls = read(words, said(investigate(words, focus)), history=[LOOKED])
    assert windows(request) == [
        (date(2026, 10, 10), date(2026, 10, 30)),
        (date(2026, 9, 19), date(2026, 10, 9)),
    ]
    assert calls == 1


def test_a_new_broad_question_does_not_inherit_the_comparison():
    words = "What has changed lately?"
    request, _ = read(words, said(investigate(words, "overview")), history=[LOOKED])
    assert windows(request) != windows_of(LOOKED)


def windows_of(turn):
    return [
        (date.fromisoformat(w["start"]), date.fromisoformat(w["end"]))
        for w in turn.request_state["data"][0]["windows"]
    ]


def test_two_periods_said_earlier_first_are_compared_later_against_earlier():
    words = "What changed between Sep 19-Oct 9 and Oct 10-30?"
    clause = investigate(
        words, "what_changed", dates("2026-09-19", "2026-10-09"), dates("2026-10-10", "2026-10-30")
    )
    request, _ = read(words, said(clause))
    assert windows(request) == windows_of(LOOKED)


# ---- from food eaten to the tracker: the day and the energy carry over, not the method ----


def food_turn(start, end):
    window = {"start": start, "end": end}
    state = {"data": [{"metrics": ["food_logs"], "operation": "food", "windows": [window]}]}
    return Turn("What did my logged meals add up to?", "820 kcal", request_state=state)


@pytest.mark.parametrize(
    "start, end, length, operation",
    [("2026-10-17", "2026-10-17", 1, "value"), ("2026-10-10", "2026-10-16", 7, "sum")],
)
def test_switching_from_meals_to_the_tracker_keeps_the_days(start, end, length, operation):
    words = "And what did the tracker say I burned?"
    clause = data(
        words,
        ["calories"],
        "inherit",
        from_earlier("its_first_day", 0, "starts_there", length),
        earlier_result=0,
        source="tracker",
    )
    request, calls = read(words, said(clause), history=[food_turn(start, end)])
    (part,) = request.parts
    assert part.metrics == ["calories"] and part.operation == operation and calls == 1
    assert windows(request) == [(date.fromisoformat(start), date.fromisoformat(end))]


# ---- one measure is one finding, however many records test it ----


def test_an_overview_counts_measures_not_records():
    """32 metrics over the same periods were "39 measures" (the a196 audit): an earlier record
    and its version re-adjusted in this run are one measure."""
    from app.agent.findings import render_overview
    from app.agent.verifier import RUN_ADJUSTED
    from app.analysis.evidence import Window
    from app.analysis.tools import compare_windows
    from app.synthetic import generate

    frame = generate(date(2026, 7, 1), 60, seed=9).frame
    recent = Window(start=date(2026, 8, 1), end=date(2026, 8, 29))
    before = Window(start=date(2026, 7, 1), end=date(2026, 7, 29))
    records = []
    for metric in ("steps", "sleep_minutes", "hrv_ms"):
        record = compare_windows(frame, metric, recent, before)
        records.append(record.model_copy(update={"stats": {**record.stats, RUN_ADJUSTED: 0.7}}))
    again = records[0].model_copy(
        update={"id": "retested", "stats": {**records[0].stats, RUN_ADJUSTED: 0.8}}
    )
    text, claims = render_overview([*records, again], date(2026, 8, 30))
    assert "None of the 3 measures tested" in text
    (steady,) = claims
    assert "retested" in steady.evidence_ids and records[0].id not in steady.evidence_ids


# ---- a pattern on tagged days is watched, never offered as a tested routine ----


def test_a_stress_tag_split_is_a_pattern_to_watch_not_a_routine():
    """ "A wind-down routine on stressful days" stood on a stress tag: no routine was observed."""
    from app.agent.ask import option_sentence
    from app.analysis.coaching import habit_options
    from app.analysis.evidence import Evidence, Window
    from app.synthetic import generate

    frame = generate(date(2026, 7, 1), 90, seed=3).frame
    frame["tag_stress"] = [i % 3 == 0 for i in range(len(frame))]
    frame["tag_late_meal"] = [i % 4 == 0 for i in range(len(frame))]
    window = Window(start=date(2026, 7, 1), end=date(2026, 9, 28))
    levers = {
        lv["lever"]: lv for lv in habit_options(frame, "sleep_efficiency", window).stats["levers"]
    }
    assert (
        levers["wind_down"]["permits"] == "watch" and "routine" not in levers["wind_down"]["habit"]
    )
    assert levers["earlier_dinner"]["permits"] == "action"
    record = Evidence(
        tool="habit_options",
        metrics=["sleep_efficiency"],
        windows=[window],
        stats={"supported": True, "levers": [levers["wind_down"] | {"supported": True}]},
        n=90,
        sufficient=True,
    )
    text = option_sentence(record, "wind_down")
    assert "keeping an eye on" in text and "does not test a routine" in text
    assert "try it" not in text
