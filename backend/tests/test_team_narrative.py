"""The model-written prose of a team report: what passes its checks, and the fallback."""

import json
from datetime import date, timedelta

import pytest

from app.agent.llm import LLMError, ScriptedLLM
from app.analysis.report import change_text
from app.analysis.team import team_statistics, week_of
from app.synthetic import Step, generate
from app.teams import narrative
from app.teams.narrative import WRITE, narrate

WEEK = week_of(date(2026, 10, 19))


@pytest.fixture(scope="module")
def statistics():
    start = WEEK.start - timedelta(days=70)
    drop = (Step("sleep_minutes", WEEK.start, -70),)
    return team_statistics([generate(start, 77, drop, seed=s).frame for s in range(8)], WEEK)


def by_metric(statistics, metric: str):
    return next(e for e in statistics.changes if e.metrics == (metric,))


def report(paragraphs: list[dict], headline: str = "The team slept less this week."):
    return ScriptedLLM.call(WRITE, headline=headline, paragraphs=paragraphs)


def sleep_paragraph(statistics, **changes) -> dict:
    sleep = by_metric(statistics, "sleep_minutes")
    stats = sleep.stats
    text = (
        f"Time asleep fell across the team: median change "
        f"{change_text('sleep_minutes', stats['median_change'])}, with {stats['members_down']} "
        f"of {stats['members']} people lower."
    )
    return {
        "text": text,
        "kind": "change",
        "metric": "sleep_minutes",
        "direction": "down",
        "evidence_ids": [sleep.id],
    } | changes


def other_changes(statistics) -> list[dict]:
    """A plain paragraph for each change found besides sleep (the drop moves recovery too)."""
    paragraphs = []
    for evidence in statistics.changed:
        metric = evidence.metrics[0]
        if metric == "sleep_minutes":
            continue
        down = evidence.stats["median_change"] < 0
        paragraphs.append(
            {
                "text": f"{narrative.team_info(metric).label} {'fell' if down else 'rose'} across "
                "the team.",
                "kind": "change",
                "metric": metric,
                "direction": "down" if down else "up",
                "evidence_ids": [evidence.id],
            }
        )
    return paragraphs


def steady_paragraph(statistics, metric: str = "steps") -> dict:
    evidence = by_metric(statistics, metric)
    return {
        "text": "Steps showed no clear change for the team.",
        "kind": "no_change",
        "metric": metric,
        "evidence_ids": [evidence.id],
    }


def test_the_model_sees_only_aggregates(statistics):
    items = narrative.payload(statistics)
    text = json.dumps(items)
    assert {i["metric"] for i in items} >= {"sleep_minutes", "steps"}
    assert "member_id" not in text and "@" not in text
    sleep = next(i for i in items if i["metric"] == "sleep_minutes" and i["kind"] == "team_change")
    assert sleep["changed"] is True and sleep["median_change"].endswith("min")


def test_a_report_that_matches_its_evidence_is_kept(statistics):
    paragraphs = [sleep_paragraph(statistics), *other_changes(statistics)]
    llm = ScriptedLLM([report([*paragraphs, steady_paragraph(statistics)])])
    attempt = narrate(llm, statistics, cap_usd=0.02)
    assert attempt.narrated is not None, attempt.problems
    assert attempt.narrated.headline == "The team slept less this week."
    assert len(llm.requests) == 1
    assert "never see or mention any individual" in llm.requests[0]["messages"][0]["content"]


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"direction": "up"}, "does not point up"),
        ({"text": "Time asleep fell by 99 min."}, "numbers not found"),
        ({"text": "One member slept far less, which pulled the team down."}, "individuals"),
        ({"text": "Time asleep fell because of deadlines."}, "causation"),
        ({"evidence_ids": ["000000000000"]}, "does not exist"),
    ],
)
def test_a_wrong_paragraph_is_sent_back_once_then_dropped(statistics, change, problem):
    wrong = report([sleep_paragraph(statistics, **change)])
    llm = ScriptedLLM([wrong, wrong])
    attempt = narrate(llm, statistics, cap_usd=0.02)
    assert attempt.narrated is None
    assert any(problem in p for p in attempt.problems), attempt.problems
    assert len(llm.requests) == 2  # the report and one repair round
    repair = llm.requests[1]["messages"][-1]["content"]
    assert problem.split()[0] in repair


