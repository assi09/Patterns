"""The agent's newer tools: regularity, training load, ranking, usual ranges, check-ins, habits."""

from datetime import date, timedelta

import pytest

from app.agent.present import display
from app.agent.tools import TOOLS, Toolbox
from app.agent.verifier import Claim, check_claim
from app.analysis.coaching import habit_options
from app.analysis.day import with_scores
from app.analysis.evidence import ToolError, Window
from app.analysis.habits import (
    checkin_summary,
    rank_days,
    sleep_regularity,
    tag_effect,
    training_load,
    usual_ranges,
    with_checkins,
)
from app.db.models import CHECKIN_TAGS
from app.synthetic import Coupling, LowWear, generate

START = date(2026, 7, 1)
END = START + timedelta(days=89)
WINDOW = Window(start=END - timedelta(days=59), end=END)


def person(seed=0, *effects):
    return with_scores(generate(START, 90, effects, seed=seed).frame)


def test_habit_options_finds_a_real_bedtime_link_and_claims_can_cite_it():
    frame = person(2, Coupling("bedtime_hour", "sleep_efficiency", 0, -0.9))
    evidence = habit_options(frame, "sleep_efficiency", WINDOW)
    levers = evidence.stats["levers"]
    earlier = next(lever for lever in levers if lever["lever"] == "earlier_bedtime")
    assert evidence.stats["supported"] and earlier["supported"]
    assert earlier["mean_with"] > earlier["mean_without"]
    assert "bedtime_hour" in evidence.metrics and evidence.stats["split_at"] is not None
    shown = display(evidence)
    assert "supported" in shown["levers"] and ":" in shown["split_at"]
    claim = Claim(
        text=f"On nights you were in bed by {shown['split_at']}, your sleep efficiency was higher, "
        "so you could try that on weeknights.",
        kind="suggestion",
        evidence_ids=[evidence.id],
        metric="sleep_efficiency",
    )
    assert check_claim(claim, {evidence.id: evidence}) == []


def test_habit_options_rarely_supports_anything_on_calm_people():
    supported = sum(
        habit_options(person(seed), "sleep_efficiency", WINDOW).stats["supported"]
        for seed in range(30)
    )
    assert supported / 30 <= 0.15  # several levers, corrected together


def test_habit_options_needs_a_metric_with_a_better_direction():
    with pytest.raises(ToolError, match="better direction"):
        habit_options(person(), "bedtime_hour", WINDOW)


def test_sleep_regularity_measures_spread_and_weekend_shift():
    evidence = sleep_regularity(person(), WINDOW)
    assert evidence.sufficient and evidence.stats["bedtime_spread_minutes"] > 0
    assert "weekend_shift_minutes" in evidence.stats
    assert "on weekends" in display(evidence)["weekend_shift_minutes"]
    short = Window(start=END - timedelta(days=3), end=END)
    assert not sleep_regularity(person(), short).sufficient


def test_training_load_compares_the_week_with_the_month():
    evidence = training_load(person(), END)
    assert evidence.sufficient
    assert evidence.stats["band"] in ("lighter than usual", "steady", "heavier than usual")
    assert {"recovery_after_hard", "recovery_after_other", "p_value"} <= set(evidence.stats)
    with pytest.raises(ToolError):
        training_load(person().drop(columns=["strain"]), END)


@pytest.mark.parametrize("order", ["best", "worst", "highest", "lowest"])
def test_rank_days_orders_by_which_way_is_better(order):
    frame = person()
    evidence = rank_days(frame, "resting_hr", WINDOW, order, 3)
    values = [d["value"] for d in evidence.stats["days"]]
    lowest_first = order in ("best", "lowest")  # a lower resting heart rate is better
    if order in ("best", "worst"):  # and more sleep is better
        sleep = [d["value"] for d in rank_days(frame, "sleep_minutes", WINDOW, order).stats["days"]]
        assert sleep == sorted(sleep, reverse=order == "best")
    assert values == sorted(values, reverse=not lowest_first) and len(values) == 3


def test_rank_days_refuses_best_for_a_metric_without_a_direction():
    with pytest.raises(ToolError, match="highest or lowest"):
        rank_days(person(), "bedtime_hour", WINDOW, "best")


def test_usual_ranges_lists_the_main_metrics():
    evidence = usual_ranges(person(), END)
    ranges = evidence.stats["ranges"]
    assert {"sleep_minutes", "resting_hr", "recovery_score"} <= set(ranges)
    assert all(r["low"] <= r["median"] <= r["high"] for r in ranges.values())
    assert "resting heart rate" in display(evidence)["ranges"]


