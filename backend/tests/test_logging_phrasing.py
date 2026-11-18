"""Everyday logging words (the audit of 2026-11-18): "a 35-minute walk" asked for its duration,
and "Yes, log it" with a draft waiting asked what to log. Confirming still takes the tap."""

import pandas as pd
import pytest
from test_broad_questions import END

from app.actions.stated import durations, lacks_a_duration
from app.agent.ask import CONFIRM_ON_CARD, CONFIRMS, plain_reply


@pytest.mark.parametrize(
    "said, seconds",
    [
        ("Prepare a log for a 35-minute walk yesterday at 18:15.", 35 * 60),
        ("a 35‑minute walk", 35 * 60),  # a non-breaking hyphen, as phones type it
        ("a 1-hour run", 3600),
        ("a 45-min ride", 45 * 60),
        ("a 1.5-hour hike", 5400),
        ("a walk lasting 35 minutes", 35 * 60),
    ],
)
def test_a_hyphenated_duration_is_read(said, seconds):
    assert seconds in durations(said) and not lacks_a_duration([said])


def test_a_clock_time_alone_is_still_not_a_duration():
    assert lacks_a_duration(["a walk yesterday at 18:15"])


@pytest.mark.parametrize(
    "said",
    ["Yes, log it.", "Yes, log that walking workout", "ok, go ahead please", "sure, save it!"],
)
def test_a_compound_confirmation_points_to_the_card(said):
    assert CONFIRMS.match(said)
    assert plain_reply(said, pd.DataFrame(), END, after_draft=True) == CONFIRM_ON_CARD


@pytest.mark.parametrize(
    "said", ["Log the 30 min run I did", "Yes, but make it 40 minutes", "Log a protein shake"]
)
def test_a_new_entry_or_a_correction_is_not_a_confirmation(said):
    assert not CONFIRMS.match(said)


def test_without_a_draft_a_confirmation_is_not_answered_as_one():
    assert plain_reply("Yes, log it.", pd.DataFrame(), END, after_draft=False) != CONFIRM_ON_CARD
