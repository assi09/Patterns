from datetime import date, timedelta

import pytest

from app.agent.verifier import Claim, check_claim, verify
from app.analysis.evidence import Evidence, Window
from app.analysis.tools import change_point, compare_windows, correlate, coverage, describe
from app.synthetic import Coupling, Step, generate

START = date(2026, 7, 1)
CHANGE_DAY = START + timedelta(30)


def window(first: int, last: int) -> Window:
    return Window(start=START + timedelta(first), end=START + timedelta(last))


@pytest.fixture(scope="module")
def evidence():
    """A person whose sleep dropped (about 90 minutes) when their bedtime moved an hour later."""
    effects = (
        Step("bedtime_hour", CHANGE_DAY, 1.0),
        Coupling("bedtime_hour", "sleep_minutes", lag_days=0, strength=-0.9),
        Step("sleep_minutes", CHANGE_DAY, -45),
    )
    frame = generate(START, 60, effects, seed=3).frame
    found = {
        "sleep": compare_windows(frame, "sleep_minutes", window(30, 59), window(0, 29)),
        "steps": compare_windows(frame, "steps", window(30, 59), window(0, 29)),
        "shift": change_point(frame, "sleep_minutes", window(0, 59)),
        "link": correlate(frame, "bedtime_hour", "sleep_minutes", window(0, 59)),
        "coverage": coverage(frame, window(0, 59)),
        "short": describe(frame, "sleep_minutes", window(0, 1)),
    }
    assert found["sleep"].stats["p_value"] < 0.001 and found["steps"].stats["p_value"] > 0.05
    return found


def by_id(evidence) -> dict:
    return {e.id: e for e in evidence.values()}


def claim(text, kind="change", ids=("sleep",), metric="sleep_minutes", direction="down", ev=None):
    return Claim(
        text=text,
        kind=kind,
        evidence_ids=[ev[i].id for i in ids] if ev else list(ids),
        metric=metric,
        direction=direction,
    )


def reasons(evidence, text, **kwargs):
    return check_claim(claim(text, ev=evidence, **kwargs), by_id(evidence))


def test_a_supported_change_with_quoted_numbers_passes(evidence):
    stats = evidence["sleep"].stats
    text = (
        f"Your sleep fell by about {abs(stats['difference']):.0f} minutes a night, from "
        f"{stats['mean_baseline'] / 60:.1f} to {stats['mean_recent'] / 60:.1f} hours."
    )
    assert reasons(evidence, text) == []


def test_the_change_must_point_the_stated_way(evidence):
    assert "does not point up" in " ".join(reasons(evidence, "Sleep went up.", direction="up"))


def test_wording_must_not_contradict_the_direction(evidence):
    found = reasons(evidence, "Your sleep increased lately.", direction="down")
    assert "wording contradicts" in " ".join(found)


def test_a_change_must_be_significant(evidence):
    found = reasons(evidence, "Your steps dropped.", ids=("steps",), metric="steps")
    assert "not significant" in " ".join(found) or "significant at" in " ".join(found)


def test_change_claims_need_a_direction(evidence):
    assert "state its direction" in " ".join(reasons(evidence, "Sleep changed.", direction=None))


def test_made_up_numbers_are_rejected(evidence):
    found = reasons(evidence, "Your sleep fell by 150 minutes.")
    assert "numbers not found" in " ".join(found) and "150" in " ".join(found)


def test_missing_and_thin_evidence_is_rejected(evidence):
    unknown = Claim(
        text="Sleep fell.",
        kind="change",
        evidence_ids=["nope"],
        metric="sleep_minutes",
        direction="down",
    )
    assert "does not exist" in check_claim(unknown, by_id(evidence))[0]
    found = reasons(evidence, "Sleep fell.", ids=("sleep", "short"))
    assert "too little data" in " ".join(found)


def test_the_change_date_and_dates_inside_the_windows_may_be_quoted(evidence):
    change = evidence["shift"].stats["change_date"]
    day = date.fromisoformat(change)
    text = f"Your sleep dropped from {day:%b} {day.day} onward ({change})."
    assert reasons(evidence, text, ids=("shift",)) == []


def test_dates_outside_the_evidence_are_rejected(evidence):
    found = reasons(evidence, "Your sleep dropped after Dec 25.", ids=("shift",))
    assert "dates outside" in " ".join(found)


def test_associations_need_a_significant_correlation_in_the_right_direction(evidence):
    ok = reasons(
        evidence,
        "Nights with a later bedtime had less sleep.",
        kind="association",
        ids=("link",),
        direction="down",
    )
    assert ok == []
    wrong = reasons(
        evidence,
        "Later bedtimes went with more sleep.",
        kind="association",
        ids=("link",),
        direction="up",
    )
    assert "does not point up" in " ".join(wrong)
    not_a_correlation = reasons(
        evidence, "Bedtime and sleep move together.", kind="association", ids=("sleep",)
    )
    assert "association evidence" in " ".join(not_a_correlation)


