"""The independent audit of b730fda: a follow-up's new days with both edges said, a food
follow-up keeping its day, evidence reopened as it was used, coaching bound to a tested habit,
nothing to explain when nothing changed, a look across every measure, and a paused workout.
Each case is the audit's failing question or its control; made-up data only."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest
from pydantic import ValidationError
from test_chat_store import person, session  # noqa: F401  (the store fixture)
from test_clauses import data, dates, earlier, read, said, windows

from app.actions.schemas import WorkoutLog
from app.actions.stated import mismatch
from app.agent.agent import AgentResult
from app.agent.ask import NO_CHANGE_TO_EXPLAIN, nothing_to_explain, one_coaching_conclusion
from app.agent.clauses import Said
from app.agent.context import Turn
from app.agent.llm import ScriptedLLM
from app.agent.requested import execute
from app.agent.requests import Request, ResolvedPart, interpret, said_schema, strict_schema
from app.agent.verifier import RUN_ADJUSTED, Claim, check_claim
from app.analysis.evidence import Evidence, Window
from app.analysis.tools import compare_windows, correlate
from app.api import chat
from app.db.chat import add_answer, load_evidence
from app.synthetic import Coupling, Step, generate

TODAY = date(2026, 11, 19)


def beside(counted_from, offset, new_period, length):
    return {
        "kind": "from_earlier",
        "landmark": counted_from,
        "offset": offset,
        "boundary": new_period,
        "length": length,
    }


# ---- a follow-up's new days: which earlier edge, which new edge, how far, how long ----

SEP = earlier("2026-09-02", "2026-09-05", "steps", "median")


@pytest.mark.parametrize(
    "words, span, start, end",
    [
        # the audit's failing wording, and its control that passed 12 of 12
        (
            "Leave the measure and calculation alone. Start at the next date and cover three days.",
            beside("its_last_day", 1, "starts_there", 3),
            "2026-09-06",
            "2026-09-08",
        ),
        (
            "Use the three calendar days immediately following that window and give me its "
            "median again.",
            beside("its_last_day", 1, "starts_there", 3),
            "2026-09-06",
            "2026-09-08",
        ),
        # a trailing window against the same day is a different block
        (
            "Now the three days ending the day after that window.",
            beside("its_last_day", 1, "ends_there", 3),
            "2026-09-04",
            "2026-09-06",
        ),
        (
            "And for the 3 days leading into it?",
            beside("its_first_day", -1, "ends_there", 3),
            "2026-08-30",
            "2026-09-01",
        ),
        (
            "That last date and the two dates before it.",
            beside("its_last_day", 0, "ends_there", 3),
            "2026-09-03",
            "2026-09-05",
        ),
        (
            "A week starting two days after it ended.",
            beside("its_last_day", 2, "starts_there", 7),
            "2026-09-07",
            "2026-09-13",
        ),
        (
            "The day before that window.",
            beside("its_first_day", -1, "ends_there", 1),
            "2026-09-01",
            "2026-09-01",
        ),
    ],
)
def test_a_follow_up_block_has_the_edges_its_words_say(words, span, start, end):
    clause = data(words, ["steps"], "median", span, earlier_result=0)
    request, calls = read(words, said(clause), history=[SEP])
    assert windows(request) == [(date.fromisoformat(start), date.fromisoformat(end))]
    assert calls == 1


def test_days_counted_from_an_earlier_end_are_no_longer_a_period_kind():
    """The rolling form let a forward start be read as a rolling end; only today anchors it."""
    old = {"kind": "days_ending", "length": 3, "ending": "earlier_end", "offset": 1}
    with pytest.raises(ValidationError):
        Said.model_validate(said(data("Start at the next date.", ["steps"], "median", old)))
    schema = str(strict_schema(said_schema()))
    assert "earlier_end" not in schema and "after_earlier" not in schema
    assert "starts_there" in schema and "its_first_day" in schema


# ---- a food follow-up keeps its day, whatever the source and the meal ----

OCT19 = {"start": "2026-10-19", "end": "2026-10-19"}
FOOD_THEN_TRACKER = [
    Turn(
        "What did my saved meals add up to on October 19?",
        "820 kcal",
        request_state={
            "data": [{"metrics": ["food_logs"], "operation": "food", "windows": [OCT19]}]
        },
    ),
    Turn(
        "Same date, energy out from the wearable?",
        "2,378 kcal",
        request_state={
            "data": [{"metrics": ["calories"], "operation": "value", "windows": [OCT19]}]
        },
    ),
]
BREAKFAST = "Switch back to meals, breakfast only. How many calories?"
# Two confirmed breakfasts on different days: a lost day changes the number, not only the dates.
MEALS = [
    {"consumedAt": "2026-10-19T08:05:00+00:00", "mealType": "BREAKFAST", "energyKcal": 280},
    {"consumedAt": "2026-10-19T12:40:00+00:00", "mealType": "LUNCH", "energyKcal": 540},
    {"consumedAt": "2026-10-12T07:50:00+00:00", "mealType": "BREAKFAST", "energyKcal": 350},
]


def test_a_breakfast_follow_up_reads_the_food_log_on_the_day_under_discussion():
    clause = data(
        BREAKFAST,
        ["calories"],
        "food",
        {
            "kind": "from_earlier",
            "landmark": "its_first_day",
            "offset": 0,
            "boundary": "starts_there",
            "length": 1,
        },
        earlier_result=0,
        meal_type="BREAKFAST",
    )
    request, calls = read(BREAKFAST, said(clause), history=FOOD_THEN_TRACKER)
    assert calls == 1 and request.parts[0].metrics == ["food_logs"]
    assert windows(request) == [(date(2026, 10, 19), date(2026, 10, 19))]
    frame = pd.DataFrame({"calories": [2300.0]}, index=pd.date_range("2026-10-19", periods=1))
    result = execute(request, frame, date(2026, 10, 31), food_logs=MEALS, zone=UTC)
    stats = next(iter(result.evidence.values())).stats
    assert stats["meals_logged"] == 1 and stats["totals"]["energyKcal"] == 280


def test_a_reading_sent_back_is_told_to_keep_what_the_error_is_not_about():
    """The retry that re-read everything dropped the breakfast's day (the b730 audit)."""
    words = "Steps and what I ate on October 19?"
    mixed = data(words, ["steps"], "food", dates("2026-10-19"))
    split = [
        data(words, ["steps"], "value", dates("2026-10-19")),
        data(words, [], "food", dates("2026-10-19"), source="food_log"),
    ]
    llm = ScriptedLLM(
        request_turns=[
            ScriptedLLM.call("read_request", **said(mixed)),
            ScriptedLLM.call("read_request", **said(*split)),
        ]
    )
    request, _, _ = interpret(llm, words, [], TODAY, read_back=False)
    retry = llm.requests[-1]["messages"][-1]["content"]
    assert "keep every other field" in retry and "periods" in retry
    assert [p.metrics for p in request.parts] == [["steps"], ["food_logs"]]