def checkin_frame():
    frame = person(3)
    checkins = []
    for k in range(40):
        day = END - timedelta(days=k)
        stressed = k % 3 == 0
        checkins.append((day, 2 if stressed else 4, ["stress"] if stressed else []))
        if stressed:  # stressful days go with shorter sleep in this made-up person
            frame.loc[str(day), "sleep_minutes"] -= 60
    return with_checkins(frame, checkins, CHECKIN_TAGS)


def test_checkins_and_tag_effect():
    frame = checkin_frame()
    summary = checkin_summary(frame, WINDOW)
    assert summary.sufficient and summary.stats["tag_days"]["stress"] > 0
    effect = tag_effect(frame, "stress", "sleep_minutes", WINDOW)
    assert (
        effect.stats["mean_with"] < effect.stats["mean_without"] and effect.stats["p_value"] < 0.05
    )
    assert "on days with stress" in display(effect)["with_tag"]
    with pytest.raises(ToolError, match="Unknown check-in tag"):
        tag_effect(frame, "coffee", "sleep_minutes", WINDOW)
    with pytest.raises(ToolError, match="no morning check-ins"):
        checkin_summary(person(), WINDOW)


def test_the_agent_can_call_every_new_tool_through_the_toolbox():
    frame = checkin_frame()
    box = Toolbox(
        frame,
        [
            "sleep_minutes",
            "sleep_efficiency",
            "bedtime_hour",
            "resting_hr",
            "strain",
            "recovery_score",
        ],
    )
    period = {"start": WINDOW.start.isoformat(), "end": WINDOW.end.isoformat()}
    calls = {
        "sleep_regularity": period,
        "training_load": {"day": END.isoformat()},
        "rank_days": {**period, "metric": "sleep_minutes", "order": "worst"},
        "usual_ranges": {"day": END.isoformat()},
        "checkins": period,
        "tag_effect": {**period, "metric": "sleep_minutes", "tag": "stress"},
        "habit_options": {**period, "metric": "sleep_minutes"},
    }
    assert set(calls) <= set(TOOLS)
    for name, arguments in calls.items():
        from app.agent.llm import ToolCall

        result = box.run(ToolCall(f"c_{name}", name, arguments))
        assert result.evidence is not None, (name, result.content)
    bad = box.run(ToolCall("bad", "tag_effect", {**period, "metric": "steps", "tag": "stress"}))
    assert bad.evidence is None  # steps is not in this expert's scope


def test_low_wear_days_do_not_break_the_tools():
    frame = person(4, LowWear(END - timedelta(days=10), END - timedelta(days=5)))
    assert habit_options(frame, "sleep_minutes", WINDOW).sufficient
    assert sleep_regularity(frame, WINDOW).sufficient


def test_a_summary_may_describe_a_supported_habit_with_direction_words():
    from app.agent.verifier import overstated

    frame = person(2, Coupling("bedtime_hour", "sleep_efficiency", 0, -0.9))
    supported = habit_options(frame, "sleep_efficiency", WINDOW)
    summary = "Being in bed earlier went with higher sleep efficiency, so you could try that."
    assert overstated(summary, [supported]) == []
    calm = habit_options(person(5), "sleep_efficiency", WINDOW)
    assert not calm.stats["supported"] and overstated(summary, [calm])


def test_goal_progress_counts_days_that_met_a_target():
    from datetime import date

    import pandas as pd

    from app.analysis.evidence import Window
    from app.analysis.habits import goal_progress

    days = pd.date_range("2026-10-01", periods=10, name="date")
    frame = pd.DataFrame({"steps": [9000.0] * 4 + [5000.0] * 6}, index=days)
    window = Window(start=date(2026, 10, 1), end=date(2026, 10, 10))
    evidence = goal_progress(frame, "steps", 8000, "at_least", window)
    assert evidence.stats["days_met"] == 4 and evidence.stats["last_week_counted"] == 7
    assert goal_progress(frame, "steps", 8000, "at_most", window).stats["days_met"] == 6


def test_the_agent_can_call_goal_progress():
    from datetime import date

    import pandas as pd

    from app.agent.llm import ToolCall
    from app.agent.tools import Toolbox

    days = pd.date_range("2026-10-01", periods=10, name="date")
    frame = pd.DataFrame({"steps": [9000.0] * 10}, index=days)
    arguments = {
        "metric": "steps",
        "goal_value": 8000,
        "direction": "at_least",
        "start": date(2026, 10, 1).isoformat(),
        "end": date(2026, 10, 10).isoformat(),
    }
    result = Toolbox(frame, ["steps"]).run(ToolCall("x", "goal_progress", arguments))
    assert result.error is None and result.evidence.stats["days_met"] == 10
