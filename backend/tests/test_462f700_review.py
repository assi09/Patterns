"""Codex's offline review of 462f700: an explanation says what its cited records establish, in
code's words, never the text a claim was written with; a state saved before whole answers were
kept replays only what its last turn shows it gave; and a repeated answer keeps its form. Each
case is a reproduction from the review with its contrasting control; made-up data only."""

from datetime import timedelta

import pytest
from test_40baaee_review import turn
from test_broad_questions import END, ON, planted
from test_clauses import dates, read, redo, said

from app.agent.agent import AgentResult
from app.agent.ask import NO_TESTED_FINDING, said_by_claims
from app.agent.context import Turn
from app.agent.verifier import Claim
from app.analysis.evidence import Evidence, Window
from app.analysis.tools import compare_windows, correlate
from app.synthetic import Step

# ---- 1. an explanation is said from its records, not from its claims' words ----

FRAME = planted(Step("steps", ON, 5000.0))
# Morning check-ins (1-5), lower over the recent days: a computed result about how they rated it.
FRAME["checkin_rating"] = [4.0 + (i % 2) * 0.5 for i in range(len(FRAME))]
FRAME.loc[FRAME.index >= str(ON), "checkin_rating"] -= 2.0
RECENT = Window(start=ON, end=END)
BEFORE = Window(start=ON - timedelta(days=28), end=ON - timedelta(days=1))


def explained(*claims, records=()):
    result = AgentResult(run_id="r", stop_reason="submitted", summary="The model's prose.")
    for record in records:
        result.evidence[record.id] = record
    result.claims = list(claims)
    said_by_claims(result)
    return result


def steps_rose():
    return compare_windows(FRAME, "steps", RECENT, BEFORE)


@pytest.mark.parametrize(
    "added",
    [
        "You have been feeling more run down.",  # the review's control
        "You have been walking to work.",  # nothing about a commute is measured
        "That's probably why you've been so tired lately.",  # a paraphrase of an outcome
    ],
)
def test_an_assertion_written_inside_a_valid_claim_is_not_said(added):
    record = steps_rose()
    claim = Claim(text=f"Steps went up. {added}", kind="change", evidence_ids=[record.id])
    result = explained(claim, records=[record])
    assert added not in result.summary and result.summary.startswith("Steps went up:")
    assert [c.evidence_ids for c in result.claims] == [[record.id]]


def test_a_supported_change_is_said_with_its_figures():
    record = steps_rose()
    claim = Claim(text="Steps rose a lot.", kind="change", evidence_ids=[record.id])
    result = explained(claim, records=[record])
    assert result.summary.startswith("Steps went up:") and " against " in result.summary


def test_a_computed_check_in_result_is_said_as_its_statistic():
    record = compare_windows(FRAME, "checkin_rating", RECENT, BEFORE)
    claim = Claim(text="You felt worse.", kind="change", evidence_ids=[record.id])
    result = explained(claim, records=[record])
    assert "felt" not in result.summary and "check-in rating went down" in result.summary


def test_an_association_is_said_as_the_test_it_was():
    record = correlate(FRAME, "steps", "hrv_ms", Window(start=BEFORE.start, end=END))
    claim = Claim(text="Walking drives your HRV.", kind="association", evidence_ids=[record.id])
    result = explained(claim, records=[record])
    assert "drives" not in result.summary and "correlation" in result.summary


def test_each_cited_record_is_said_once_in_the_order_cited():
    rose = steps_rose()
    rating = compare_windows(FRAME, "checkin_rating", RECENT, BEFORE)
    claims = [
        Claim(text="a", kind="change", evidence_ids=[rating.id]),
        Claim(text="b", kind="change", evidence_ids=[rose.id, rating.id]),
    ]
    result = explained(*claims, records=[rose, rating])
    assert [c.evidence_ids for c in result.claims] == [[rating.id], [rose.id]]


def test_claims_citing_no_stated_finding_say_so_never_their_own_words():
    stats = {"passage_id": "p", "text": "Get daylight.", "source": "CDC", "title": "t"}
    passage = Evidence(tool="knowledge", metrics=(), windows=(), n=0, sufficient=True, stats=stats)
    claim = Claim(text="You have been walking to work.", kind="guidance", evidence_ids=[passage.id])
    result = explained(claim, records=[passage])
    assert result.summary == NO_TESTED_FINDING and not result.claims