# ---- a look across every measure is an overview, however it was typed ----

FULL_SET = (
    "Contrast my full set of measurements for October 11 through 31 with September 20 through "
    "October 10. What stood out?"
)
SPANS = (dates("2026-10-11", "2026-10-31"), dates("2026-09-20", "2026-10-10"))


@pytest.mark.parametrize(
    "clauses",
    [
        [data(FULL_SET, [], "compare", *SPANS, every_metric=True)],
        # read as three clauses: each window's averages, then the comparison
        [
            data(FULL_SET, [], "mean", SPANS[0], every_metric=True),
            data(FULL_SET, [], "mean", SPANS[1], every_metric=True),
            data(FULL_SET, [], "compare", *SPANS, every_metric=True),
        ],
    ],
)
def test_data_about_every_measure_is_a_look_across_them(clauses):
    request, calls = read(FULL_SET, said(*clauses))
    assert request.kind == "investigate" and request.focus == "overview" and calls == 1
    assert [p.metrics for p in request.parts] == [[]] and not request.reads
    assert windows(request) == [
        (date(2026, 10, 11), date(2026, 10, 31)),
        (date(2026, 9, 20), date(2026, 10, 10)),
    ]


def test_named_measures_compared_stay_a_comparison_of_those():
    words = "Compare my steps and HRV for October 11-31 with September 20-October 10."
    request, _ = read(words, said(data(words, ["steps", "hrv_ms"], "compare", *SPANS)))
    assert request.kind == "data" and request.parts[0].metrics == ["steps", "hrv_ms"]


# ---- evidence reopens as the answer used it ----


