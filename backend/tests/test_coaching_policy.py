"""Coaching on everyday habits is allowed, grounded in the person's own evidence; medical is not."""

from datetime import date

import pytest

from app.agent.guard import INSTRUCTIONS
from app.agent.router import CRITERIA, OUT_OF_SCOPE, KeywordRouter
from app.agent.verifier import Claim, check_claim
from app.analysis.evidence import Evidence, Window

WINDOW = Window(start=date(2026, 9, 1), end=date(2026, 9, 28))


def evidence(tool="correlate", p=0.01, metrics=("bedtime_hour", "sleep_efficiency"), **stats):
    return Evidence(
        tool=tool,
        metrics=metrics,
        windows=(WINDOW,),
        n=28,
        sufficient=True,
        stats={"p_value": p, "rho": -0.5, **stats},
    )


def suggestion(text, ids, metric="sleep_efficiency"):
    return Claim(text=text, kind="suggestion", evidence_ids=ids, metric=metric)


def test_a_grounded_suggestion_worded_as_an_option_passes():
    e = evidence()
    text = "On nights you were in bed earlier, sleep efficiency went with it; you could try that."
    assert check_claim(suggestion(text, [e.id]), {e.id: e}) == []


def test_a_suggestion_without_a_real_pattern_is_refused():
    e = evidence(p=0.4)
    reasons = check_claim(suggestion("You could try going to bed earlier.", [e.id]), {e.id: e})
    assert any("specific to this person" in r for r in reasons)


@pytest.mark.parametrize(
    "text, problem",
    [
        ("You should go to bed earlier to sleep better.", "do not order"),
        ("Going to bed earlier will fix your sleep efficiency.", "option"),
    ],
)
def test_a_suggestion_is_an_option_never_an_order(text, problem):
    e = evidence()
    reasons = check_claim(suggestion(text, [e.id]), {e.id: e})
    assert any(problem in r for r in reasons)


def test_coaching_is_in_scope_and_medical_is_not():
    assert "improving their everyday habits" in CRITERIA[OUT_OF_SCOPE]
    assert "supplements" in CRITERIA[OUT_OF_SCOPE] and "doctor" in CRITERIA[OUT_OF_SCOPE]
    assert KeywordRouter().classify("How can I sleep better?").top != OUT_OF_SCOPE
    assert (
        KeywordRouter().classify("Should I see a doctor about my heart rate?").top == OUT_OF_SCOPE
    )


def test_the_guard_allows_habits_and_flags_medical():
    assert "suggesting an everyday habit are not medical" in INSTRUCTIONS
    for word in ("medication", "supplements", "diet", "doctor", "condition"):
        assert word in INSTRUCTIONS
