"""The v6 live audit's failures, as rules (docs/independent-audit-v6-handoff.md). Each beside a
control and words that need a different answer. Made-up dates and rows only; no model is called.
"""

from datetime import date

import pytest
from test_action_api import setup, sign_in  # noqa: F401 (the fixture)
from test_broad_questions import planted
from test_clauses import data, dates, earlier, read, said, windows
from test_v5_reliability import FOOD, frame_until, overview

from app.agent.agent import AgentResult
from app.agent.context import Turn
from app.agent.findings import cite_findings
from app.agent.requested import execute
from app.agent.requests import Ambiguous, Reading, movements_apart, resolve
from app.agent.world import head_noun, supporting, unasked_variants_out
from app.analysis.evidence import Evidence

TODAY = date(2026, 11, 19)


def codes(request):
    return [c for a in request.attempts for c in a.get("codes", [])]


# ---- the next two dates, however much of the words the reader copied ----

NEXT_TWO = "What does the same statistic come out to on the next two dates after the interval ends?"
# The reader's copy of a clause's words stopped short of its dates, so a check that the words name
# no period sent the right reading back (eight metrics in the v6 audit).
SHORT = "What does the same statistic come out to"
AUDITED = [
    "steps",
    "deep_sleep_minutes",
    "time_in_bed",
    "calories",
    "rem_sleep_minutes",
    "strain",
    "hr_zone_vigorous_minutes",
    "checkin_rating",
    "distance_km",
]


@pytest.mark.parametrize("metric", AUDITED)
@pytest.mark.parametrize("words", [NEXT_TWO, SHORT])
def test_the_next_two_dates_pass_first_time_whatever_words_the_clause_copied(metric, words):
    clause = data(words, [metric], "min", {"kind": "after_earlier", "length": 2}, earlier_result=0)
    history = [earlier("2026-08-03", "2026-08-07", metric, "min")]
    request, calls = read(NEXT_TWO, said(clause), history=history)
    assert windows(request) == [(date(2026, 8, 8), date(2026, 8, 9))] and calls == 1


@pytest.mark.parametrize(
    "wrong", [{"kind": "same_as_earlier"}, {"kind": "shift_earlier", "days": 2}]
)
def test_the_old_days_or_a_shift_for_the_next_two_dates_are_sent_back(wrong):
    clause = data(NEXT_TWO, ["steps"], "min", wrong, earlier_result=0)
    right = data(
        NEXT_TWO, ["steps"], "min", {"kind": "after_earlier", "length": 2}, earlier_result=0
    )
    history = [earlier("2026-08-03", "2026-08-07", "steps", "min")]
    request, _ = read(NEXT_TWO, said(clause), said(right), history=history)
    assert windows(request) == [(date(2026, 8, 8), date(2026, 8, 9))]
    assert {"adjacent", "length"} & set(codes(request))


def test_the_next_two_dates_cross_a_year():
    clause = data(
        NEXT_TWO, ["steps"], "min", {"kind": "after_earlier", "length": 2}, earlier_result=0
    )
    history = [earlier("2026-12-27", "2026-12-31", "steps", "min")]
    request, calls = read(NEXT_TWO, said(clause), history=history, today=date(2027, 1, 10))
    assert windows(request) == [(date(2027, 1, 1), date(2027, 1, 2))] and calls == 1


def test_with_two_earlier_results_the_one_named_is_counted_from():
    state = {
        "data": [
            {
                "metrics": ["steps"],
                "operation": "mean",
                "windows": [{"start": "2026-09-03", "end": "2026-09-05"}],
            },
            {
                "metrics": ["resting_hr"],
                "operation": "max",
                "windows": [{"start": "2026-09-16", "end": "2026-09-19"}],
            },
        ]
    }
    words = "For the second one, the next two dates after that interval?"
    clause = data(words, [], "inherit", {"kind": "after_earlier", "length": 2}, earlier_result=1)
    request, _ = read(words, said(clause), history=[Turn("q", "a", request_state=state)])
    assert windows(request) == [(date(2026, 9, 20), date(2026, 9, 21))]
    assert request.parts[0].metrics == ["resting_hr"]


# ---- a baseline next to a period named in the same message ----