def test_a_repaired_report_is_kept(statistics):
    wrong = report([sleep_paragraph(statistics, direction="up")])
    right = report([sleep_paragraph(statistics), *other_changes(statistics)])
    attempt = narrate(ScriptedLLM([wrong, right]), statistics, cap_usd=0.02)
    assert attempt.narrated is not None


def test_a_change_that_was_not_found_cannot_be_reported(statistics):
    steps = by_metric(statistics, "steps")
    assert steps not in statistics.changed
    invented = {
        "text": "Steps rose across the team.",
        "kind": "change",
        "metric": "steps",
        "direction": "up",
        "evidence_ids": [steps.id],
    }
    problems = narrative.check(
        narrative.TeamNarrative(
            headline="A week of change.",
            paragraphs=[sleep_paragraph(statistics), *other_changes(statistics), invented],
        ),
        statistics,
    )
    assert any("did not find" in p for p in problems)


def test_every_change_found_must_be_covered(statistics):
    problems = narrative.check(
        narrative.TeamNarrative(
            headline="A quiet week.", paragraphs=[steady_paragraph(statistics)]
        ),
        statistics,
    )
    assert any("leaves out changes" in p and "Time asleep" in p for p in problems)


def test_no_change_cannot_be_said_of_a_change(statistics):
    claimed = steady_paragraph(statistics, "sleep_minutes") | {
        "text": "Time asleep showed no clear change."
    }
    problems = narrative.check(
        narrative.TeamNarrative(
            headline="A week.", paragraphs=[sleep_paragraph(statistics), claimed]
        ),
        statistics,
    )
    assert any("found one" in p for p in problems)


def test_model_errors_and_unusable_answers_fall_back(statistics):
    class Failing:
        def complete(self, messages, **kwargs):
            raise LLMError("OpenAI took too long to answer.")

    attempt = narrate(Failing(), statistics, cap_usd=0.02)
    assert attempt.narrated is None and "too long" in attempt.problems[0]
    prose = ScriptedLLM([ScriptedLLM.say("Here is your report."), ScriptedLLM.say("Again.")])
    assert narrate(prose, statistics, cap_usd=0.02).narrated is None
    malformed = ScriptedLLM([ScriptedLLM.call(WRITE, headline="x"), ScriptedLLM.call(WRITE)])
    attempt = narrate(malformed, statistics, cap_usd=0.02)
    assert attempt.narrated is None and "form" in attempt.problems[0]
    assert "paragraphs" in attempt.problems[0]  # says what is wrong, so it can be fixed


def test_a_label_written_where_the_key_belongs_is_read_as_the_key(statistics):
    labeled = sleep_paragraph(statistics, metric="Time asleep")
    paragraphs = [labeled, *other_changes(statistics)]
    assert (
        narrative.check(
            narrative.TeamNarrative(headline="A week.", paragraphs=paragraphs), statistics
        )
        == []
    )
    unknown = sleep_paragraph(statistics, metric="naps")
    problems = narrative.check(
        narrative.TeamNarrative(
            headline="A week.", paragraphs=[unknown, *other_changes(statistics)]
        ),
        statistics,
    )
    assert any("metric must be one of" in p and "sleep_minutes" in p for p in problems)


def test_the_form_limits_metrics_to_the_weeks_keys(statistics):
    tool = narrative._tool(["sleep_minutes", "steps"])
    paragraph = tool["function"]["parameters"]["$defs"]["Paragraph"]
    assert paragraph["properties"]["metric"]["enum"] == ["sleep_minutes", "steps"]
