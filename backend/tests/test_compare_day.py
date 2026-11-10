from datetime import date, timedelta

import pandas as pd
import pytest

from app.agent.agent import AgentResult
from app.agent.experts import carry_consulted
from app.agent.guard import GuardError, Judgement
from app.agent.verifier import Claim, check_claim, overstated, text_problems
from app.analysis.day import MIN_USUAL_DAYS, USUAL_DAYS, compare_day
from app.analysis.evidence import Evidence, ToolError, Window

START = date(2026, 7, 1)
DAY = START + timedelta(days=USUAL_DAYS)


def frame(last: float, before: list[float] | None = None) -> pd.DataFrame:
    values = [*(before or [float(v) for v in range(55, 55 + USUAL_DAYS)]), last]
    return pd.DataFrame({"resting_hr": values}, index=pd.date_range(START, periods=len(values)))


@pytest.mark.parametrize(("last", "position"), [(90.0, "above"), (50.0, "below"), (68.0, "within")])
def test_a_day_is_placed_against_the_middle_half_of_the_weeks_before(last, position):
    evidence = compare_day(frame(last), "resting_hr", DAY)
    assert evidence.tool == "compare_day" and evidence.sufficient
    assert evidence.stats["position"] == position and evidence.stats["value"] == last
    assert (evidence.stats["usual_low"], evidence.stats["usual_high"]) == (61.75, 75.25)
    assert evidence.windows[0] == Window(start=DAY, end=DAY)
    assert evidence.windows[1] == Window(start=START, end=DAY - timedelta(days=1))


def test_without_enough_days_or_a_value_it_is_not_sufficient():
    short = frame(60.0, [60.0] * (MIN_USUAL_DAYS - 1))
    day = START + timedelta(days=MIN_USUAL_DAYS - 1)
    assert compare_day(short, "resting_hr", day).sufficient  # the value alone can be stated
    assert "position" not in compare_day(short, "resting_hr", day).stats
    assert not compare_day(frame(float("nan")), "resting_hr", DAY).sufficient
    with pytest.raises(ToolError):
        compare_day(frame(60.0), "made_up", DAY)
    with pytest.raises(ToolError):
        compare_day(frame(60.0), "resting_hr", DAY + timedelta(days=5))


def day_evidence(position: str) -> dict[str, Evidence]:
    last = {"above": 90.0, "below": 50.0, "within": 68.0}[position]
    evidence = compare_day(frame(last), "resting_hr", DAY)
    return {evidence.id: evidence}


def day_claim(evidence: dict[str, Evidence], text: str, direction=None) -> Claim:
    return Claim(
        text=text,
        kind="day",
        evidence_ids=list(evidence),
        metric="resting_hr",
        direction=direction,
    )


def test_day_claims_must_match_where_the_day_sits():
    above = day_evidence("above")
    assert (
        check_claim(day_claim(above, "Resting heart rate is higher than usual today.", "up"), above)
        == []
    )
    assert check_claim(day_claim(above, "Resting heart rate was 90 bpm today.", "up"), above) == []
    wrong = check_claim(day_claim(above, "Resting heart rate is lower today.", "down"), above)
    assert any("above the usual range" in r for r in wrong)
    within = day_evidence("within")
    assert check_claim(day_claim(within, "Resting heart rate is in its usual range."), within) == []
    assert check_claim(day_claim(within, "Resting heart rate is up today.", "up"), within)


def test_day_claims_need_compare_day_evidence():
    other = Evidence(
        tool="describe",
        metrics=("resting_hr",),
        windows=(Window(start=START, end=DAY),),
        n=29,
        sufficient=True,
        stats={"mean": 60.0},
    )
    reasons = check_claim(day_claim({other.id: other}, "Higher today.", "up"), {other.id: other})
    assert any("must cite compare_day" in r for r in reasons)


def test_a_summary_may_say_today_is_above_usual_when_compare_day_shows_it():
    summary = "Your resting heart rate is higher than usual today."
    assert overstated(summary, list(day_evidence("above").values())) == []
    assert overstated(summary, list(day_evidence("within").values()))


class Guard:
    def __init__(self, *words, fail=False):
        self.words, self.fail = words, fail

    def judge(self, texts):
        if self.fail:
            raise GuardError("down")
        flags = tuple(any(w in t for w in self.words) for t in texts)
        return Judgement(flagged=flags, probabilities=tuple(0.0 for _ in flags))


def sleep_claim(evidence_id="ev_sleep", text="Time asleep did not clearly change."):
    return Claim(text=text, kind="no_change", evidence_ids=[evidence_id], metric="sleep_minutes")


def lead(summary: str, cited: str = "ev_hrv") -> AgentResult:
    result = AgentResult(run_id="run", stop_reason="submitted")
    result.summary = summary
    result.claims = [
        Claim(text="HRV did not clearly change.", kind="no_change", evidence_ids=[cited])
    ]
    return result


def test_a_consulted_experts_claims_are_carried_when_the_summary_uses_them():
    result = lead("Recovery looks steady, and your time asleep was stable too.")
    carried = carry_consulted(result, {"sleep": [sleep_claim()]}, {"ev_sleep": "sleep"}, None)
    assert carried and result.claims[-1].metric == "sleep_minutes"


def test_nothing_is_carried_when_already_cited_or_not_mentioned():
    cited = lead("Your time asleep was stable.", cited="ev_sleep")
    assert carry_consulted(cited, {"sleep": [sleep_claim()]}, {"ev_sleep": "sleep"}, None) == []
    unrelated = lead("Recovery looks steady.")
    assert carry_consulted(unrelated, {"sleep": [sleep_claim()]}, {"ev_sleep": "sleep"}, None) == []


def test_carried_claims_go_through_the_guard():
    flagged = sleep_claim(text="Time asleep is low, see a doctor.")
    result = lead("Your time asleep was stable.")
    assert carry_consulted(result, {"sleep": [flagged]}, {}, Guard("doctor")) == []
    down = lead("Your time asleep was stable.")
    assert carry_consulted(down, {"sleep": [sleep_claim()]}, {}, Guard(fail=True))


def test_a_day_without_a_value_says_which_earlier_day_has_one():
    evidence = compare_day(frame(float("nan")), "resting_hr", DAY)
    assert evidence.stats["latest_day_with_value"] == (DAY - timedelta(days=1)).isoformat()


def test_a_day_with_no_usual_range_can_be_stated_but_not_placed():
    short = frame(60.0, [60.0] * (MIN_USUAL_DAYS - 1))
    day = START + timedelta(days=MIN_USUAL_DAYS - 1)
    evidence = compare_day(short, "resting_hr", day)
    said = {evidence.id: evidence}
    value = Claim(
        text="Your resting heart rate was 60 bpm.",
        kind="value",
        metric="resting_hr",
        evidence_ids=[evidence.id],
    )
    placed = Claim(
        text="Your resting heart rate was within your usual range.",
        kind="day",
        metric="resting_hr",
        evidence_ids=[evidence.id],
    )
    assert check_claim(value, said) == []
    assert any("usual range" in r for r in check_claim(placed, said))


def test_a_date_with_no_year_stands_if_either_year_fits():
    window = Window(start=date(2021, 12, 20), end=date(2022, 1, 22))
    evidence = Evidence(
        tool="describe", metrics=("steps",), windows=(window,), n=30, sufficient=True, stats={}
    )
    assert not any("dates" in r for r in text_problems("From Dec 20 to Jan 22.", [evidence]))
    assert any("dates" in r for r in text_problems("On Mar 3 it rose.", [evidence]))