@pytest.mark.parametrize(
    "text, reason",
    [
        ("Your sleep dropped because of your later bedtime.", "states causation"),
        ("Your sleep dropped, which may be insomnia.", "medical language"),
        ("Your sleep dropped while you ran a calorie deficit.", "calorie balance"),
    ],
)
def test_forbidden_wording_is_rejected(evidence, text, reason):
    assert reason in " ".join(reasons(evidence, text))


def test_no_change_claims_must_match_the_evidence(evidence):
    ok = reasons(
        evidence,
        "Your steps did not change.",
        kind="no_change",
        ids=("steps",),
        metric="steps",
        direction=None,
    )
    assert ok == []
    wrong = reasons(evidence, "Your sleep stayed the same.", kind="no_change", direction=None)
    assert "shows a significant one" in " ".join(wrong)


def test_data_quality_claims_cite_coverage(evidence):
    assert (
        reasons(
            evidence,
            "Some days had little wear.",
            kind="data_quality",
            ids=("coverage",),
            metric=None,
            direction=None,
        )
        == []
    )
    found = reasons(
        evidence,
        "Some days had little wear.",
        kind="data_quality",
        ids=("sleep",),
        metric=None,
        direction=None,
    )
    assert "coverage evidence" in " ".join(found)


def test_claims_must_be_about_the_cited_metric(evidence):
    found = reasons(evidence, "Steps fell.", metric="steps")
    assert "none of the cited evidence is about steps" in " ".join(found)


def test_verify_separates_accepted_and_rejected_claims(evidence):
    good = claim("Your sleep fell.", ev=evidence)
    bad = claim("Your sleep fell by 150 minutes.", ev=evidence)
    verdict = verify([good, bad], by_id(evidence))
    assert verdict.accepted == (good,)
    assert verdict.rejected[0].claim == bad and verdict.rejected[0].reasons


def test_durations_in_hours_and_minutes_are_checked(evidence):
    from app.agent.present import duration

    stats = evidence["sleep"].stats
    recent, drop = duration(stats["mean_recent"]), duration(stats["difference"])
    good = f"You slept {recent} on average, down {drop}."
    assert reasons(evidence, good) == []
    assert "durations not found" in " ".join(
        reasons(evidence, "You slept 3 h 5 min on average, down.")
    )


@pytest.fixture(scope="module")
def bedtime():
    frame = generate(START, 60, (Step("bedtime_hour", CHANGE_DAY, 1.0),), seed=3).frame
    return compare_windows(frame, "bedtime_hour", window(30, 59), window(0, 29))


def test_clock_times_must_match_the_evidence(bedtime):
    from app.agent.present import clock

    stats = bedtime.stats
    ok = Claim(
        text=f"Your bedtime moved later, from about {clock(stats['mean_baseline'])} to "
        f"{clock(stats['mean_recent'])}.",
        kind="change",
        evidence_ids=[bedtime.id],
        metric="bedtime_hour",
        direction="up",
    )
    assert check_claim(ok, {bedtime.id: bedtime}) == []
    invented = ok.model_copy(update={"text": "Your bedtime moved later, to about 3:15 am."})
    assert "times of day" in " ".join(check_claim(invented, {bedtime.id: bedtime}))


def test_internal_metric_names_are_rejected(evidence):
    found = reasons(evidence, "Your sleep_minutes went down.")
    assert "internal metric names (sleep_minutes)" in " ".join(found)


def test_evidence_ids_in_the_text_get_their_own_reason(evidence):
    from app.agent.verifier import text_problems

    cited = list(evidence.values())
    found = text_problems(f"Your sleep got shorter (evidence {cited[0].id}).", cited)
    assert found == ["writes evidence ids in the text; list them only in evidence_ids"]
    assert text_problems("Your sleep got shorter (evidence deadbeefcafe).", cited) == []


def test_text_problems_check_any_text_against_evidence(evidence):
    from app.agent.verifier import text_problems

    cited = list(evidence.values())
    assert text_problems("Your sleep got shorter while bedtime moved later.", cited) == []
    assert text_problems("You slept 2 h less, due to stress.", cited)


def test_a_sentence_may_only_name_metrics_its_evidence_covers(evidence):
    from app.agent.verifier import text_problems

    sleep = [evidence["sleep"]]
    found = text_problems("Your time asleep went down, and your HRV held steady.", sleep)
    assert found == [
        "mentions heart rate variability (HRV), which none of the cited evidence covers; "
        "describe only what the evidence shows"
    ]
    assert text_problems("Your time asleep went down.", sleep) == []
    # A correlation covers both of its metrics.
    assert text_problems("Later bedtimes went with less time asleep.", [evidence["link"]]) == []
    assert "bedtime" in " ".join(text_problems("Your bedtime moved later.", sleep))