SHIFTED = (
    "What actually shifted in my measurements between September 12 and 25 compared with before?"
)


def investigate(words, *periods, focus="what_changed", **extra):
    return {
        "type": "investigate",
        "said": words,
        "focus": focus,
        "metrics": [],
        "periods": list(periods),
        **extra,
    }


def test_compared_with_before_counts_from_the_named_period_on_a_first_message():
    """A cold start asked "Which earlier measurement?" and the conversation never recovered."""
    clause = investigate(
        SHIFTED, dates("2026-09-12", "2026-09-25"), {"kind": "before_earlier", "length": 28}
    )
    request, calls = read(SHIFTED, said(clause))
    assert windows(request) == [
        (date(2026, 9, 12), date(2026, 9, 25)),
        (date(2026, 8, 15), date(2026, 9, 11)),
    ]
    assert calls == 1


def test_a_block_before_an_earlier_result_still_uses_that_result():
    words = "And the 5 days before that block?"
    clause = data(
        words, ["steps"], "mean", {"kind": "before_earlier", "length": 5}, earlier_result=0
    )
    request, _ = read(words, said(clause), history=[earlier("2026-09-12", "2026-09-25")])
    assert windows(request) == [(date(2026, 9, 7), date(2026, 9, 11))]


# ---- months with "of", and "same week" ----


def test_a_month_of_a_year_is_that_month_and_year():
    words = "What about those two in February of 2027?"
    clause = investigate(
        words, {"kind": "month", "year": 2027, "month": 2}, focus="overview", earlier_result=0
    )
    request, calls = read(words, said(clause), history=[earlier("2026-11-03", "2026-11-08")])
    assert windows(request) == [(date(2027, 2, 1), date(2027, 2, 28))] and calls == 1


def test_the_same_week_is_the_earlier_days_not_the_calendar_week():
    """Asked about Sep 1-7, "same week" counted Aug 31-Sep 6 (the same count, by chance)."""
    words = "Same week, just the days right on 6000?"
    week = data(
        words,
        ["steps"],
        "count",
        {"kind": "calendar", "unit": "week", "offset": 0},
        comparison="==",
        threshold=6000,
        earlier_result=0,
    )
    same = data(
        words,
        ["steps"],
        "count",
        {"kind": "same_as_earlier"},
        comparison="==",
        threshold=6000,
        earlier_result=0,
    )
    history = [earlier("2026-09-01", "2026-09-07", "steps", "count")]
    request, _ = read(words, said(week), said(same), history=history, today=date(2026, 9, 6))
    assert windows(request) == [(date(2026, 9, 1), date(2026, 9, 7))]
    assert "same_days" in codes(request)


def test_this_week_still_means_this_week():
    words = "What about this week, same threshold?"
    week = data(
        words,
        ["steps"],
        "count",
        {"kind": "calendar", "unit": "week", "offset": 0},
        comparison="==",
        threshold=6000,
        earlier_result=0,
    )
    history = [earlier("2026-09-01", "2026-09-07", "steps", "count")]
    request, calls = read(words, said(week), history=history, today=date(2026, 9, 9))
    assert windows(request) == [(date(2026, 9, 7), date(2026, 9, 9))] and calls == 1


# ---- the source and the statistic the words name ----

MEAL_DAY = Turn(
    "For breakfast on September 22 give the energy in the entry I logged.",
    "1 entry.",
    request_state={
        "data": [
            {
                "metrics": ["food_logs"],
                "operation": "food",
                "windows": [{"start": "2026-09-22", "end": "2026-09-22"}],
                "meal_type": "BREAKFAST",
            }
        ]
    },
)
BURNED = "Switch from intake to expenditure for the same day: calories burned?"


def test_calories_burned_after_a_meal_reads_the_wearable():
    clause = data(BURNED, ["calories"], "value", {"kind": "same_as_earlier"}, earlier_result=0)
    request, calls = read(BURNED, said(clause), history=[MEAL_DAY])
    assert request.parts[0].metrics == ["calories"] and calls == 1


