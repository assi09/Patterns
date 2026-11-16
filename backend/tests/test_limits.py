"""What the data cannot answer is said plainly, and the smaller fixes of the tuning round."""

from datetime import date

import pytest

from app.agent.agent import without_coverage_talk
from app.agent.ask import EDIT_ON_CARD, ask
from app.agent.context import Turn
from app.agent.conversation import CHAT_FALLBACKS, chat_kind
from app.agent.intent import Intent
from app.agent.limits import asks_future, dates_named, other_person, outside_the_data, untracked
from app.agent.llm import ScriptedLLM
from app.agent.router import EXPERT_LABELS, LABELS, Classification
from app.agent.strategy_types import certain_talk
from app.analysis.day import with_scores
from app.analysis.evidence import Window
from app.analysis.tools import describe
from app.reminders.tools import CLAIMS_SET
from app.synthetic import generate

START = date(2026, 7, 1)
TODAY = date(2026, 9, 28)


@pytest.fixture(scope="module")
def frame():
    return with_scores(generate(START, 90, seed=4).frame)


class Router:
    def __init__(self, question_type="day", topic="sleep", intent=Intent.READ):
        self.result = Classification(
            dict.fromkeys(LABELS, 0.0) | {topic: 0.9},
            dict.fromkeys(EXPERT_LABELS, 0.0),
            source="test",
            intent_probabilities={str(i): float(i == intent) for i in Intent},
            question_types={question_type: 1.0},
        )

    def classify(self, question, earlier=()):
        return self.result


@pytest.mark.parametrize(
    "message, who",
    [
        ("how did my wife sleep last night?", "wife"),
        ("What were my son's steps today?", "son"),
        ("I walked with my wife today", None),  # about them, and no question
        ("my boss stressed me out", None),
        ("how did I sleep?", None),
        # Their own sleep, with a relative in the story: a false trigger in the probe run.
        ("my sister visited this week, is my sleep actually worse?", None),
        ("did my husband's heart rate go up?", "husband"),
    ],
)
def test_another_persons_data(message, who):
    assert other_person(message) == who


def test_dates_outside_the_data_get_a_plain_reply():
    start = date(2026, 7, 19)
    before = outside_the_data("how did I sleep on January 3 2025?", start, TODAY)
    assert before and "starts on Jul 19, 2026" in before and "Jan 3, 2025" in before
    assert "hasn't happened yet" in outside_the_data("steps on 2026-12-25?", start, TODAY)
    assert outside_the_data("sleep on Aug 3 2026?", start, TODAY) is None
    assert outside_the_data("how did I sleep on Aug 3?", start, TODAY) is None  # no year
    assert dates_named("3 January 2025 and 2025-01-04") == [date(2025, 1, 3), date(2025, 1, 4)]


@pytest.mark.parametrize(
    "message, future",
    [
        ("how will I sleep tonight?", True),
        ("how many steps will I get tomorrow?", True),
        ("remind me tomorrow at 7 to stretch", False),
        ("how did I sleep last night?", False),
    ],
)
def test_the_future(message, future):
    assert asks_future(message) is future


def test_untracked_things():
    assert untracked("I tend to be drinking more water than usual") == "water"
    assert untracked("does my menstrual cycle affect recovery?") == "menstrual"
    assert untracked("how did I sleep?") is None


def test_another_persons_data_is_answered_without_a_model(frame):
    llm = ScriptedLLM([])
    reply = ask(llm, Router(topic="out_of_scope"), frame, "how did my wife sleep last night?")
    assert reply.result.stop_reason == "limits" and "your wife" in reply.result.summary
    assert llm.requests == []


def test_a_day_before_the_data_is_answered_without_a_model(frame):
    llm = ScriptedLLM([])
    reply = ask(llm, Router(), frame, "how did I sleep on January 3 2025?", today=TODAY)
    assert reply.result.stop_reason == "limits" and "starts on Jul 1, 2026" in reply.result.summary
    assert llm.requests == []


def test_the_future_gets_its_own_guide(frame):
    llm = ScriptedLLM([])
    ask(llm, Router(), frame, "how will I sleep tonight?", today=TODAY)
    assert "can't predict it" in llm.requests[-1]["messages"][1]["content"]


def test_water_is_said_to_be_missing_not_answered_with_food_logs(frame):
    llm = ScriptedLLM([])
    reply = ask(llm, Router("why", topic="nutrition"), frame, "Has more water helped my sleep?")
    assert reply.route.action == "general"
    assert "does not have" in llm.requests[-1]["messages"][1]["content"]


def test_a_correction_after_a_draft_points_to_the_card(frame):
    llm = ScriptedLLM([])
    history = [Turn("log 2 eggs for breakfast", "Ready to log: 2 eggs, today at 08:00.")]
    reply = ask(
        llm,
        Router(topic="nutrition"),
        frame,
        "actually it was 3 eggs",
        history=history,
        after_draft=True,
    )
    assert reply.result.summary == EDIT_ON_CARD and llm.requests == []
    plain = ask(ScriptedLLM([]), Router(), frame, "actually it was 3 eggs", history=history)
    assert plain.result.summary != EDIT_ON_CARD  # only right after a draft