def answer_citing(db, user, record, run):
    return add_answer(
        db,
        user,
        f"answer {run}",
        claims=[{"text": "Steps went up.", "kind": "change", "evidence_ids": [record.id]}],
        evidence=[record],
        answered_by=None,
        routed=None,
        consulted=[],
        refused=False,
        run_id=run,
    )


def test_one_test_adjusted_in_two_families_reopens_with_each_answers_figures(session):  # noqa: F811
    """Two answers cite the same comparison, corrected for runs of 3 and of 30 tests: each
    reopens with its own adjusted p-value; neither overwrites the other (the b730 audit)."""
    frame = generate(date(2026, 7, 1), 60, seed=4).frame
    test = compare_windows(
        frame,
        "steps",
        Window(start=date(2026, 8, 1), end=date(2026, 8, 29)),
        Window(start=date(2026, 7, 1), end=date(2026, 7, 29)),
    )

    def adjusted(q, n):
        return test.model_copy(update={"stats": {**test.stats, RUN_ADJUSTED: q, "tests_in_run": n}})

    user = person(session)
    first = answer_citing(session, user, adjusted(0.012, 3), "run1")
    second = answer_citing(session, user, adjusted(0.044, 30), "run2")
    again = answer_citing(session, user, adjusted(0.012, 3), "run3")
    session.flush()
    assert first.evidence_ids == [test.id] and second.evidence_ids != first.evidence_ids
    assert second.claims[0]["evidence_ids"] == second.evidence_ids
    assert again.evidence_ids == first.evidence_ids  # the same contents are one record
    shown = load_evidence(session, user, [*first.evidence_ids, *second.evidence_ids])
    (one,), (other,) = first.evidence_ids, second.evidence_ids
    assert shown[one].stats[RUN_ADJUSTED] == 0.012 and shown[one].stats["tests_in_run"] == 3
    assert shown[other].stats[RUN_ADJUSTED] == 0.044 and shown[other].stats["tests_in_run"] == 30
    assert shown[other].id == other and shown[other].stats["difference"] == test.stats["difference"]


# ---- a suggestion stands on a tested habit, not on a measure that moved ----


@pytest.fixture(scope="module")
def moved_and_linked():
    start = date(2026, 7, 1)
    effects = (
        Step("bedtime_hour", start + timedelta(30), 1.0),
        Coupling("bedtime_hour", "sleep_minutes", lag_days=0, strength=-0.9),
        Step("sleep_minutes", start + timedelta(30), -45),
    )
    frame = generate(start, 60, effects, seed=3).frame
    recent = Window(start=start + timedelta(30), end=start + timedelta(59))
    before = Window(start=start, end=start + timedelta(29))
    found = {
        "moved": compare_windows(frame, "sleep_minutes", recent, before),
        "linked": correlate(
            frame, "bedtime_hour", "sleep_minutes", Window(start=start, end=recent.end)
        ),
    }
    assert all(e.stats["p_value"] < 0.01 for e in found.values())
    return found


GROUNDING = "a measure that changed, a meal logged or something they told you tests no habit"


def suggestion_reasons(record: Evidence) -> list[str]:
    option = Claim(
        text="You could try a steadier bedtime.",
        kind="suggestion",
        evidence_ids=[record.id],
        metric="sleep_minutes",
    )
    return check_claim(option, {record.id: record})


def test_a_change_in_a_measure_does_not_ground_a_habit_to_try(moved_and_linked):
    assert any(GROUNDING in r for r in suggestion_reasons(moved_and_linked["moved"]))


def test_a_tested_association_grounds_a_habit_to_try(moved_and_linked):
    assert not any(GROUNDING in r for r in suggestion_reasons(moved_and_linked["linked"]))


# ---- a suggestion offers the habit its evidence tested, and code says it ----
# The review of 4fdac68: bedtime-and-sleep evidence accepted "spreading walks across more days".

WALKS = "You could try spreading walks across more days of the week."
BEDTIME = "You could try a steadier bedtime."


def offered(text: str, record: Evidence, option: str | None) -> Claim:
    return Claim(
        text=text,
        kind="suggestion",
        evidence_ids=[record.id],
        metric="sleep_minutes",
        option=option,
    )


BINDING = "a suggestion offers one option its cited evidence tested"