def test_calories_burned_read_as_the_meals_is_sent_back():
    meals = data(BURNED, ["food_logs"], "food", {"kind": "same_as_earlier"}, earlier_result=0)
    worn = data(BURNED, ["calories"], "value", {"kind": "same_as_earlier"}, earlier_result=0)
    request, _ = read(BURNED, said(meals), said(worn), history=[MEAL_DAY])
    assert request.parts[0].metrics == ["calories"] and "metric" in codes(request)


@pytest.mark.parametrize("metrics", [["calories", "protein"], ["energy_kcal", "protein_g"]])
def test_calories_beside_a_nutrient_in_meals_are_eaten(metrics):
    words = "Now total all confirmed meals on the same date for both calories and protein."
    clause = data(words, metrics, "sum", {"kind": "same_as_earlier"}, earlier_result=0)
    request, calls = read(words, said(clause), history=[MEAL_DAY])
    (food,) = request.parts
    assert (food.metrics, food.operation, food.meal_type) == (["food_logs"], "food", None)
    text = execute(request, frame_until(TODAY), TODAY, food_logs=FOOD[:0]).summary
    assert "0 entries" in text and calls == 1


def test_and_the_protein_continues_the_meal_read():
    words = "And the protein?"
    clause = data(words, [], "inherit", {"kind": "same_as_earlier"}, earlier_result=0)
    request, _ = read(words, said(clause), history=[MEAL_DAY])
    assert request.parts[0].metrics == ["food_logs"]


def test_a_stress_signs_score_is_the_stress_score():
    words = (
        "Between 2026-08-07 and 2026-08-11, inclusive, give the maximum of my daily physical "
        "stress-signs score."
    )
    strain = data(words, ["strain"], "max", dates("2026-08-07", "2026-08-11"))
    stress = data(words, ["stress_score"], "max", dates("2026-08-07", "2026-08-11"))
    request, _ = read(words, said(strain), said(stress))
    assert request.parts[0].metrics == ["stress_score"] and "metric" in codes(request)


def test_the_lowest_day_is_the_minimum_not_the_earlier_mean():
    words = "Back to the first result: give the lowest day's value in that interval."
    kept = data(words, [], "inherit", {"kind": "same_as_earlier"}, earlier_result=0)
    lowest = data(words, [], "min", {"kind": "same_as_earlier"}, earlier_result=0)
    history = [earlier("2026-09-03", "2026-09-05", "steps", "mean")]
    request, _ = read(words, said(kept), said(lowest), history=history)
    assert request.parts[0].operation == "min" and "statistic" in codes(request)


@pytest.mark.parametrize(
    "words",
    [
        "Same statistic for the next two dates after the interval ends?",
        "What was the peak heart-rate zone time over those days?",
    ],
)
def test_words_naming_no_new_statistic_keep_the_earlier_one(words):
    metric = "hr_zone_peak_minutes" if "peak" in words else "steps"
    clause = data(words, [metric], "inherit", {"kind": "same_as_earlier"}, earlier_result=0)
    history = [earlier("2026-09-03", "2026-09-05", metric, "mean")]
    request, _ = read(words, said(clause), history=history)
    assert "statistic" not in codes(request)


# ---- the person's own data, and what an investigation is asked to do ----


def test_my_own_data_asked_for_someone_is_not_another_person_s():
    words = "My teammate is asking about MY sleep score that night. What was it?"
    other = said(data(words, ["sleep_score"], "value", dates("2026-09-18")), subject="other")
    mine = said(data(words, ["sleep_score"], "value", dates("2026-09-18")))
    request, _ = read(words, other, mine)
    assert request.subject == "self" and request.parts


def test_someone_else_s_data_is_still_theirs():
    words = "Can you pull up my teammate's sleep score that night?"
    other = said(data(words, ["sleep_score"], "value", dates("2026-09-18")), subject="other")
    request, calls = read(words, other)
    assert request.subject == "other" and calls == 1


def test_what_lines_up_with_a_change_is_an_explanation():
    words = (
        "What else in the records lines up with the clearest change? Say when it is impossible "
        "to tell."
    )
    changed = investigate(words, {"kind": "same_as_earlier"}, earlier_result=0)
    why = investigate(words, {"kind": "same_as_earlier"}, focus="why", earlier_result=0)
    request, _ = read(
        words, said(changed), said(why), history=[earlier("2026-09-12", "2026-09-25")]
    )
    assert request.focus == "why"


