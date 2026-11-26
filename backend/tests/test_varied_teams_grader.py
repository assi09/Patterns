"""The varied-team grader must reject a wrong finding, not only pass right ones.

Each test takes a correct finding from a real report built on made-up data, corrupts one claim
(the direction, a count, the week, the comparison period, the unit) and requires the grader to
fail that claim, and only that claim. Without these, a 149/149 score could not tell a working
grader from one that passes everything.
"""

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from app.analysis.team import week_of
from app.db.daily import save_daily
from app.db.models import Team, User
from app.db.session import session_scope
from app.synthetic import Step, generate
from app.teams import memberships, reports

sys.path.insert(0, str(Path(__file__).parents[2] / "eval"))

import varied_teams  # noqa: E402

NOW = datetime(2026, 10, 26, 9, tzinfo=UTC)
WEEK = week_of(date(2026, 10, 19))
EMAILS = {f"member{i:02d}@example.com" for i in range(8)}


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """One team of 8 with a planted three-week sleep drop: this week's report and last week's."""
    url = f"sqlite:///{tmp_path_factory.mktemp('grader') / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    engine = create_engine(url)
    effects = (Step("sleep_minutes", WEEK.start - timedelta(days=14), -70),)
    with session_scope(engine) as db:
        boss = User(email="boss@example.com", status="approved", role="supervisor")
        db.add(boss)
        db.flush()
        team = memberships.create_team(db, boss, "Design", None, NOW)
        for i in range(8):
            person = User(email=f"member{i:02d}@example.com", status="approved")
            db.add(person)
            db.flush()
            frame = generate(WEEK.start - timedelta(days=80), 87, effects, seed=i).frame
            save_daily(db, person.id, "google_health", frame)
            memberships.join(db, team, person, NOW - timedelta(days=90))
        team_id = team.id
    out = {}
    with session_scope(engine) as db:
        team = db.get(Team, team_id)
        for name, week, now in (
            ("this", WEEK, NOW),
            ("last", week_of(WEEK.start - timedelta(days=7)), NOW - timedelta(days=7)),
        ):
            report = reports.build_report(db, team, week, now)
            db.expunge(report)
            out[name] = report
    return out


def change_item(report) -> dict:
    row = next(p for p in report.body["priorities"] if p["metric"] == "sleep_minutes")
    return {
        "text": row["text"],
        "kind": "change",
        "metric": row["metric"],
        "evidence_ids": [row["evidence_id"]],
    }


def section_item(report, metric="sleep_minutes") -> dict:
    s = next(s for s in report.body["sections"] if s["metric"] == metric)
    return {
        "text": s["text"],
        "kind": "section",
        "metric": metric,
        "evidence_ids": [s["evidence_id"]],
    }


def grade(item, report, week=WEEK.start) -> dict:
    return varied_teams.check_items([item], report, EMAILS, week)


def failed_checks(result) -> set[str]:
    return {name for name, ok in result["checks"].items() if not ok}


def test_correct_findings_pass_every_claim(built):
    report = built["this"]
    change = grade(change_item(report), report)
    assert failed_checks(change) == set(), change["failed"]
    assert change["claims"] == 7 and change["claims_passed"] == 7
    for section in report.body["sections"]:
        item = section_item(report, section["metric"])
        assert failed_checks(grade(item, report)) == set(), item["text"]


def corrupt(item: dict, old: str, new: str) -> dict:
    assert old in item["text"], (old, item["text"])
    return {**item, "text": item["text"].replace(old, new, 1)}


def test_a_reversed_direction_fails(built):
    report = built["this"]
    item = change_item(report)
    figure = varied_teams.FIGURE.search(item["text"])[1]
    flipped = corrupt(corrupt(item, "lower", "higher"), figure, "+" + figure[1:])
    assert {"figure_value_sign_unit", "direction_word"} <= failed_checks(grade(flipped, report))
    # The sign alone, with the words left right, still fails.
    sign_only = corrupt(item, figure, "+" + figure[1:])
    assert failed_checks(grade(sign_only, report)) == {"figure_value_sign_unit"}
    changed = next(s for s in report.body["sections"] if s["status"] == "changed")
    section = section_item(report, changed["metric"])
    word = varied_teams.WORD.search(section["text"])[1]
    other = {"fell": "rose", "rose": "fell", "moved later": "x"}.get(word, "rose")
    assert "direction_word" in failed_checks(grade(corrupt(section, word, other), report))


def test_a_wrong_numerator_fails_even_with_the_right_denominator(built):
    report = built["this"]
    item = change_item(report)
    moved = varied_teams.MOVED.search(item["text"])
    wrong = corrupt(item, moved[0], f"({int(moved[1]) - 1} of {moved[2]} people)")
    assert failed_checks(grade(wrong, report)) == {"counts_match_fields"}
    section = section_item(report)
    split = varied_teams.SPLIT.search(section["text"])
    up, n, down = split.groups()
    swapped = split[0].replace(f"{up} of {n} higher, {down}", f"{down} of {n} higher, {up}")
    assert failed_checks(grade(corrupt(section, split[0], swapped), report)) == {
        "counts_match_fields"
    }


def test_a_finding_from_the_wrong_week_fails(built):
    this, last = built["this"], built["last"]
    # Last week's finding, graded as this week's: its record ends a week early.
    stale = change_item(last)
    assert "target_week" in failed_checks(grade(stale, last))
    # This week's finding graded for the week before.
    assert "target_week" in failed_checks(grade(change_item(this), this, WEEK.start - timedelta(7)))
    assert "target_week" in failed_checks(
        grade(section_item(this), this, WEEK.start - timedelta(7))
    )


def test_a_wrongly_named_comparison_period_fails(built):
    report = built["this"]
    item = change_item(report)
    named = varied_teams.NAMED.search(item["text"])
    old_wording = corrupt(item, named[0], "against the four weeks before")
    assert failed_checks(grade(old_wording, report)) == {"comparison_period"}
    shifted = corrupt(item, named[0], "against Sep 7 to Oct 4")
    assert failed_checks(grade(shifted, report)) == {"comparison_period"}
    unstated = corrupt(item, named[0] + " ", "")
    assert failed_checks(grade(unstated, report)) == {"comparison_period"}


def test_a_wrong_unit_streak_or_scale_fails(built):
    report = built["this"]
    item = change_item(report)
    assert "figure_value_sign_unit" in failed_checks(
        grade(corrupt(item, " min ", " steps "), report)
    )
    assert "streak" in failed_checks(
        grade(corrupt(item, "3 weeks running", "4 weeks running"), report)
    )
    figure = varied_teams.FIGURE.search(item["text"])[1]
    doubled = f"{float(figure) * 2:+.0f}"
    assert failed_checks(grade(corrupt(item, figure, doubled), report)) == {
        "figure_value_sign_unit"
    }


def test_a_figure_from_a_withheld_metric_fails(built):
    report = built["this"]
    section = section_item(report)
    record = dict(report.evidence[section["evidence_ids"][0]])
    record["stats"] = {**record["stats"], "members": 4}
    fake = type("R", (), {"evidence": {**report.evidence, section["evidence_ids"][0]: record}})()
    assert "five_or_more" in failed_checks(grade(section, fake))


def test_an_empty_briefing_checks_no_claims(built):
    result = varied_teams.check_items([], built["this"], EMAILS, WEEK.start)
    assert result["claims"] == 0 and result["items_claim_checked"] == 0
