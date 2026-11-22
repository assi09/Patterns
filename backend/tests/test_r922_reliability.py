"""The independent audit of 9228fe6 and Codex's offline root-cause checks: a reference keeps its
days whatever the source, one look written twice is one look, a whole comparison is reused
whole, an answer asked again in another form keeps its request, coaching says which period it
tested, and a failed variant pick authorizes no other variant. Each case is an audit failure or
one of the controls Codex named; made-up data only."""

from datetime import date, timedelta

from test_broad_questions import END, ON, Router, planted, submit
from test_clauses import data, dates, read, redo, said, windows
from test_edits import from_earlier
from test_investigate_and_memory import reading_llm

from app.agent.ask import ask
from app.agent.context import Turn
from app.synthetic import Step

# ---- a reference keeps its days, before the source decides the operation ----

OCT17 = {"start": "2026-10-17", "end": "2026-10-17"}
ATE = Turn(
    "What did my logged meals add up to on October 17?",
    "820 kcal",
    request_state={"data": [{"metrics": ["food_logs"], "operation": "food", "windows": [OCT17]}]},
)


def burned(*periods, operation="inherit", reference=0):
    words = "Keep the date, but now the energy I burned according to the tracker."
    extra = {"earlier_result": reference} if reference is not None else {}
    clause = data(words, ["calories"], operation, *periods, source="tracker", **extra)
    return words, clause


def test_a_reference_with_no_new_days_keeps_the_food_answers_day():
    """energy-02/t2: the empty period list became all history, a 150-day total."""
    words, clause = burned()
    request, calls = read(words, said(clause), history=[ATE])
    (part,) = request.parts
    assert part.operation == "value" and not part.history and calls == 1
    assert windows(request) == [(date(2026, 10, 17), date(2026, 10, 17))]


def test_an_explicit_whole_history_stays_whole_history():
    words, clause = burned({"kind": "all_history"})
    request, _ = read(words, said(clause), history=[ATE])
    (part,) = request.parts
    assert part.history and not part.windows


def test_an_explicit_new_date_replaces_the_referenced_one():
    words, clause = burned(dates("2026-10-18"))
    request, _ = read(words, said(clause), history=[ATE])
    assert windows(request) == [(date(2026, 10, 18), date(2026, 10, 18))]
    assert request.parts[0].operation == "value"


def test_a_cold_tracker_total_does_not_invent_a_date():
    words = "What's the total energy I've burned?"
    clause = data(words, ["calories"], "sum", source="tracker")
    request, _ = read(words, said(clause))
    (part,) = request.parts
    assert part.history and part.operation == "sum" and not part.windows


def test_a_new_metric_question_with_no_days_still_reads_all_history():
    """Only a part that points back keeps the days: a new question keeps none."""
    words = "What's my average HRV?"
    clause = data(words, ["hrv_ms"], "mean")
    request, _ = read(words, said(clause), history=[ATE])
    assert request.parts[0].history


# ---- one look written twice is one look; a side read of named metrics stays ----

SEP = dates("2026-09-01", "2026-09-14")
OCT = dates("2026-10-02", "2026-10-15")
OPENING = "Across everything you track, how did Oct 2-15 compare with Sep 1-14?"


def look(*periods, metrics=()):
    return {
        "type": "investigate",
        "said": OPENING,
        "focus": "overview",
        "metrics": list(metrics),
        "periods": list(periods),
        "earlier_result": None,
        "every_metric": not metrics,
    }


def whole(*periods):
    return data(OPENING, [], "compare", *periods, every_metric=True)


BOTH = [(date(2026, 10, 2), date(2026, 10, 15)), (date(2026, 9, 1), date(2026, 9, 14))]


def test_an_identical_whole_registry_comparison_beside_the_look_is_the_same_look():
    """screenshift-01/t1 (diagnostic): the duplicate asked for an earlier result, cold."""
    request, calls = read(OPENING, said(whole(OCT, SEP), look(OCT, SEP)))
    assert request.kind == "investigate" and not request.reads and calls == 1
    assert windows(request) == BOTH


def test_an_unscoped_look_takes_the_scope_its_data_clause_names():
    """screenflat-01/t1 (diagnostic): dated data clause, investigation with no periods."""
    request, _ = read(OPENING, said(whole(OCT, SEP), look()))
    assert request.kind == "investigate" and not request.reads
    assert windows(request) == BOTH and request.parts[0].metrics == []