def test_a_reply_code_wrote_is_left_as_it_is():
    record = steps_rose()
    result = AgentResult(run_id="r", stop_reason="limits", summary="Your data has no days then.")
    result.evidence[record.id] = record
    result.claims = [Claim(text="x", kind="change", evidence_ids=[record.id])]
    said_by_claims(result)
    assert result.summary == "Your data has no days then."


# ---- 2. a state saved before whole answers were kept replays only what it shows ----

# The captured long_context-01/t6 shape: a plank answer, an older resting heart rate kept.
RESTING_PART = {
    "metrics": ["resting_hr"],
    "operation": "mean",
    "windows": [{"start": "2026-10-12", "end": "2026-10-16"}],
}
PLANK = {"last": "guidance", "guidance": ["basic plank"], "data": [RESTING_PART]}


def test_repeating_plank_guidance_does_not_reopen_an_older_result():
    words = "Repeat that plank explanation briefly."
    request, _ = read(
        words, said(redo(words)), history=[Turn("How?", "Hold.", request_state=PLANK)]
    )
    assert request.kind == "guidance" and request.topics == ["basic plank"] and not request.reads


def test_the_older_result_is_still_there_when_asked_for():
    words = "And that resting heart rate again."
    history = [Turn("How?", "Hold.", request_state=PLANK)]
    request, _ = read(words, said(redo(words, earlier_result=0)), history=history)
    assert request.kind == "data" and request.parts[0].metrics == ["resting_hr"]


def test_a_new_state_with_a_side_read_still_replays_it():
    guide = {"type": "guidance", "said": "How do I plank?", "topics": ["plank"], "question": "x"}
    steps = {
        "type": "data",
        "said": "my steps on Oct 3",
        "metrics": ["steps"],
        "operation": "value",
        "periods": [dates("2026-10-03")],
    }
    _, first = turn("How do I plank, and my steps on Oct 3?", guide, steps)
    request, _ = turn("Again, briefly.", redo("Again, briefly."), history=[first])
    assert request.kind == "guidance" and [p.metrics for p in request.reads] == [["steps"]]


def test_a_new_guidance_only_state_replays_no_read():
    guide = {"type": "guidance", "said": "How do I plank?", "topics": ["plank"], "question": "x"}
    _, data_turn = turn(
        "Sleep?",
        {
            "type": "data",
            "said": "Sleep?",
            "metrics": ["sleep_minutes"],
            "operation": "mean",
            "periods": [dates("2026-10-01", "2026-10-07")],
        },
    )
    _, plank = turn("How do I plank?", guide, history=[data_turn])
    request, _ = turn("Again.", redo("Again."), history=[data_turn, plank])
    assert request.kind == "guidance" and not request.reads


# ---- 3. a repeated answer keeps its form ----

LOOK = {
    "type": "investigate",
    "said": "Give me three options for my sleep.",
    "focus": "coaching",
    "metrics": ["sleep_minutes"],
    "periods": [dates("2026-10-11", "2026-10-24")],
    "earlier_result": None,
    "points": 3,
}


def test_three_options_repeated_briefly_are_still_three_and_a_new_count_wins():
    first, one = turn(LOOK["said"], LOOK)
    assert first.points == 3
    again, two = turn("Repeat that briefly.", redo("Repeat that briefly."), history=[one])
    assert (again.kind, again.focus, again.points) == ("investigate", "coaching", 3)
    fewer, three = turn("Just two now.", redo("Just two now.", options=2), history=[one, two])
    assert fewer.points == 2
    still, _ = turn("And again.", redo("And again."), history=[one, two, three])
    assert still.points == 2


def test_a_new_question_starts_with_its_own_form():
    _, one = turn(LOOK["said"], LOOK)
    fresh = LOOK | {"said": "What could I try for my steps?", "metrics": ["steps"], "points": None}
    request, _ = turn(fresh["said"], fresh, history=[one])
    assert request.points is None