@pytest.mark.parametrize("message", ["?", "...", "😴", "👍"])
def test_only_symbols_is_small_talk(message):
    assert certain_talk(message) and chat_kind(message) == "symbols"


@pytest.mark.parametrize(
    "message", ["who made you? are you chatgpt?", "delete all my data", "is my data private?"]
)
def test_questions_about_the_app_have_an_honest_fallback(message):
    assert certain_talk(message) and chat_kind(message) == "app"
    assert "Patterns team" in CHAT_FALLBACKS["app"]


def test_denying_a_gap_is_still_coverage_talk():
    text = "Time asleep held. There was no low wear time or missing-data issue in this period."
    assert without_coverage_talk(text) == "Time asleep held."


@pytest.mark.parametrize(
    "text, claims_on",
    [
        ("I set up a nightly wind-down reminder for 10:30.", True),
        ("I've set it for you.", True),
        ("Tap Set on the card to turn it on.", False),
        ("Here's the reminder. Tap Set to turn it on.", False),
    ],
)
def test_a_reminder_reply_may_not_say_it_is_on(text, claims_on):
    assert bool(CLAIMS_SET.search(text)) is claims_on


def test_additive_metrics_have_a_weekly_figure(frame):
    window = Window(start=date(2026, 9, 1), end=date(2026, 9, 28))
    steps = describe(frame, "steps", window).stats
    assert steps["per_week"] == pytest.approx(steps["mean"] * 7, rel=1e-3)
    assert "per_week" not in describe(frame, "resting_hr", window).stats
    assert "total" in describe(frame, "sleep_minutes", window).stats  # total sleep over a period


def test_an_overlong_summary_is_explained_once_then_trimmed(frame):
    from app.agent.agent import MAX_SUMMARY, SUBMIT, answer

    long = "You could try an earlier night. " * 40
    submit = ScriptedLLM.call(SUBMIT, summary=long, claims=[])
    llm = ScriptedLLM([submit, submit])
    result = answer(llm, frame, "How can I sleep better?", today=TODAY)
    told = llm.requests[1]["messages"][-1]["content"]
    assert f"limit is {MAX_SUMMARY}" in told and str(len(long)) in told
    assert result.stop_reason == "submitted"
    assert 0 < len(result.summary) <= MAX_SUMMARY and result.summary.endswith(".")


def test_periods_are_named_by_code():
    from datetime import datetime

    from app.agent.periods import with_dates

    now = datetime(2026, 11, 16, 11, 30)  # a Monday
    assert "last week = Mon Nov 9 to Sun Nov 15" in with_dates("sleep last week?", now)
    # A Monday: "this week" would be one day, so it means the last 7.
    assert "this week = the last 7 days, Tue Nov 10 to Mon Nov 16" in with_dates(
        "steps this week", now
    )
    thursday = datetime(2026, 11, 19, 9, 0)
    assert "this week = Mon Nov 16 to Thu Nov 19" in with_dates("steps this week", thursday)
    assert "the last 30 days" in with_dates("sleep this month", datetime(2026, 11, 2, 9, 0))
    assert "about 08:00" in with_dates("I ran this morning, log it", now)
    assert "has not happened yet" in with_dates("log a swim this evening", now)
    assert with_dates("how did I sleep?", now) == "how did I sleep?"


def test_the_agent_reads_the_dates_and_the_router_does_not(frame):
    from datetime import datetime

    class Seeing(Router):
        seen: list[str] = []

        def classify(self, question, earlier=()):
            self.seen.append(question)
            return self.result

    router, llm = Seeing("lookup"), ScriptedLLM([])
    now = datetime(2026, 9, 28, 10, 0)
    ask(llm, router, frame, "average sleep last week?", today=now, now=now)
    assert router.seen[-1] == "average sleep last week?"
    assert "last week = Mon Sep 21 to Sun Sep 27" in llm.requests[-1]["messages"][1]["content"]


def _clear_causes(frame, question="Why has my HRV dropped lately?"):
    from app.agent.strategy import candidate_causes, check_premise

    data = with_scores(frame)
    premise = check_premise(data, question, "recovery")
    if not premise or not premise.holds:
        return None
    records, text = candidate_causes(data, premise)
    lines = text.splitlines()[1:]
    return {
        r.metrics[0]
        for r, line in zip(records, lines, strict=False)
        if "clear change" in line and "no clear" not in line
    }