def test_what_changed_stays_what_changed():
    words = "What changed over those days?"
    changed = investigate(words, {"kind": "same_as_earlier"}, earlier_result=0)
    request, calls = read(words, said(changed), history=[earlier("2026-09-12", "2026-09-25")])
    assert request.focus == "what_changed" and calls == 1


# ---- an overview's "the rest" is checked against everything it covers ----


@pytest.fixture(scope="module")
def two_changes():
    from test_broad_questions import ON

    from app.synthetic import Step

    return planted(Step("steps", ON, -5000.0), Step("sleep_minutes", ON, -90.0))


def test_the_rest_held_steady_is_left_out_when_another_metric_changed(two_changes):
    records = overview(two_changes)
    result = AgentResult(
        run_id="x",
        stop_reason="submitted",
        summary="Your time asleep fell; the rest looked steady, including bedtime.",
    )
    cite_findings(result, list(records.values()))
    assert "the rest" not in result.summary and result.summary.startswith("Your time asleep fell.")
    assert "Also clearly changed:" in result.summary and "Steps went down" in result.summary
    assert {c.metric for c in result.claims} >= {"sleep_minutes", "steps"}
    assert all(c.evidence_ids[0] in result.evidence for c in result.claims)


def test_the_rest_held_steady_stays_when_it_is_true(two_changes):
    from app.agent.present import label
    from app.agent.verifier import _significant

    records = overview(two_changes)
    moved = [label(m) for m, r in records.items() if "difference" in r.stats and _significant(r)]
    result = AgentResult(
        run_id="x",
        stop_reason="submitted",
        summary=f"Your {', '.join(moved)} changed clearly. The rest looked steady.",
    )
    cite_findings(result, list(records.values()))
    assert "The rest looked steady." in result.summary


# ---- a relationship with nothing to pair says what each metric has ----


def test_a_relationship_with_no_paired_days_gives_each_metric_s_coverage():
    frame = frame_until(TODAY, ("steps", "hrv_ms"))
    frame["hrv_ms"] = float("nan")
    words = "How did steps and HRV move together during Nov 3-8?"
    request, _ = read(
        words,
        said(data(words, ["steps", "hrv_ms"], "correlate", dates("2026-11-03", "2026-11-08"))),
    )
    result = execute(request, frame, TODAY)
    assert (
        "steps on 6 of 6 days" in result.summary and "no heart rate variability" in result.summary
    )
    (claim,) = result.claims
    assert len(claim.evidence_ids) == 2 and all(i in result.evidence for i in claim.evidence_ids)


def test_a_relationship_outside_the_data_says_so():
    frame = frame_until(TODAY, ("steps", "hrv_ms"))
    words = "Check both again for February 2027."
    request, _ = read(
        words,
        said(
            data(
                words, ["steps", "hrv_ms"], "correlate", {"kind": "month", "year": 2027, "month": 2}
            )
        ),
    )
    result = execute(request, frame, TODAY)
    assert result.summary.startswith("Your data has no days")


# ---- guidance: the movement asked for, and its own passages ----


class Found:
    def __init__(self, title, kind="exercise"):
        from types import SimpleNamespace

        self.passage = SimpleNamespace(title=title, kind=kind)


@pytest.mark.parametrize(
    "topic, titles, kept",
    [
        (
            "ordinary floor push-up",
            [
                "Pushups (Close and Wide Hand Positions)",
                "Single-Arm Push-Up",
                "Clock Push-Up",
                "Decline Push-Up",
            ],
            ["Pushups (Close and Wide Hand Positions)"],
        ),
        (
            "squat with no external weight",
            ["Bodyweight Squat", "Weighted Squat", "Kneeling Squat", "Hack Squat"],
            ["Bodyweight Squat"],
        ),
        (
            "floor glute bridge",
            ["Barbell Glute Bridge", "Butt Lift (Bridge)", "Single Leg Glute Bridge"],
            ["Butt Lift (Bridge)"],
        ),
        (
            "standard pushup on the ground",
            ["Pushups (Close and Wide Hand Positions)", "Push-Up Wide"],
            ["Pushups (Close and Wide Hand Positions)"],
        ),
        # what was asked for is kept, and with no plain passage nothing is dropped
        ("decline push-up", ["Decline Push-Up", "Clock Push-Up"], ["Decline Push-Up"]),
        ("barbell glute bridge", ["Barbell Glute Bridge"], ["Barbell Glute Bridge"]),
    ],
)
def test_passages_for_variants_nobody_asked_for_are_left_out(topic, titles, kept):
    found = unasked_variants_out([Found(t) for t in titles], topic)
    assert [f.passage.title for f in found] == kept


