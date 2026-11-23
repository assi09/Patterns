"""Which dates have no record: the exact dates, computed by code and kept in the evidence.

In the Fitbit replay of 2026-11-22, "Which dates have no sleep record?" after "How many nights
have sleep records from Mar 9 through Mar 15?" was completed in 0 of 43 reserved conversations:
replies repeated the count, widened to all history, or named a recorded date as missing.
"""

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
from test_action_api import setup, sign_in  # noqa: F401 (the fixture)
from test_clauses import SAME, data, dates, reader, said, windows

from app.agent.context import Turn
from app.agent.llm import ScriptedLLM
from app.agent.requested import SHOWN_RUNS, execute
from app.agent.requests import Request, ResolvedPart, interpret
from app.analysis.evidence import Window
from app.analysis.tools import coverage
from app.api.store import analyze, get_data
from app.ingest.takeout import DailyData

WEEK = Window(start=date(2026, 3, 9), end=date(2026, 3, 15))  # Monday to Sunday


def week_of_sleep() -> pd.DataFrame:
    """Made-up values: Mar 10 empty (an interior gap), Mar 11 a recorded zero, Mar 13 absent
    from the data altogether."""
    days = pd.to_datetime(["2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-14"])
    days = days.append(pd.to_datetime(["2026-03-15"]))
    return pd.DataFrame(
        {"sleep_minutes": [400.0, np.nan, 0.0, 410.0, 395.0, 420.0], "steps": [1.0] * 6},
        index=days,
    )


# ---- the tool ----


def test_missing_dates_are_the_calendar_dates_without_a_value():
    record = coverage(week_of_sleep()[["sleep_minutes"]], WEEK, dates=True)
    assert record.stats["missing_dates"] == {"sleep_minutes": ["2026-03-10", "2026-03-13"]}
    assert record.stats["days_present"] == {"sleep_minutes": 5}  # the zero is a record
    assert record.windows == (WEEK,)


def test_a_week_with_every_date_recorded_has_none_missing():
    record = coverage(
        week_of_sleep()[["steps"]],
        Window(start=date(2026, 3, 14), end=date(2026, 3, 15)),
        dates=True,
    )
    assert record.stats["missing_dates"] == {"steps": []}


def test_dates_outside_the_data_are_missing_too():
    window = Window(start=date(2026, 3, 14), end=date(2026, 3, 17))
    record = coverage(week_of_sleep()[["sleep_minutes"]], window, dates=True)
    assert record.stats["missing_dates"]["sleep_minutes"] == ["2026-03-16", "2026-03-17"]


def test_the_list_is_only_made_when_asked_for():
    assert "missing_dates" not in coverage(week_of_sleep(), WEEK).stats


# ---- the answer, from that evidence ----


def answer(frame, window, metric="sleep_minutes"):
    request = Request(
        kind="data",
        parts=[ResolvedPart(metrics=[metric], operation="missing_dates", windows=[window])],
    )
    return execute(request, frame, date(2026, 3, 20))


def test_the_answer_names_exactly_the_missing_dates():
    result = answer(week_of_sleep(), WEEK)
    (claim,) = result.claims
    assert claim.kind == "data_quality"
    assert "Tue, Mar 10" in claim.text and "Fri, Mar 13" in claim.text
    assert "(2 of 7 days)" in claim.text
    for recorded in ("Mar 9", "Wed, Mar 11", "Mar 12", "Mar 14", "Mar 15,", "Sun, Mar 15"):
        assert recorded not in claim.text.split("record on", 1)[1]
    (record,) = result.evidence.values()
    assert record.stats["missing_dates"]["sleep_minutes"] == ["2026-03-10", "2026-03-13"]


def test_a_week_with_nothing_missing_says_so():
    result = answer(week_of_sleep(), Window(start=date(2026, 3, 14), end=date(2026, 3, 15)))
    assert "no date is missing" in result.claims[0].text


def test_consecutive_missing_dates_are_one_run():
    frame = week_of_sleep()
    frame.loc[pd.Timestamp("2026-03-12"), "sleep_minutes"] = np.nan  # Mar 12-13 now both missing
    (claim,) = answer(frame, WEEK).claims
    assert "Tue, Mar 10, and Thu, Mar 12 to Fri, Mar 13" in claim.text