def test_code_finds_the_cause_of_a_change_and_none_when_there_is_none():
    found = missed = false_alarms = checked = 0
    for seed in range(20):
        base = generate(START, 120, seed=100 + seed).frame
        last = base.index[-21:]
        caused = base.copy()
        caused.loc[last, "sleep_minutes"] -= 70
        caused.loc[last, "hrv_ms"] -= 9
        alone = base.copy()
        alone.loc[last, "hrv_ms"] -= 9
        with_cause, without = _clear_causes(caused), _clear_causes(alone)
        if with_cause is None or without is None:
            continue  # the premise check did not confirm the drop: nothing to explain
        checked += 1
        found += "sleep_minutes" in with_cause
        missed += "sleep_minutes" not in with_cause
        false_alarms += bool(without)
    assert checked >= 15
    assert found / checked >= 0.9  # a 70-minute drop over three weeks is found
    assert false_alarms / checked <= 0.15  # and a lone change is rarely given a cause


@pytest.mark.parametrize(
    "description, query, chain",
    [
        ("McDONALD'S, Bacon Ranch Salad with Crispy Chicken", "chicken salad", True),
        ("Fast foods, salad, with chicken", "chicken salad", True),
        ("Chicken salad spread", "chicken salad", False),
        ("McDONALD'S, Big Mac", "mcdonalds big mac", False),  # they named it
        ("Egg, whole, raw, fresh", "eggs", False),
    ],
)
def test_generic_foods_come_before_restaurant_items(description, query, chain):
    from app.outside import restaurant_item

    assert restaurant_item(description, query) is chain


def test_a_reminder_listing_is_said_by_code():
    from app.reminders.tools import listing_reply

    rows = [
        {"title": "Wind down", "schedule": "Every day at 22:30", "status": "proposed"},
        {"title": "Stretch", "schedule": "Once, Tue 17 Nov at 07:00", "status": "active"},
    ]
    text = listing_reply(rows)
    assert "2 reminders" in text and "every day at 22:30" in text and "(on)" in text
    assert "no reminders" in listing_reply([])


def test_an_untracked_question_that_fails_its_checks_is_answered_honestly(frame):
    from app.agent.agent import NO_ANSWER

    llm = ScriptedLLM([])  # every run fails: no submission at all
    reply = ask(
        llm, Router("why", topic="recovery"), frame, "Does my menstrual cycle hurt my recovery?"
    )
    assert reply.result.summary != NO_ANSWER
    assert "doesn't include menstrual" in reply.result.summary


def test_a_total_with_no_period_means_all_the_data():
    # "What are the total REM sleep minutes?" was answered with last night (PHIA, 2026-11-16).
    from datetime import datetime

    from app.agent.periods import asks_over_days, names_no_period, with_dates

    now, first = datetime(2026, 11, 16, 11, 30), date(2026, 7, 1)
    noted = with_dates("What are the total REM sleep minutes?", now, first)
    assert "no period is named, so all the data, Wed Jul 1 to Mon Nov 16" in noted
    assert "all the data" in with_dates("what is my highest steps?", now, first)
    for kept in (
        "how did I sleep?",  # no total, average or extreme asked for
        "What is the total awake minutes today",  # one day
        "total steps this week",  # a period of its own
        "average sleep last 7 days",
        "my lowest HRV since October",
    ):
        assert "all the data" not in with_dates(kept, now, first), kept
    assert with_dates("What are the total REM sleep minutes?", now) == (
        "What are the total REM sleep minutes?"  # without the first day, nothing to name
    )
    assert asks_over_days("total sleep last 30 days") and not names_no_period(
        "total sleep last 30 days"
    )
    assert not asks_over_days("average deep sleep last night")


def test_a_total_typed_as_one_day_gets_the_tools_that_add_days_up(frame):
    from datetime import datetime

    llm = ScriptedLLM([])
    now = datetime(2026, 9, 28, 10, 0)
    ask(
        llm, Router("day"), frame, "What was the sum of the deep sleep minutes?", today=now, now=now
    )
    request = llm.requests[-1]
    offered = set(request["tools"])
    assert "describe" in offered  # the day strategy has no describe
    assert "all the data" in request["messages"][1]["content"]
    llm = ScriptedLLM([])
    ask(llm, Router("day"), frame, "How did I sleep last night?", today=now, now=now)
    offered = set(llm.requests[-1]["tools"])
    assert "describe" not in offered  # a real day question keeps the day strategy


@pytest.mark.parametrize(
    "said, kind",
    [
        ("Nah i meant 100g cooked chicken and 100g cooked rice", "correct"),
        ("no, it was 3 eggs", "correct"),
        ("actually 2 slices", "correct"),
        ("it should be 250 kcal", "correct"),
        ("Log it", "confirm"),
        ("yes please", "confirm"),
        ("looks good!", "confirm"),
        ("no thanks", None),
        ("now log a run too", None),
        ("yes, and how did I sleep?", None),
    ],
)
def test_what_reads_as_a_correction_or_a_confirmation_of_a_draft(said, kind):
    from app.agent.ask import CONFIRMS, CORRECTS

    found = "confirm" if CONFIRMS.match(said) else "correct" if CORRECTS.match(said) else None
    assert found == kind
