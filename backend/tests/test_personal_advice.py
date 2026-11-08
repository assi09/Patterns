"""Advice specific to the person: what stands out, what is refused, and when it is offered."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.agent.ask import ask
from app.agent.llm import ScriptedLLM
from app.agent.present import display
from app.agent.router import EXPERT_LABELS, LABELS, Classification
from app.agent.strategy import coaching_evidence
from app.agent.verifier import GENERIC_ADVICE, Claim, check_claim, text_problems
from app.alarms.explain import explain, specific_advice
from app.analysis.coaching import personal_options
from app.analysis.evidence import ToolError, Window
from app.synthetic import generate

START = date(2026, 8, 1)
DAYS = 90
END = START + timedelta(days=DAYS - 1)
WINDOW = Window(start=END - timedelta(days=59), end=END)


def person(seed: int = 11) -> pd.DataFrame:
    frame = generate(START, DAYS, seed=seed).frame
    frame["strain"] = 10.0 + np.random.default_rng(seed).normal(0, 1, len(frame))
    return frame


def steady() -> pd.DataFrame:
    """Nothing stands out: the same bedtime, sleep and steps every day."""
    frame = person()
    frame["bedtime_hour"] = -0.5
    frame["sleep_efficiency"] = 80.0 + np.tile([0.0, 0.1], len(frame) // 2 + 1)[: len(frame)]
    frame["sleep_minutes"] = 420.0 + np.tile([0.0, 1.0], len(frame) // 2 + 1)[: len(frame)]
    frame["steps"] = 8000.0
    return frame


def keys(evidence) -> list[str]:
    return [option["key"] for option in evidence.stats["options"]]


def test_a_steady_person_gets_nothing_rather_than_a_filler():
    evidence = personal_options(steady(), "sleep_efficiency", WINDOW)
    assert not evidence.sufficient and evidence.stats["options"] == []


def test_later_weekends_stand_out_with_the_persons_own_number():
    frame = steady()
    frame.loc[frame.index.dayofweek >= 5, "bedtime_hour"] = 0.5  # an hour later
    evidence = personal_options(frame, "sleep_efficiency", WINDOW)
    option = next(o for o in evidence.stats["options"] if o["key"] == "weekend_shift")
    assert "1 h 0 min later" in option["note"] and "bedtime_hour" in evidence.metrics


def test_bedtimes_on_best_and_worst_nights_are_compared():
    frame = steady()
    rng = np.random.default_rng(3)
    frame["bedtime_hour"] = -0.5 + rng.normal(0, 1, len(frame))
    frame["sleep_efficiency"] = 90 - 3 * (frame["bedtime_hour"] + 0.5)
    evidence = personal_options(frame, "sleep_efficiency", WINDOW)
    assert "best_nights" in keys(evidence)
    assert evidence.stats["best_bedtime"] < evidence.stats["worst_bedtime"]


def test_a_metric_where_lower_is_better_ranks_the_right_way():
    frame = steady()
    rng = np.random.default_rng(4)
    frame["bedtime_hour"] = -0.5 + rng.normal(0, 1, len(frame))
    frame["resting_hr"] = 60 + 3 * (frame["bedtime_hour"] + 0.5)  # later goes with higher
    evidence = personal_options(frame, "resting_hr", WINDOW)
    assert evidence.stats["best_bedtime"] < evidence.stats["worst_bedtime"]


def test_time_in_bed_is_named_as_the_limit_when_they_sleep_well_in_it():
    frame = steady()
    frame["sleep_efficiency"] = 95.0
    frame["time_in_bed"] = 400.0
    assert "time_in_bed" in keys(personal_options(frame, "sleep_minutes", WINDOW))


def test_a_heavier_week_stands_out_for_recovery():
    frame = steady()
    frame.loc[frame.index[-7:], "strain"] = 16.0
    evidence = personal_options(
        frame, "recovery_score" if "recovery_score" in frame else "hrv_ms", WINDOW
    )
    assert "heavy_week" in keys(evidence)


def test_the_quietest_weekday_stands_out_for_steps():
    frame = steady()
    frame.loc[frame.index.dayofweek == 1, "steps"] = 3000.0
    option = personal_options(frame, "steps", WINDOW).stats["options"][0]
    assert option["key"] == "quiet_day" and option["note"].startswith("Tuesday")


def test_a_recent_dip_stands_out_but_a_recent_rise_does_not():
    frame = person()
    frame.loc[frame.index[-7:], "steps"] = frame["steps"].mean() * 0.4
    assert "recent_dip" in keys(personal_options(frame, "steps", WINDOW))
    frame.loc[frame.index[-7:], "steps"] = frame["steps"].mean() * 3
    assert "recent_dip" not in keys(personal_options(frame, "steps", WINDOW))


def test_a_metric_with_no_better_direction_is_refused():
    with pytest.raises(ToolError):
        personal_options(person(), "calories", WINDOW)


def test_too_few_days_says_nothing():
    short = Window(start=END - timedelta(days=9), end=END)
    assert "best_nights" not in keys(personal_options(person(), "sleep_efficiency", short))


def test_options_are_capped():
    frame = person()
    assert len(personal_options(frame, "sleep_efficiency", WINDOW).stats["options"]) <= 4


@pytest.mark.parametrize("seed", range(20))
def test_the_notes_quote_only_numbers_the_evidence_holds(seed):
    frame = person(seed)
    frame.loc[frame.index.dayofweek >= 5, "bedtime_hour"] += 1.0
    for metric in ("sleep_efficiency", "sleep_minutes", "steps"):
        evidence = personal_options(frame, metric, WINDOW)
        for option in evidence.stats["options"]:
            assert text_problems(f"You could try this: {option['note']}.", [evidence]) == []


def suggestion(text: str, evidence) -> Claim:
    return Claim(
        text=text, kind="suggestion", evidence_ids=[evidence.id], metric=evidence.metrics[0]
    )


def test_a_suggestion_on_what_stands_out_passes_and_an_order_does_not():
    frame = steady()
    frame.loc[frame.index.dayofweek >= 5, "bedtime_hour"] = 0.5
    evidence = personal_options(frame, "sleep_efficiency", WINDOW)
    kind = {evidence.id: evidence}
    assert not check_claim(
        suggestion("You could try pulling Saturday back a little.", evidence), kind
    )
    assert check_claim(suggestion("You must go to bed earlier on Saturdays.", evidence), kind)


def test_nothing_standing_out_backs_no_suggestion():
    evidence = personal_options(steady(), "sleep_efficiency", WINDOW)
    reasons = check_claim(
        suggestion("You could try an earlier night.", evidence), {evidence.id: evidence}
    )
    assert any("specific to this person" in reason for reason in reasons)


@pytest.mark.parametrize(
    "text",
    [
        "You could try slow breathing before bed.",
        "Try to get 8 hours of sleep.",
        "Aim for 7-9 hours.",
        "A balanced diet might help.",
        "You could try to stay hydrated.",
        "Practising good sleep hygiene could help.",
        "You might reduce your stress.",
        "Try meditation.",
    ],
)
def test_advice_anyone_could_read_anywhere_is_refused(text):
    assert GENERIC_ADVICE.search(text)
    assert any("anyone could read" in reason for reason in text_problems(text, []))


@pytest.mark.parametrize(
    "text",
    [
        "Your weekend bedtimes run 1 h 0 min later than weekdays.",
        "Your stress score held steady.",
        "You slept 8 hours on Oct 12.",
    ],
)
def test_specific_sentences_are_not_taken_for_generic_advice(text):
    assert not GENERIC_ADVICE.search(text)


class Fixed:
    def __init__(self, kind: str):
        self.kind = kind

    def classify(self, question, earlier=()):
        return Classification(
            dict.fromkeys(LABELS, 0.0) | {"sleep": 0.9},
            dict.fromkeys(EXPERT_LABELS, 0.0),
            source="test",
            question_types={self.kind: 1.0},
        )


def task(kind: str, frame) -> str:
    llm = ScriptedLLM([ScriptedLLM.say("x")] * 5)
    ask(llm, Fixed(kind), frame, "Anything?")
    return llm.requests[0]["messages"][-1]["content"]


def weekend_person():
    frame = steady()
    frame.loc[frame.index.dayofweek >= 5, "bedtime_hour"] = 0.5
    return frame


def test_a_coaching_question_is_given_what_stands_out():
    assert "What stands out in their own routine" in task("coaching", weekend_person())


def test_a_question_about_what_happened_is_not():
    assert "What stands out in their own routine" not in task("day", weekend_person())
    assert "What stands out in their own routine" not in task("why", weekend_person())


def test_the_evidence_shows_its_options_readably():
    evidence, text = coaching_evidence(weekend_person(), "sleep", ["sleep_efficiency"])
    assert "later than weekdays" in text
    routine = next(e for e in evidence if e.tool == "personal_options")
    assert "later than weekdays" in display(routine)["options"]


# Alerts


ALARM = dict(
    metric="sleep_efficiency", title="Low", body="Lower than usual.", evidence=[], today=END
)


def told(kind: str, frame) -> str:
    llm = ScriptedLLM([ScriptedLLM.say("x")] * 5)
    explain(llm, frame, kind=kind, **ALARM)
    return llm.requests[0]["messages"][-1]["content"]


def test_a_lasting_problem_with_something_specific_gets_advice():
    question = told("streak", weekend_person())
    assert "End with one thing they could try" in question and "later than weekdays" in question


def test_one_bad_day_gets_no_advice():
    assert "give no advice" in told("day", weekend_person())


def test_with_nothing_specific_an_alert_stays_a_description():
    assert "give no advice" in told("streak", steady())


def test_a_metric_with_no_better_direction_has_no_advice():
    assert specific_advice(person(), "calories", END) == ([], "")


def test_an_alert_is_given_what_the_person_kept():
    llm = ScriptedLLM([ScriptedLLM.say("x")] * 5)
    explain(llm, steady(), kind="streak", context="They have exams this week.", **ALARM)
    assert "They have exams this week." in llm.requests[0]["messages"][-1]["content"]


def test_what_stands_out_comes_with_how_to_try_it():
    from app.agent.knowledge import cards_for
    from app.analysis.evidence import Evidence, Window

    record = Evidence(
        tool="personal_options",
        metrics=("sleep_efficiency",),
        windows=(Window(start=WINDOW.start, end=WINDOW.end),),
        n=30,
        sufficient=True,
        stats={"options": [{"key": "bedtime_spread", "note": "", "try": ""}]},
    )
    assert [card.id for card in cards_for([record])] == ["fixed-wake-time"]


def test_an_answer_about_what_it_cannot_do_is_sent_back():
    from app.agent.verifier import text_problems

    for text in (
        "I can't give you 5 points from your data.",
        "Here are the evidence-based points.",
        "Nothing in your tested habits was clear.",
    ):
        assert any("talks about itself" in reason for reason in text_problems(text, []))
    assert text_problems("You could try one fixed morning alarm.", []) == []