def test_a_long_list_is_shortened_in_words_but_whole_in_the_evidence():
    days = pd.date_range("2026-01-01", "2026-02-28")
    values = [np.nan if i % 2 else 400.0 for i in range(len(days))]  # every other date missing
    frame = pd.DataFrame({"sleep_minutes": values}, index=days)
    window = Window(start=days[0].date(), end=days[-1].date())
    result = answer(frame, window)
    (record,) = result.evidence.values()
    missing = record.stats["missing_dates"]["sleep_minutes"]
    assert len(missing) == 29
    assert f"{29 - SHOWN_RUNS} days more, all listed in the evidence" in result.claims[0].text


# ---- the follow-up keeps the count's metric and days ----

TODAY = date(2026, 3, 20)


def test_which_dates_after_a_count_keeps_its_metric_and_days():
    words = "How many nights have sleep records from 2026-03-09 through 2026-03-15?"
    count = said(data(words, ["sleep_minutes"], "coverage", dates("2026-03-09", "2026-03-15")))
    _, state, _ = interpret(reader(count), words, [], TODAY, read_back=True)
    history = [Turn(words, "answer", request_state=state)]
    words = "Which dates have no sleep record?"
    follow = said(data(words, ["sleep_minutes"], "missing_dates", SAME))
    request, _, _ = interpret(reader(follow), words, history, TODAY, read_back=True)
    assert request.kind == "data"
    (part,) = request.parts
    assert part.operation == "missing_dates" and part.metrics == ["sleep_minutes"]
    assert windows(request) == [(WEEK.start, WEEK.end)]


# ---- through the chat, with the evidence reopened ----


def test_which_dates_through_the_chat_cites_the_exact_dates(setup):  # noqa: F811
    client, _, agent = setup
    headers = sign_in(setup)
    frame = analyze_frame()
    client.app.dependency_overrides[get_data] = lambda: analyze(
        DailyData(frame=frame), datetime.now(UTC)
    )
    first = "How many nights have sleep records from 2026-08-03 through 2026-08-09?"
    second = "Which dates have no sleep record?"
    turns = [
        (
            first,
            said(data(first, ["sleep_minutes"], "coverage", dates("2026-08-03", "2026-08-09"))),
        ),
        (second, said(data(second, ["sleep_minutes"], "missing_dates", SAME))),
    ]
    conversation = None
    for words, reading in turns:
        agent.llm.request_turns = [ScriptedLLM.call("read_request", **reading)]
        body = {"text": words} | ({"conversationId": conversation} if conversation else {})
        response = client.post("/chat", headers=headers, json=body)
        assert response.status_code == 200, response.text
        reply = response.json()[-1]
        conversation = reply["conversationId"]
    assert "Tue, Aug 4" in reply["text"] and "Fri, Aug 7" in reply["text"]
    assert "Wed, Aug 5" not in reply["text"]  # its recorded zero is a record
    reopened = client.get("/chat", headers=headers, params={"conversation": conversation}).json()
    assert reopened[-1]["text"] == reply["text"]
    (cited,) = reopened[-1]["evidenceIds"]
    record = client.get(f"/evidence/{cited}", headers=headers).json()
    assert record["tool"] == "coverage"
    assert record["windows"] == [{"start": "2026-08-03", "end": "2026-08-09"}]
    assert record["stats"]["missing_dates"] == {"sleep_minutes": ["2026-08-04", "2026-08-07"]}


def analyze_frame() -> pd.DataFrame:
    """The fixture's synthetic data with planted gaps: Aug 4 and Aug 7 empty, Aug 5 a zero."""
    from app.synthetic import generate

    frame = generate(date(2026, 7, 1), 60, seed=5).frame.copy()
    for day in ("2026-08-04", "2026-08-07"):
        frame.loc[pd.Timestamp(day), "sleep_minutes"] = np.nan
    frame.loc[pd.Timestamp("2026-08-05"), "sleep_minutes"] = 0.0
    return frame
