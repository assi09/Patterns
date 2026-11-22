"""Codex's review and matched-reader comparison of e1c1eec: a record is stated for what its
statistic means, a block after or before an earlier period has its boundary worked out by code,
a repeat says its target apart from its statistic, and a repeat beside another clause is
answered too. Each case is a reproduction from the review with its contrasting controls;
made-up data only."""

from datetime import date, timedelta

import pandas as pd
import pytest
from test_clauses import SAME, data, dates, earlier, read, redo, said, windows

from app.agent.agent import AgentResult
from app.agent.ask import said_by_claims
from app.agent.context import Turn
from app.agent.findings import SAYERS, code_claim
from app.agent.verifier import Claim, verify
from app.analysis.evidence import Window
from app.analysis.habits import tag_effect
from app.analysis.tools import (
    change_point,
    compare_windows,
    correlate,
    describe,
    trend,
    weekday_split,
)

# ---- A. each record type is stated for what its statistic means ----

DAYS = pd.date_range("2026-09-01", periods=60)
WHOLE = Window(start=DAYS[0].date(), end=DAYS[-1].date())
LATER = Window(start=DAYS[30].date(), end=DAYS[-1].date())
FIRST = Window(start=DAYS[0].date(), end=DAYS[29].date())
JITTER = [(i * 37) % 11 * 40.0 for i in range(60)]  # small, fixed day-to-day variation


def frame(steps):
    f = pd.DataFrame(index=DAYS)
    f["steps"] = [s + j for s, j in zip(steps, JITTER, strict=True)]
    f["hrv_ms"] = [40.0 + (i * 13) % 7 for i in range(60)]
    f["tag_hard_training"] = [i % 2 for i in range(60)]
    return f


STEP_UP = frame([5000.0] * 30 + [10000.0] * 30)
FLAT = frame([7000.0] * 60)
WEEKENDS = frame([10000.0 if d.dayofweek >= 5 else 5000.0 for d in DAYS])
TAGGED = frame([5000.0 + 5000.0 * (i % 2) for i in range(60)])


def records(f):
    return [
        compare_windows(f, "steps", LATER, FIRST),
        change_point(f, "steps", WHOLE),
        weekday_split(f, "steps", WHOLE),
        tag_effect(f, "hard_training", "steps", WHOLE),
        trend(f, "steps", WHOLE),
        correlate(f, "steps", "hrv_ms", WHOLE),
        describe(f, "steps", WHOLE),
    ]


ALL = [r for f in (STEP_UP, FLAT, WEEKENDS, TAGGED) for r in records(f)]


@pytest.mark.parametrize("record", ALL, ids=lambda r: r.tool)
def test_every_stated_record_has_its_figures_and_passes_the_verifier_again(record):
    """change_point, weekday_split, tag_effect: each came out as "Steps went up: against ."."""
    claim = code_claim(record)
    assert claim is not None and record.tool in SAYERS
    assert " against ." not in claim.text and ": ." not in claim.text
    assert not verify([claim], {record.id: record}).rejected


def test_a_split_is_said_as_a_split_and_groups_as_groups():
    split = code_claim(change_point(STEP_UP, "steps", WHOLE))
    assert "around" in split.text and "after against" in split.text and split.kind == "change"
    week = code_claim(weekday_split(WEEKENDS, "steps", WHOLE))
    assert "weekend days than on weekdays" in week.text and "went up" not in week.text
    tag = code_claim(tag_effect(TAGGED, "hard_training", "steps", WHOLE))
    assert "days with hard training" in tag.text and tag.kind != "change"


def test_a_record_with_too_little_data_is_not_stated_and_its_omission_is_said():
    short = Window(start=DAYS[0].date(), end=DAYS[1].date())
    thin = compare_windows(
        STEP_UP, "steps", short, Window(start=DAYS[2].date(), end=DAYS[3].date())
    )
    assert not thin.sufficient and code_claim(thin) is None
    rose = compare_windows(STEP_UP, "steps", LATER, FIRST)
    result = AgentResult(run_id="r", stop_reason="submitted", summary="Model prose.")
    result.evidence |= {thin.id: thin, rose.id: rose}
    result.claims = [Claim(text="x", kind="change", evidence_ids=[thin.id, rose.id])]
    said_by_claims(result)
    assert result.summary.startswith("Steps went up") and "Model prose" not in result.summary
    assert any("too little data" in n for n in result.notes)