def test_generic_words_do_not_count_as_naming_a_metric(evidence):
    from app.agent.verifier import text_problems

    steps = [evidence["steps"]]
    assert (
        text_problems("Your activity and sleep looked steady; steps did not change.", steps) == []
    )
    # "time awake in bed" is its own metric, not "time in bed".
    found = " ".join(text_problems("Time awake in bed rose.", [evidence["sleep"]]))
    assert "time awake in bed" in found and "time in bed," not in found


def _test_evidence(metric: str, p: float, tool: str = "compare_windows") -> Evidence:
    return Evidence(
        tool=tool,
        metrics=(metric,),
        windows=(window(0, 29),),
        n=30,
        sufficient=True,
        stats={"p_value": p, "difference": -1.0},
    )


def test_a_summary_may_not_describe_a_change_no_significant_test_shows():
    from app.agent.verifier import overstated

    # From a real run: the weekday split of sleep score was not significant.
    evidence = [
        _test_evidence("sleep_score", 0.2, "weekday_split"),
        _test_evidence("sleep_minutes", 0.6, "weekday_split"),
    ]
    summary = (
        "The main difference is that sleep score was somewhat lower on weekends, while time "
        "asleep and sleep efficiency do not show clear weekend-weekday differences."
    )
    assert overstated(summary, evidence) == [
        "describes a change in sleep score that no significant evidence in this run shows; say "
        "there was no clear change, or leave it out"
    ]


def test_each_clause_is_judged_on_its_own():
    from app.agent.verifier import overstated

    # From a real run: bedtime's change was significant, time in bed's was not.
    evidence = [_test_evidence("bedtime_hour", 0.001), _test_evidence("time_in_bed", 0.09)]
    summary = "You started going to bed later, and spending less time in bed."
    found = overstated("Your bedtime moved later. You spent less time in bed.", evidence)
    assert "time in bed" in found[0] and "bedtime" not in found[0]
    assert overstated("Your bedtime moved later.", evidence) == []
    assert "time in bed" in overstated(summary, evidence)[0]


def test_a_hedged_direction_is_allowed_for_a_tested_metric():
    from app.agent.verifier import overstated

    # From a real answer: time asleep's drop was significant alone (p 0.016) but not after the
    # run's correction. Saying so with a hedge is honest; without one it overstates.
    evidence = [_test_evidence("sleep_minutes", 0.096), _test_evidence("bedtime_hour", 0.57)]
    hedged = (
        "You slept a little less in the last month, though with this many checks that could "
        "be normal variation. Your bedtime held steady."
    )
    assert overstated(hedged, evidence) == []
    assert "time asleep" in overstated("You slept a little less in the last month.", evidence)[0]
    # A hedge does not license a metric the run never tested.
    untested = "Your HRV was a little lower, though that could be normal variation."
    assert "HRV" in overstated(untested, evidence)[0]


def test_saying_nothing_clearly_changed_is_not_an_overstatement():
    from app.agent.verifier import overstated

    evidence = [_test_evidence("sleep_efficiency", 0.4)]
    assert overstated("Sleep efficiency did not clearly go down.", evidence) == []
    assert overstated("Sleep efficiency stayed about the same.", evidence) == []


def test_an_association_supports_both_of_its_metrics():
    from app.agent.verifier import overstated

    link = Evidence(
        tool="correlate",
        metrics=("bedtime_hour", "sleep_minutes"),
        windows=(window(0, 29),),
        n=30,
        sufficient=True,
        stats={"p_value": 0.001, "p_value_adjusted": 0.003, "rho": -0.6},
    )
    assert overstated("Later bedtimes went with less time asleep.", [link]) == []


def test_a_value_needs_evidence_that_holds_it_but_no_significance():
    from app.agent.verifier import Claim, check_claim

    evidence = _test_evidence("sleep_minutes", 0.9, "rank_days")
    claim = Claim(
        text="Your best night was Oct 13.",
        kind="value",
        evidence_ids=[evidence.id],
        metric="sleep_minutes",
    )
    reasons = check_claim(claim, {evidence.id: evidence})
    assert not any("significant" in reason or "value claim" in reason for reason in reasons)


def test_repeating_what_the_person_said_is_not_inventing_a_number():
    from app.agent.verifier import text_problems

    text = "What time did that 20 minute walk end?"
    assert text_problems(text, []) != []
    assert text_problems(text, [], "Log a 20 minute walk") == []


def test_the_app_talking_about_the_person_in_the_third_person_is_sent_back():
    from app.agent.verifier import text_problems

    assert any(
        "talks about itself" in reason
        for reason in text_problems("The person asked for water.", [])
    )
