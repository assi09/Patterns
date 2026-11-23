"""A length the message said survives the retry, whatever the retry put in its place.

"Make the opening date the closing date of a three-day block" was read with both days placed on
one date and length 3; code sends that back and keeps the length. Kept only when the retry left
it empty, a retry with length 1 or 2 was accepted, and the question asked named the new count
(the audit of 910da27, item 3 of pr-195-followup-issues.md).
"""

from datetime import date

import pytest
from test_bcdb0ff_review import LENGTH_WORDS, placed
from test_clauses import dates, read, redo, said

from app.agent.context import Turn
from app.agent.requests import kept_fields

BLOCK = Turn(
    "Median strain Sep 16-21?",
    "7.7",
    request_state={
        "data": [
            {
                "metrics": ["strain"],
                "operation": "median",
                "windows": [{"start": "2026-09-16", "end": "2026-09-21"}],
            }
        ],
        "last": "data",
    },
)
FIRST = said(redo(LENGTH_WORDS, placed("its_first_day", "its_first_day", 3)))
THREE_DAYS = [(date(2026, 9, 14), date(2026, 9, 16))]  # ending on the opening date, Sep 16


def windows(request):
    return [(w.start, w.end) for p in request.parts for w in p.windows]


@pytest.mark.parametrize("retried", [None, 1, 2, 4])
def test_the_retry_gets_the_three_days_whatever_length_it_gave(retried):
    retry = said(redo(LENGTH_WORDS, placed(None, "its_first_day", retried)))
    request, calls = read(LENGTH_WORDS, FIRST, retry, history=[BLOCK])
    assert calls == 2 and windows(request) == THREE_DAYS


@pytest.mark.parametrize("retried", [1, 2])
def test_a_retry_that_still_places_both_days_is_asked_about_with_the_said_count(retried):
    retry = said(redo(LENGTH_WORDS, placed("its_first_day", "its_first_day", retried)))
    request, _ = read(LENGTH_WORDS, FIRST, retry, history=[BLOCK])
    assert request.kind == "clarify"
    assert "Which 3 days" in request.clarification  # never the retry's count


def test_a_retry_that_reads_the_period_as_another_kind_keeps_the_count_too():
    retry = said(redo(LENGTH_WORDS, {"kind": "block_before", "length": 2}))
    kept = kept_fields(retry, FIRST, ("periods.length",))
    assert kept["clauses"][0]["periods"][0]["length"] == 3


def test_explicit_dates_in_the_retry_have_no_length_to_replace():
    retry = said(redo(LENGTH_WORDS, dates("2026-09-14", "2026-09-16")))
    kept = kept_fields(retry, FIRST, ("periods.length",))
    assert kept["clauses"][0]["periods"][0] == dates("2026-09-14", "2026-09-16")


def test_a_period_the_first_reading_gave_no_length_keeps_the_retrys():
    first = said(redo(LENGTH_WORDS, placed("its_first_day", "its_last_day", None)))
    retry = said(redo(LENGTH_WORDS, placed(None, "its_first_day", 3)))
    kept = kept_fields(retry, first, ("periods.length",))
    assert kept["clauses"][0]["periods"][0]["length"] == 3