@pytest.mark.parametrize("option", [None, "steps", "active_days"])
def test_bedtime_evidence_backs_no_walking_option(moved_and_linked, option):
    linked = moved_and_linked["linked"]
    reasons = check_claim(offered(WALKS, linked, option), {linked.id: linked})
    assert any(BINDING in r and "bedtime_hour" in r for r in reasons)


def test_bedtime_evidence_backs_the_bedtime_option(moved_and_linked):
    linked = moved_and_linked["linked"]
    assert not check_claim(offered(BEDTIME, linked, "bedtime_hour"), {linked.id: linked})


def coaching_turn(claims, evidence):
    return AgentResult(
        run_id="x",
        stop_reason="submitted",
        summary="One good option is spreading your walks across the week.",
        claims=claims,
        evidence={e.id: e for e in evidence},
    )


def test_what_the_person_reads_is_the_option_the_evidence_tested(moved_and_linked):
    """Even with the right key beside the wrong words, the reply is said from the record: the
    walking prose goes, and the bedtime option it was bound to is what is shown and cited."""
    linked = moved_and_linked["linked"]
    result = coaching_turn([offered(WALKS, linked, "bedtime_hour")], [linked])
    one_coaching_conclusion(result, [])
    shown = chat.answer_text(result.summary, [c.text for c in result.claims], result.notes)
    assert "walk" not in shown.casefold() and "bedtime" in shown
    (claim,) = result.claims
    assert claim.kind == "suggestion" and claim.evidence_ids == [linked.id]
    assert claim.option == "bedtime_hour" and claim.text in shown


def lever_record(supported: bool) -> Evidence:
    lever = {
        "lever": "regular_bedtime",
        "habit": "a regular bedtime, within half an hour of your usual",
        "group": "nights near your usual bedtime",
        "supported": supported,
    }
    return Evidence(
        tool="habit_options",
        metrics=["sleep_minutes"],
        windows=[Window(start="2026-10-11", end="2026-10-31")],
        stats={"supported": supported, "levers": [lever]},
        n=21,
        sufficient=True,
    )


@pytest.mark.parametrize("supported", [True, False])
def test_an_option_the_evidence_does_not_support_falls_back(supported):
    record = lever_record(supported)
    result = coaching_turn([], [record])
    one_coaching_conclusion(result, [record])
    if supported:
        assert "a regular bedtime" in result.summary and result.claims[-1].kind == "suggestion"
    else:
        assert "None of the everyday habits" in result.summary
        assert all(c.kind != "suggestion" for c in result.claims)
    assert "walk" not in result.summary


# ---- nothing changed: nothing to explain, said by code ----


def flat_overview(p_values):
    frame = generate(date(2026, 7, 1), 60, seed=9).frame
    recent = Window(start=date(2026, 8, 1), end=date(2026, 8, 29))
    before = Window(start=date(2026, 7, 1), end=date(2026, 7, 29))
    tests = []
    for metric, p in zip(("steps", "sleep_minutes", "hrv_ms"), p_values, strict=True):
        record = compare_windows(frame, metric, recent, before)
        stats = {**record.stats, RUN_ADJUSTED: p, "tests_in_run": 3, "overview": True}
        tests.append(record.model_copy(update={"stats": stats}))
    return tests, [recent, before]


def why_result(tests):
    result = AgentResult(run_id="r", stop_reason="answered")
    result.evidence = {e.id: e for e in tests}
    result.summary = "Your sleep, activity and recovery all held steady."
    result.claims = [
        Claim(
            text="Steps showed no clear change.",
            kind="no_change",
            evidence_ids=[tests[0].id],
            metric="steps",
        )
    ]
    return result


def why_request(spans):
    return Request(
        kind="investigate",
        focus="why",
        parts=[ResolvedPart(metrics=[], operation="describe", windows=spans)],
    )


def test_explaining_a_look_where_nothing_changed_says_there_is_nothing_to_explain():
    tests, spans = flat_overview([0.8, 0.6, 0.9])
    result = why_result(tests)
    assert nothing_to_explain(result, why_request(spans), TODAY)
    assert "nothing changed clearly" in result.summary and NO_CHANGE_TO_EXPLAIN in result.summary
    assert "held steady" not in result.summary
    assert {i for c in result.claims for i in c.evidence_ids} == {e.id for e in tests}


