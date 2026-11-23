"""A calendar week counted from an earlier result, and its weekdays or weekend, worked out by code.

The reader could count a calendar week only from today, and had no weekday or weekend part. So
"the full week before that week" after a weekend answer was counted in days from whichever result
it pointed at (from the weekend it is the wrong week), and "Monday to Friday" or "that weekend"
was placed by hand (the Fitbit replay of 2026-11-22). Now the week that holds the earlier
result's days is the anchor, so any result in that week gives the same days.
"""

from datetime import date

import pytest
from pydantic import ValidationError
from test_action_api import setup, sign_in  # noqa: F401 (the fixture)
from test_clauses import data, dates, reader, redo, said

from app.agent.clauses import CalendarPeriod
from app.agent.context import Turn
from app.agent.llm import ScriptedLLM
from app.agent.requests import interpret

TODAY = date(2020, 1, 27)
A = ("2020-01-20", "2020-01-26")  # Monday to Sunday
B = ("2020-01-13", "2020-01-19")  # the week before


def ask(history, words, reading, today=TODAY):
    request, state, _ = interpret(reader(reading), words, list(history), today, read_back=True)
    return request, [*history, Turn(words, "answer", request_state=state)]


def week(offset=0, days="all", relative_to="earlier_result"):
    return {
        "kind": "calendar",
        "unit": "week",
        "offset": offset,
        "relative_to": relative_to,
        "days": days,
    }


def windows(request):
    return [(w.start.isoformat(), w.end.isoformat()) for p in request.parts for w in p.windows]


def two_weeks():
    """A, then the week before it: B is the last answer (index 0), A is index 1."""
    words = "Total steps 2020-01-20 to 2020-01-26?"
    _, history = ask([], words, said(data(words, ["steps"], "sum", dates(*A))))
    block = {"kind": "block_before", "length": 7}
    return ask(
        history, "And the week before?", said(redo("And the week before?", block, earlier_result=0))
    )[1]


@pytest.mark.parametrize(
    "index, days, expected",
    [
        (0, "weekdays", ("2020-01-13", "2020-01-17")),
        (1, "weekdays", ("2020-01-20", "2020-01-24")),
        (0, "weekend", ("2020-01-18", "2020-01-19")),
        (1, "weekend", ("2020-01-25", "2020-01-26")),
        (0, "all", B),
    ],
)
def test_a_part_of_the_week_holding_an_earlier_result(index, days, expected):
    words = "For that earlier week, just Monday to Friday?"
    request, _ = ask(two_weeks(), words, said(redo(words, week(0, days), earlier_result=index)))
    assert request.kind == "data" and windows(request) == [expected]
    assert request.parts[0].operation == "sum" and request.parts[0].metrics == ["steps"]


@pytest.mark.parametrize("index", [0, 1])
def test_the_week_before_that_week_is_the_same_from_the_weekend_or_the_whole_week(index):
    """Sleep in the replay: a week, then "only that weekend?", then the full week before."""
    words = "Average time asleep 2020-01-20 to 2020-01-26?"
    _, history = ask([], words, said(data(words, ["sleep_minutes"], "mean", dates(*A))))
    weekend = "Only that weekend?"
    _, history = ask(history, weekend, said(redo(weekend, week(0, "weekend"), earlier_result=0)))
    words = "Now average the full week before that week."
    request, _ = ask(history, words, said(redo(words, week(-1), earlier_result=index)))
    assert windows(request) == [B]  # index 0 is the weekend, index 1 the whole week


def test_weekdays_of_a_week_counted_from_today():
    words = "Steps on weekdays last week?"
    reading = said(data(words, ["steps"], "sum", week(-1, "weekdays", "today")))
    request, _ = ask([], words, reading)
    assert windows(request) == [("2020-01-20", "2020-01-24")]


def test_a_weekend_that_has_not_happened_yet_is_asked_about():
    words = "Steps this weekend?"
    reading = said(data(words, ["steps"], "sum", week(0, "weekend", "today")))
    request, _ = ask([], words, reading, today=date(2020, 1, 29))  # a Wednesday
    assert request.kind == "clarify"


def test_that_week_of_a_period_across_two_weeks_is_asked_about():
    words = "Steps 2020-01-16 to 2020-01-21?"  # Thursday to Tuesday
    _, history = ask(
        [], words, said(data(words, ["steps"], "sum", dates("2020-01-16", "2020-01-21")))
    )
    words = "Weekdays of that week?"
    request, _ = ask(history, words, said(redo(words, week(0, "weekdays"), earlier_result=0)))
    assert request.kind == "clarify"


def test_weekdays_belong_to_a_week_not_a_month():
    words = "Steps on weekdays last month?"
    month = {
        "kind": "calendar",
        "unit": "month",
        "offset": -1,
        "relative_to": "today",
        "days": "weekdays",
    }
    request, _ = ask([], words, said(data(words, ["steps"], "sum", month)))
    assert request.kind == "clarify"


def test_a_week_after_today_is_not_a_reading():
    with pytest.raises(ValidationError):
        CalendarPeriod.model_validate(week(1, relative_to="today"))
    assert CalendarPeriod.model_validate(week(1)).offset == 1  # after an earlier result: fine


def test_a_week_counted_from_today_still_works_as_before():
    words = "Steps last week?"
    request, _ = ask(
        [],
        words,
        said(data(words, ["steps"], "sum", {"kind": "calendar", "unit": "week", "offset": -1})),
    )
    assert windows(request) == [A]


# ---- through the chat, with the evidence reopened ----


def test_weekdays_of_that_earlier_week_through_the_chat(setup):  # noqa: F811
    client, _, agent = setup
    headers = sign_in(setup)
    first = "Total steps from 2026-08-10 to 2026-08-16?"
    turns = [
        (first, said(data(first, ["steps"], "sum", dates("2026-08-10", "2026-08-16")))),
        (
            "And the week before?",
            said(
                redo(
                    "And the week before?", {"kind": "block_before", "length": 7}, earlier_result=0
                )
            ),
        ),
        (
            "For that earlier week, just Monday to Friday?",
            said(
                redo(
                    "For that earlier week, just Monday to Friday?",
                    week(0, "weekdays"),
                    earlier_result=0,
                )
            ),
        ),
    ]
    conversation = None
    for words, reading in turns:
        agent.llm.request_turns = [ScriptedLLM.call("read_request", **reading)]
        body = {"text": words} | ({"conversationId": conversation} if conversation else {})
        response = client.post("/chat", headers=headers, json=body)
        assert response.status_code == 200, response.text
        reply = response.json()[-1]
        conversation = reply["conversationId"]
    reopened = client.get("/chat", headers=headers, params={"conversation": conversation}).json()
    assert reopened[-1]["evidenceIds"] == reply["evidenceIds"] and reply["evidenceIds"]
    cited = [client.get(f"/evidence/{e}", headers=headers).json() for e in reply["evidenceIds"]]
    assert {(w["start"], w["end"]) for r in cited for w in r["windows"]} == {
        ("2026-08-03", "2026-08-07")
    }