def test_the_grounding_controls_still_hold_for_every_type():
    for record in records(STEP_UP):
        result = AgentResult(run_id="r", stop_reason="submitted", summary="Prose.")
        result.evidence[record.id] = record
        result.claims = [
            Claim(text="You have been walking to work.", kind="value", evidence_ids=[record.id])
        ]
        said_by_claims(result)
        assert "walking to work" not in result.summary


# ---- B. a block after or before an earlier period: code works out its boundary ----

BLOCK = earlier("2026-09-14", "2026-09-19", "hrv_ms", "mean")  # six days


@pytest.mark.parametrize(
    "span, start, end",
    [
        # "the next four calendar dates after the block" (metric_hrv_ms-02/t2: Sep 17-20)
        ({"kind": "block_after", "length": 4}, "2026-09-20", "2026-09-23"),
        # "four dates beginning two dates after that last day"
        (
            {"kind": "block_after", "length": 4, "starts_days_after_its_last_day": 2},
            "2026-09-21",
            "2026-09-24",
        ),
        # "the five dates immediately before that range"
        ({"kind": "block_before", "length": 5}, "2026-09-09", "2026-09-13"),
        (
            {"kind": "block_before", "length": 3, "ends_days_before_its_first_day": 2},
            "2026-09-10",
            "2026-09-12",
        ),
        # "translate the complete block back by two dates; keep its size": no length to give
        ({"kind": "whole_shifted", "days": -2}, "2026-09-12", "2026-09-17"),
        ({"kind": "whole_shifted", "days": 3}, "2026-09-17", "2026-09-22"),
    ],
)
def test_a_relation_to_an_earlier_block_is_worked_out_by_code(span, start, end):
    words = "Same measure, those days."
    request, calls = read(words, said(redo(words, span)), history=[BLOCK])
    assert calls == 1
    assert windows(request) == [(date.fromisoformat(start), date.fromisoformat(end))]


@pytest.mark.parametrize(
    "span, start, end",
    [
        # protected: placed endpoints for anchored ranges inside or ending on the block
        (
            {
                "kind": "from_earlier",
                "new_last_day": {"counted_from": "its_first_day", "days_after": 0},
                "length": 3,
            },
            "2026-09-12",
            "2026-09-14",
        ),
        (
            {
                "kind": "from_earlier",
                "new_last_day": {"counted_from": "its_last_day", "days_after": 0},
                "length": 2,
            },
            "2026-09-18",
            "2026-09-19",
        ),
    ],
)
def test_placed_endpoints_still_work_for_anchored_ranges(span, start, end):
    words = "x"
    request, _ = read(words, said(redo(words, span)), history=[BLOCK])
    assert windows(request) == [(date.fromisoformat(start), date.fromisoformat(end))]


def test_a_block_before_a_period_in_the_same_clause():
    words = "Oct 9-31 compared with the four weeks before."
    clause = data(
        words,
        ["steps"],
        "compare",
        dates("2026-10-09", "2026-10-31"),
        {"kind": "block_before", "length": 28, "relative_to": "this_clause"},
    )
    request, _ = read(words, said(clause))
    assert windows(request) == [
        (date(2026, 10, 9), date(2026, 10, 31)),
        (date(2026, 9, 11), date(2026, 10, 8)),
    ]


# ---- C. a repeat's target, apart from its statistic; a repeat beside another clause ----

STEPS_MEAN = Turn(
    "And my mean steps Oct 16-18?",
    "7,400",
    request_state={
        "data": [
            {
                "metrics": ["steps"],
                "operation": "mean",
                "windows": [{"start": "2026-10-16", "end": "2026-10-18"}],
            }
        ],
        "last": "data",
    },
)
TWO = [dates("2026-10-11", "2026-10-24"), dates("2026-08-17", "2026-08-30")]
BOTH = [(date(2026, 10, 11), date(2026, 10, 24)), (date(2026, 8, 17), date(2026, 8, 30))]


def test_every_measure_asked_for_in_a_repeat_is_every_measure():
    """main_side_scope-02/t3: empty metrics inherited the last steps result."""
    words = "Return to the comparison across every metric, Oct 11-24 against Aug 17-30."
    clause = redo(words, *TWO, operation="compare", target="every_metric")
    request, _ = read(words, said(clause), history=[STEPS_MEAN])
    assert request.kind == "investigate" and request.focus == "overview"
    assert request.parts[0].metrics == [] and windows(request) == BOTH


