"""The independent audit of b3d64ca and the general repair plan: unknown habit exposures, one
hypothesis per test, every result of an answer addressable, an answer redone only when its data
is kept, no default answer for a reading nobody could place, a reported date error moved the
right way, and coaching assembled once with the points asked for. Each case is a reproduction
from the audit or the plan, with its contrasting control; made-up data only."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from test_broad_questions import END, ON, Router, planted, submit
from test_clauses import data, dates, earlier, read, redo, said, windows
from test_edits import from_earlier
from test_investigate_and_memory import reading_llm
from test_r922_reliability import LOOKED, OCT, OPENING, SEP, look

from app.agent.ask import ask, unresolved_follow_up
from app.agent.clauses import Said, reading_from
from app.agent.context import Turn
from app.agent.requested import execute
from app.agent.requests import Request, interpret, outline
from app.agent.verifier import RUN_ADJUSTED, run_adjusted
from app.analysis.coaching import habit_options
from app.analysis.evidence import Evidence, Window
from app.synthetic import Step, generate

TODAY = date(2026, 11, 19)

# ---- F: an unknown exposure is neither group ----

DAYS = pd.date_range("2026-09-01", periods=20)
WINDOW = Window(start=date(2026, 9, 1), end=date(2026, 9, 20))


def nights(known_early, known_late, unknown):
    """Five early and five late known bedtimes, then ten nights with no bedtime recorded."""
    frame = pd.DataFrame(index=DAYS)
    frame["bedtime_hour"] = [22.0] * 5 + [24.0] * 5 + [np.nan] * 10
    frame["sleep_efficiency"] = known_early + known_late + unknown
    return frame


def lever(frame, key="earlier_bedtime"):
    levers = habit_options(frame, "sleep_efficiency", WINDOW).stats["levers"]
    return next(lv for lv in levers if lv["lever"] == key)


def test_nights_with_no_bedtime_join_neither_group():
    """Equal known groups, and ten unknown nights with lower sleep: the unknown nights became
    "later nights" and an earlier bedtime was supported (the plan's missing-exposure probe)."""
    found = lever(nights([90.0] * 5, [90.0] * 5, [80.0] * 10))
    assert (found["n_with"], found["n_without"]) == (5, 5)
    assert not found["supported"]


def test_unknown_nights_do_not_change_the_known_result():
    with_unknown = lever(nights([92.0, 93, 91, 92, 94], [84.0, 83, 85, 82, 84], [70.0] * 10))
    known_only = nights([92.0, 93, 91, 92, 94], [84.0, 83, 85, 82, 84], [70.0] * 10).iloc[:10]
    alone = lever(known_only)
    for field in ("n_with", "n_without", "mean_with", "mean_without", "difference"):
        assert with_unknown[field] == alone[field]


def test_a_day_with_no_strain_is_not_an_ordinary_day():
    frame = pd.DataFrame(index=pd.date_range("2026-09-01", periods=40))
    frame["strain"] = [18.0 if i % 4 == 0 else 8.0 for i in range(40)]
    frame.loc[frame.index[10:20], "strain"] = np.nan
    frame["hrv_ms"] = 50.0
    window = Window(start=date(2026, 9, 1), end=date(2026, 10, 10))
    levers = habit_options(frame, "hrv_ms", window).stats["levers"]
    rest = next(lv for lv in levers if lv["lever"] == "rest_after_hard_day")
    # 39 mornings have a day before; the ten after a missing strain day are in neither group
    assert rest["n_with"] + rest["n_without"] == 39 - 10


# ---- E: one hypothesis, however many records carry it ----


def compared_record(p, window_start="2026-09-01", record_id=None, metric="steps"):
    window = Window(start=date.fromisoformat(window_start), end=date(2026, 9, 30))
    record = Evidence(
        tool="compare_windows",
        metrics=[metric],
        windows=[window, Window(start=date(2026, 8, 1), end=date(2026, 8, 30))],
        stats={"p_value": p, "difference": 1.0},
        n=60,
        sufficient=True,
    )
    return record.model_copy(update={"id": record_id}) if record_id else record


def adjusted(records):
    return {e.id: (e.stats[RUN_ADJUSTED], e.stats["tests_in_run"]) for e in run_adjusted(records)}


def test_an_identical_retest_under_a_new_id_is_one_test():
    """0.03 and 0.07 give 0.06; a copy of the first under another id gave three tests and 0.045,
    across the cutoff (the plan's hypothesis probe)."""
    first, second = compared_record(0.03, metric="steps"), compared_record(0.07, metric="hrv_ms")
    copy = first.model_copy(update={"id": "retested"})
    alone = adjusted([first, second])
    assert alone[first.id] == (0.06, 2)
    with_copy = adjusted([first, second, copy])
    assert with_copy[first.id] == with_copy["retested"] == (0.06, 2)
    assert adjusted([copy, second, first]) == with_copy  # order does not matter


def test_a_different_test_of_the_same_metric_is_another_hypothesis():
    first, second = compared_record(0.03, metric="steps"), compared_record(0.07, metric="hrv_ms")
    other_days = compared_record(0.03, window_start="2026-09-10", metric="steps")
    assert adjusted([first, second, other_days])[first.id][1] == 3


# ---- D: every result addressable; the same look only for the same referent ----


def investigation_with_side_read():
    words = f"{OPENING} And my mean steps over Oct 2-15?"
    side = data("And my mean steps over Oct 2-15?", ["steps"], "mean", OCT)
    from app.agent.llm import ScriptedLLM

    llm = ScriptedLLM(
        request_turns=[ScriptedLLM.call("read_request", **said(look(OCT, SEP), side))]
    )
    return interpret(llm, words, [], TODAY, read_back=False)


def test_a_side_read_stays_addressable_on_the_next_turn():
    _, state, _ = investigation_with_side_read()
    kinds = [(p["operation"], p["metrics"]) for p in state["data"]]
    assert ("describe", []) in kinds and ("mean", ["steps"]) in kinds
    assert state["last"] == "investigate"


def two_looks():
    def part(start, end):
        return {
            "metrics": [],
            "operation": "describe",
            "windows": [{"start": start, "end": end}, {"start": "2026-08-01", "end": "2026-08-14"}],
        }

    state = {"data": [part("2026-09-01", "2026-09-14"), part("2026-10-02", "2026-10-15")]}
    return Turn("Two looks.", "Done.", request_state=state)


def test_the_same_spans_of_different_results_are_not_one_look():
    """A whole-registry side comparison of result 0 beside an investigation of result 1: their
    raw spans compared equal, and the side comparison was dropped (the b3d64ca review)."""
    same = {"kind": "same_as_earlier"}
    side = data(OPENING, [], "compare", same, every_metric=True, earlier_result=0)
    main = look(same) | {"earlier_result": 1}
    reading = reading_from(Said.model_validate(said(side, main)), OPENING)
    assert len(reading.also) == 1 and reading.also[0].reference == 0


def test_a_whole_registry_comparison_over_other_days_runs_cold_as_an_overview():
    """Kept beside the look, it asked for an earlier result and clarified (the b3d64ca review)."""
    other = dates("2026-08-02", "2026-08-15")
    side = data(OPENING, [], "compare", OCT, other)
    request, _ = read(OPENING, said(look(OCT, SEP), side))
    assert request.kind == "investigate"
    (read_beside,) = request.reads
    assert read_beside.every_metric and read_beside.operation == "compare"
    frame = generate(date(2026, 7, 1), 140, seed=7).frame
    done = execute(Request(kind="data", parts=[read_beside]), frame, TODAY)
    assert "compared with" in done.summary and done.claims
    assert all(i in done.evidence for c in done.claims for i in c.evidence_ids)


def test_redo_after_guidance_redoes_the_guidance_not_the_older_data():
    """An older data comparison outlived a plank answer, and "that again" re-ran the data."""
    state = {**LOOKED.request_state, "guidance": ["plank"], "last": "guidance"}
    after_guidance = Turn("How do I do a plank?", "Hold a straight line.", request_state=state)
    words = "Say that again in fewer words."
    request, _ = read(words, said(redo(words)), history=[after_guidance])
    assert request.kind == "guidance" and request.topics == ["plank"]


def test_redo_after_data_still_redoes_the_data():
    words = "Say that again in fewer words."
    request, _ = read(words, said(redo(words)), history=[LOOKED])
    assert request.kind == "investigate" and len(request.parts[0].windows) == 2


# ---- B: a changed period is never a redo; an unplaced reading is asked about ----

SEVEN = earlier("2026-09-27", "2026-10-03", "time_in_bed", "mean")
SHORTEN = "Shorten it to a three-date average, still finishing on that same last date."


def test_a_shorter_period_said_in_a_redo_is_the_shorter_period():
    """time_in_bed-02/t2: as a redo it kept all seven days. A redo now says its days."""
    edit = from_earlier("its_last_day", 0, "ends_there", 3)
    request, calls = read(SHORTEN, said(redo(SHORTEN, edit)), history=[SEVEN])
    assert calls == 1 and request.kind == "data"
    assert windows(request) == [(date(2026, 10, 1), date(2026, 10, 3))]
    assert request.parts[0].metrics == ["time_in_bed"] and request.parts[0].operation == "mean"


def test_fewer_words_on_the_same_result_is_still_a_redo():
    words = "Say that same result in fewer words, keeping its dates."
    request, calls = read(words, said(redo(words)), history=[SEVEN])
    assert calls == 1 and windows(request) == [(date(2026, 9, 27), date(2026, 10, 3))]


def test_a_reading_nobody_could_place_is_asked_about_not_answered_with_defaults():
    """checkin_rating-02/t2: read as other, it reported recent steps."""
    llm = reading_llm(submit(), kind="other")
    history = [Turn("Check-in mean Oct 1-6?", "3.4", request_state=SEVEN.request_state)]
    reply = ask(
        llm,
        Router("lookup"),
        planted(),
        "Treat the last date as zero, then +1 to +4.",
        today=END,
        history=history,
    )
    assert reply.result.summary == unresolved_follow_up(history, END)
    assert "time in bed" in reply.result.summary.casefold() and not reply.result.evidence
    assert not [r for r in llm.requests if r.get("tools") and "describe" in str(r["tools"])]


def test_small_talk_read_as_other_still_gets_its_reply():
    llm = reading_llm(submit("Glad it helped!"), kind="other")
    reply = ask(llm, Router("chat"), planted(), "Thanks, that's great.", today=END, history=[SEVEN])
    assert reply.result.summary != unresolved_follow_up([SEVEN], END)


# ---- C: a reported date error is moved the right way ----

PAUSED = "That was two days too early. Fix just its date."


@pytest.mark.parametrize(
    "fields, offset",
    [
        ({"card_was": "too_early", "by_days": 2}, 2),  # paused_move-01/t2 moved it two earlier
        ({"card_was": "too_late", "by_days": 3}, -3),
        ({"days_from_card": 2}, 2),  # "move the draft forward two days"
        ({"days_from_card": -2}, -2),  # "move it back two days"
    ],
)
def test_a_card_moves_the_way_the_correction_means(fields, offset):
    clause = {"type": "correct", "said": PAUSED, **fields}
    reading = reading_from(Said.model_validate(said(clause)), PAUSED)
    assert reading.kind == "correction" and reading.card_day_offset == offset


# ---- A: a trace says which field of a reading was wrong ----


@pytest.mark.parametrize(
    "span, shown",
    [
        (from_earlier("its_first_day", 0, "ends_there", 3), "beside/previous/first+0/ends/3"),
        (from_earlier("its_first_day", -2, "ends_there", 3), "beside/previous/first-2/ends/3"),
        (from_earlier("its_last_day", 1, "starts_there", 4), "beside/previous/last+1/starts/4"),
    ],
)
def test_the_outline_keeps_every_field_of_a_date_edit(span, shown):
    words = "x"
    reading = reading_from(Said.model_validate(said(data(words, ["hrv_ms"], "mean", span))), words)
    assert outline(reading)["parts"][0]["periods"] == [shown]


def test_the_outline_keeps_a_corrections_sign_and_a_redos_count():
    move = reading_from(
        Said.model_validate(said({"type": "correct", "said": PAUSED, "days_from_card": -2})), PAUSED
    )
    assert outline(move)["card_day_offset"] == -2
    again = reading_from(
        Said.model_validate(said(redo("x", options=3))),
        "x",
    )
    assert outline(again)["redo_options"] == 3


# ---- G: coaching assembled once, with the points asked for ----


def test_options_asked_for_beside_an_investigations_coaching_survive_its_assembly(monkeypatch):
    """_fill_points added general points, then the coaching rebuild dropped them (the plan's
    renderer control)."""
    from app.agent import ask as asking
    from app.agent.knowledge import load_index, passage_evidence
    from app.agent.personal import top_up

    # Passages with an actionable sentence: the general points the answer can be topped up with.
    passages = [
        p
        for p in load_index().passages
        if p.kind != "exercise" and top_up("", 1, 0, [passage_evidence(p)])
    ][:6]
    monkeypatch.setattr(
        asking, "more_passages", lambda *a, **k: ([passage_evidence(p) for p in passages], 0.0)
    )
    frame = planted(Step("steps", ON, -5000.0))
    later = {"kind": "explicit", "start": (END - timedelta(13)).isoformat(), "end": END.isoformat()}
    llm = reading_llm(
        submit(),
        kind="investigate",
        focus="coaching",
        parts=[{"metrics": ["sleep_minutes"], "periods": [later]}],
        points=3,
    )
    reply = ask(llm, Router("lookup"), frame, "Give me three options for my sleep.", today=END)
    shown = reply.result.summary
    assert "points marked General are public guidance" in shown and "- General (" in shown
    kinds = [c.kind for c in reply.result.claims]
    assert "guidance" in kinds and len([k for k in kinds if k in ("suggestion", "guidance")]) <= 3