def test_a_clear_change_still_gets_its_explanation():
    tests, spans = flat_overview([0.8, 0.001, 0.9])
    result = why_result(tests)
    assert not nothing_to_explain(result, why_request(spans), TODAY)
    assert "held steady" in result.summary  # the model's answer stays, checked as before


# ---- a paused workout: elapsed, active and paused time are separate facts ----

NOW = datetime(2026, 10, 31, 18, 0, tzinfo=UTC)
PAUSED = [
    "Draft yesterday's walk from 15:00 until 15:40. I spent 10 minutes paused and walked for 30."
]


def walk(active_minutes, end="15:40"):
    return WorkoutLog.model_validate(
        {
            "exercise_type": "WALKING",
            "start_time": "2026-10-30T15:00:00+00:00",
            "end_time": f"2026-10-30T{end}:00+00:00",
            "active_seconds": active_minutes * 60,
        }
    )


def test_a_stated_pause_is_its_own_fact_beside_the_span_and_the_active_time():
    assert mismatch(walk(30), PAUSED, NOW) is None


def test_a_draft_matching_no_stated_length_names_what_it_has():
    problem = mismatch(walk(40), PAUSED, NOW)
    assert problem and "active time 40 min" in problem and "elapsed time 40 min" in problem
    assert "10 min" in problem


# ---- end to end: what is stored and reopened is the supported option, linked to its record ----


def test_a_reopened_coaching_answer_shows_only_the_tested_option_and_its_record(
    tmp_path, monkeypatch
):
    """The model offers walking advice it invented twice: once under a walking key no record
    tested, once under the valid bedtime key. The person reads, and reopens, only the bedtime
    option the habit test supports, cited to that test."""
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from test_chat_api import FixedRouter, signed_in, submission
    from test_question_strategy import evidence_id_for

    from app.analysis.day import with_scores
    from app.api import auth
    from app.api.chat import AgentParts
    from app.api.main import create_app
    from app.api.store import analyze, get_data
    from app.auth.accounts import LoginThrottle
    from app.db.session import session_scope
    from app.ingest.takeout import DailyData

    url = f"sqlite:///{tmp_path / 'chat.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    planted = (Coupling("bedtime_hour", "sleep_efficiency", 0, -0.9),)
    frame = with_scores(generate(date(2026, 7, 1), 90, planted, seed=2).frame)

    def invented(messages):
        task = messages[1]["content"]
        habit = evidence_id_for(task, "sleep efficiency", "Habits tested")
        walking = "You could try spreading your walks across more days of the week."
        claims = [
            {
                "text": walking,
                "kind": "suggestion",
                "evidence_ids": [habit],
                "metric": "sleep_efficiency",
                "option": "steps",
            },
            {
                "text": walking,
                "kind": "suggestion",
                "evidence_ids": [habit],
                "metric": "sleep_efficiency",
                "option": "earlier_bedtime",
            },
        ]
        return submission(f"{walking} It suits you best.", claims=claims)

    agent = AgentParts(ScriptedLLM([invented, invented]), FixedRouter("coaching", sleep=0.9), None)
    monkeypatch.setattr(auth, "throttle", LoginThrottle())
    monkeypatch.setattr(chat, "_busy", set())
    app = create_app()

    def db():
        with session_scope(engine) as scoped:
            yield scoped

    data = analyze(DailyData(frame=frame), datetime.now(UTC))
    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[get_data] = lambda: data
    app.dependency_overrides[chat.get_agent] = lambda: agent
    app.dependency_overrides[chat.get_sessions] = lambda: lambda: session_scope(engine)
    client = TestClient(app)
    headers = signed_in(client, engine)

    response = client.post("/chat", json={"text": "How can I sleep better?"}, headers=headers)
    assert response.status_code == 200, response.text
    _, answer = response.json()
    reopened = client.get("/chat", headers=headers).json()[-1]
    assert reopened == answer
    for text in (answer["text"], reopened["text"]):
        assert "walk" not in text.casefold() and "It suits you best" not in text
        assert "being in bed by" in text
    (cited,) = reopened["evidenceIds"]
    record = client.get(f"/evidence/{cited}", headers=headers).json()
    assert record["tool"] == "habit_options"
    levers = {lever["lever"]: lever for lever in record["stats"]["levers"]}
    assert levers["earlier_bedtime"]["supported"]