def test_the_plain_movement_is_searched_by_its_head_noun():
    assert [
        head_noun(t)
        for t in ("floor glute bridge", "ordinary floor push-up", "squat with no external weight")
    ] == ["bridge", "pushup", "squat"]


def passage(title, text):
    return Evidence(
        tool="knowledge",
        metrics=[],
        windows=[],
        n=1,
        sufficient=True,
        stats={"title": title, "text": text, "passage_id": title},
    )


def test_a_passage_off_the_topic_is_not_cited():
    caffeine = passage("Caffeine", "Avoid caffeine for several hours before sleep; stop earlier.")
    light = passage(
        "Using Light to Promote Sleep", "Bright light at night can keep you awake for hours."
    )
    reply = "Avoid caffeine for several hours before sleep, and stop it earlier in the day."
    assert supporting(reply, [caffeine, light], "caffeine timing") == [caffeine]


def test_one_routine_named_in_parts_is_followed_up_without_asking():
    state = {
        "guidance": ["desk worker", "interrupt long sitting"],
        "guidance_passages": ["movement-breaks", "medlineplus-a4f697961323"],
    }
    follow = Reading(
        kind="guidance",
        guidance_reference=True,
        guidance_question="Is a short walk an example in that guidance?",
    )
    request = resolve(follow, state, TODAY)
    assert len(request.topics) == 1 and "sitting" in request.topics[0]


def test_two_exercises_are_still_asked_about():
    assert movements_apart(["plank", "lunge"], [])
    follow = Reading(kind="guidance", guidance_reference=True, guidance_question="And breathing?")
    with pytest.raises(Ambiguous, match="plank or lunge"):
        resolve(follow, {"guidance": ["plank", "lunge"]}, TODAY)


# ---- no memory candidate from a pure question, checked in the store ----


@pytest.mark.parametrize("told", [False, True])
def test_a_pure_question_leaves_no_candidate_in_the_store(setup, monkeypatch, told):  # noqa: F811
    from dataclasses import replace

    from test_v5_reliability import Synchronous, reader_said

    from app.agent.llm import ScriptedLLM
    from app.api import chat

    client, _, agent = setup
    headers = sign_in(setup)
    monkeypatch.setattr(chat, "update_summary", lambda *args: None)
    monkeypatch.setattr(chat, "_pool", Synchronous(chat._pool))
    listening = replace(agent, background=True)
    client.app.dependency_overrides[chat.get_agent] = lambda: listening
    question = "During Jul 1-7 count the days on which my steps were 6000 or above."
    statement = "I'm aiming for 6000 steps a day."
    clauses = [
        data(
            question,
            ["steps"],
            "count",
            dates("2026-07-01", "2026-07-07"),
            comparison=">=",
            threshold=6000,
        )
    ]
    if told:
        clauses.insert(0, {"type": "other", "said": statement})
    agent.llm.request_turns = [reader_said(*clauses)]
    heard = {"kind": "goal", "text": "Aims for 6000 steps a day"}
    agent.llm.turns = [ScriptedLLM.call("record_memories", memories=[heard])] * 2
    text = f"{statement} {question}" if told else question
    first = client.post("/chat", headers=headers, json={"text": text}).json()[-1]
    kept = client.get("/memory", headers=headers).json()
    candidates = kept["waiting"] + kept["noticed"] + kept["kept"]
    assert bool(candidates) == told
    assert "at or above 6,000" in first["text"]  # the count itself was answered
    reopened = client.get("/chat", headers=headers).json()
    assert reopened[-1]["text"] == first["text"]