def test_a_named_side_read_survives_beside_the_look():
    words = f"{OPENING} And my mean steps over Oct 2-15?"
    side = data("And my mean steps over Oct 2-15?", ["steps"], "mean", OCT)
    request, _ = read(words, said(look(OCT, SEP), side))
    assert request.kind == "investigate" and windows(request) == BOTH
    assert [(p.metrics, p.windows[0].start) for p in request.reads] == [
        (["steps"], date(2026, 10, 2))
    ]


def test_a_breakfast_read_with_no_metric_is_no_look_across_everything():
    words = "Just breakfast on October 17."
    clause = data(words, [], "food", dates("2026-10-17"), meal_type="BREAKFAST")
    request, _ = read(words, said(clause))
    assert request.kind == "data" and request.parts[0].metrics == ["food_logs"]
    assert request.parts[0].meal_type == "BREAKFAST"


# ---- a whole comparison is reused whole; editing one side of two still asks which ----

LOOKED = Turn(
    OPENING,
    "Nothing changed clearly.",
    request_state={
        "data": [
            {
                "metrics": [],
                "operation": "describe",
                "windows": [
                    {"start": "2026-10-02", "end": "2026-10-15"},
                    {"start": "2026-09-01", "end": "2026-09-14"},
                ],
            }
        ],
        "focus": "overview",
    },
)


def why(*periods):
    words = "Why might that be?"
    return words, {
        "type": "investigate",
        "said": words,
        "focus": "why",
        "metrics": [],
        "periods": list(periods),
        "earlier_result": 0,
        "every_metric": False,
    }


def test_a_why_about_the_whole_comparison_keeps_both_periods():
    words, clause = why({"kind": "same_as_earlier"})
    request, calls = read(words, said(clause), history=[LOOKED])
    assert request.focus == "why" and windows(request) == BOTH and calls == 1


def test_an_edit_of_one_side_of_two_periods_still_asks_which():
    """The single-window guard stays: "the next three days" after two periods needs a side."""
    words, clause = why(from_earlier("its_last_day", 1, "starts_there", 3))
    request, _ = read(words, said(clause), history=[LOOKED])
    assert request.kind == "clarify"


# ---- the last answer again in another form keeps its request ----

THREE = "Could you give me up to three options here, saying which are personal versus general?"


def options(count=3):
    return redo(THREE, options=count)


def test_options_asked_for_after_a_look_are_coaching_on_that_look():
    """screenflat-02/t4: read as small talk, the look was lost and habits were tested on the
    default two months."""
    request, calls = read(THREE, said(options()), history=[LOOKED])
    assert request.kind == "investigate" and request.focus == "coaching" and calls == 1
    assert windows(request) == BOTH


def test_a_redo_of_a_data_answer_keeps_the_read():
    shorter = "Say that again, shorter."
    request, _ = read(shorter, said(redo(shorter)), history=[ATE])
    assert request.kind == "data" and windows(request) == [(date(2026, 10, 17), date(2026, 10, 17))]


def test_a_redo_with_nothing_earlier_asks():
    request, _ = read(THREE, said(options()))
    assert request.kind == "clarify"


def test_a_formatting_redo_is_not_something_told_about_them():
    request, _ = read(THREE, said(options()), history=[LOOKED])
    assert not request.told


# ---- coaching on a comparison tests the later period and says so ----


def test_coaching_on_two_periods_tests_the_later_one_and_says_so():
    frame = planted(Step("steps", ON, -5000.0))
    later = {"kind": "explicit", "start": (END - timedelta(13)).isoformat(), "end": END.isoformat()}
    earlier_days = {
        "kind": "explicit",
        "start": (END - timedelta(41)).isoformat(),
        "end": (END - timedelta(28)).isoformat(),
    }
    llm = reading_llm(
        submit(),
        kind="investigate",
        focus="coaching",
        parts=[{"metrics": ["sleep_minutes"], "periods": [earlier_days, later]}],
    )
    reply = ask(
        llm, Router("lookup"), frame, "What could I try, given those two periods?", today=END
    )
    habits = [e for e in reply.result.evidence.values() if e.tool == "habit_options"]
    assert habits and all(
        w.start >= END - timedelta(13) and w.end <= END for e in habits for w in e.windows
    )
    assert any("the later of the two periods compared" in n for n in reply.result.notes)