def test_the_same_target_keeps_the_named_measure():
    words = "The same comparison for those two blocks."
    request, _ = read(words, said(redo(words, *TWO, operation="compare")), history=[STEPS_MEAN])
    assert request.kind == "data" and request.parts[0].metrics == ["steps"]


def test_a_broad_look_edited_to_a_comparison_keeps_its_breadth():
    """main_side_scope-01/t3: the indexed broad look lost its breadth as a comparison."""
    look = Turn(
        "Review every measure Oct 11-24 against Aug 17-30.",
        "Nothing changed clearly.",
        request_state={
            "data": [
                {
                    "metrics": [],
                    "operation": "describe",
                    "windows": [
                        {"start": "2026-10-11", "end": "2026-10-24"},
                        {"start": "2026-08-17", "end": "2026-08-30"},
                    ],
                },
                STEPS_MEAN.request_state["data"][0],
            ],
            "last": "data",
        },
    )
    words = "Give the all-measure comparison again, Oct 11-24 and Aug 17-30."
    clause = redo(words, *TWO, operation="compare", earlier_result=0)
    request, _ = read(words, said(clause), history=[look])
    assert request.kind == "investigate" and request.parts[0].metrics == []
    assert windows(request) == BOTH


@pytest.mark.parametrize(
    "fields",
    [
        {"target": "named", "metrics": []},  # named, with nothing named
        {"target": "every_metric", "metrics": ["steps"]},  # every measure, with one named
    ],
)
def test_a_target_that_contradicts_its_metrics_goes_back(fields):
    words = "Again for those days."
    wrong = redo(words, SAME) | fields
    right = redo(words, SAME)
    request, calls = read(words, said(wrong), said(right), history=[STEPS_MEAN])
    assert calls == 2 and request.parts[0].metrics == ["steps"]


def test_a_measure_restated_under_the_same_target_is_used():
    """The reader restates an unchanged metric often: no conflict, and named fields win."""
    words = "Repeat that statistic for those days."
    clause = redo(words, SAME, metrics=["steps"]) | {"target": "same"}
    request, calls = read(words, said(clause), history=[STEPS_MEAN])
    assert calls == 1 and request.parts[0].metrics == ["steps"]


def test_a_repeat_beside_a_status_clause_is_answered_too():
    """mixed_log-01/t3: "say both again" as a redo and a status lost the repeated figure."""
    state = {**STEPS_MEAN.request_state, "last": "status"}
    figure = ({"text": "x", "metric": "steps", "evidence_ids": ["e"]},)
    history = [Turn("Saved? And my steps?", "x", claims=figure, request_state=state)]
    words = "Say both again in a shorter answer."
    status = {"type": "status", "said": words, "about": "entry"}
    request, _ = read(words, said(redo(words), status), history=history, pending=True)
    assert request.kind == "status" and [p.metrics for p in request.reads] == [["steps"]]


def test_a_status_alone_beside_a_repeat_of_a_status_alone_reads_nothing():
    history = [Turn("Saved?", "Not yet.", request_state={"last": "status"})]
    words = "Again, both."
    status = {"type": "status", "said": words, "about": "entry"}
    request, _ = read(words, said(redo(words), status), history=history, pending=True)
    assert request.kind == "status" and not request.reads


def test_explicit_one_component_after_a_mixed_answer():
    state = {**STEPS_MEAN.request_state, "last": "status"}
    history = [Turn("Saved? And my steps?", "x", request_state=state)]
    words = "Just the steps figure again."
    request, _ = read(words, said(redo(words, earlier_result=0)), history=history)
    assert request.kind == "data" and request.parts[0].metrics == ["steps"]
    assert windows(request) == [(date(2026, 10, 16), date(2026, 10, 18))]


def test_days_after_a_block_never_end_where_it_ended():
    """The relation is the boundary: a successor block starts after the earlier last day."""
    words = "The next four days."
    request, _ = read(
        words, said(redo(words, {"kind": "block_after", "length": 4})), history=[BLOCK]
    )
    (window,) = request.parts[0].windows
    assert window.start == date(2026, 9, 19) + timedelta(days=1) and window.days == 4
