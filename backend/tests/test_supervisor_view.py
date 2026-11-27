# ruff: noqa: F811 (the fixtures imported from test_coach)
"""One team week for the supervisor's screen and MCP (app.teams.view, docs/supervisor-workflow.md):
each finding with its own dates and coverage, evidence opened only through its own team's report,
calendar states that never read missing as zero, and a change followed up as it stood then."""

import json
import uuid
from datetime import timedelta

import pandas as pd
import pytest
from sqlalchemy import select
from test_coach import (  # noqa: F401
    BUSY,
    NOW,
    TODAY,
    WEEK,
    engine,
    give_calendars,
    make_team,
    run,
)
from test_mcp import build as build_mcp
from test_mcp import call as call_mcp

from app.db.daily import save_daily
from app.db.models import Team, TeamAction, TeamNote, TeamReport, User
from app.db.session import session_scope
from app.harness import tools
from app.harness.tools import HarnessError
from app.sync import calendar
from app.teams import memberships, outcome, reports, view


def team_of(db, team_id: str) -> Team:
    return db.get(Team, uuid.UUID(team_id))


def boss(db) -> User:
    return db.scalar(select(User).where(User.email == "boss@example.com"))


def reported(engine, size: int = 7) -> str:
    """A team with the week's Fitbit report made at NOW, right after its members joined."""
    team_id = make_team(engine, size=size)
    with session_scope(engine) as db:
        reports.build_report(db, team_of(db, team_id), WEEK, NOW)
    return team_id


def ready(engine, size: int = 7) -> str:
    """A team whose time asleep fell three weeks before the report and stayed low, reported."""
    team_id = make_team(engine, size=size)
    run(engine, team_id, [])
    return team_id


# The week, as one call answers it


def test_a_sustained_finding_carries_its_own_baseline_and_coverage(engine):
    team_id = ready(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        report = db.scalar(select(TeamReport).where(TeamReport.team_id == team.id))
        out = view.overview(db, team, WEEK.start, TODAY)
        [found] = out["priorities"]
        record = report.evidence[found["evidence_id"]]
    assert out["report"]["state"] == "findings"
    assert out["report"]["week"] == {"start": str(WEEK.start), "end": str(WEEK.end)}
    assert found["label"] == "Sustained change" and found["direction"] == "lower"
    assert found["change"]["unit"] == "min" and found["change"]["value"] < 0
    assert found["baseline"] == record["windows"][1]  # the scan's fixed baseline, not the week's
    assert found["target"]["end"] == str(WEEK.end) and found["weeks_running"] >= 2
    assert found["contributors"] == 7 and found["roster"] == 7
    weekly = out["this_week_vs_previous_four"]
    assert weekly["label"] == "This week vs. the previous four weeks"
    assert weekly["baseline"] == {
        "start": str(WEEK.start - timedelta(days=28)),
        "end": str(WEEK.start - timedelta(days=1)),
    }
    assert "reportable metrics changed this week vs. the previous four weeks" in weekly["summary"]


def test_nothing_free_text_or_per_person_reaches_the_overview(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        db.add(
            TeamNote(
                team_id=uuid.UUID(team_id),
                text="Offsite in Lisbon, ask Dana about it",
                starts_on=WEEK.start,
                ends_on=WEEK.end,
                created_at=NOW,
            )
        )
    run(engine, team_id, [])
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        report = db.scalar(select(TeamReport).where(TeamReport.team_id == team.id))
        assert "Lisbon" in json.dumps(report.body)  # the stored sentence carries the note
        text = json.dumps(view.overview(db, team, None, TODAY))
        record = view.finding_evidence(
            db, team, str(report.id), report.body["priorities"][0]["evidence_id"]
        )
    assert "Lisbon" not in text and "Dana" not in text
    for key in ("q1", "q3", "change_q1", "member", "@example.com"):
        assert key not in text and key not in json.dumps(record)


def test_a_week_without_a_report_says_so_and_substitutes_none(engine):
    team_id = ready(engine)
    with session_scope(engine) as db:
        out = view.overview(db, team_of(db, team_id), WEEK.start - timedelta(days=70), TODAY)
    assert out["report"]["state"] == "no_report" and out["priorities"] == []
    assert str(WEEK.start) not in json.dumps(out)


def test_a_withheld_week_gives_its_reason_and_no_figure(engine):
    team_id = make_team(engine, size=3)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        reports.build_report(db, team, WEEK, NOW)
        out = view.overview(db, team, WEEK.start, TODAY)
    assert out["report"]["state"] == "withheld"
    assert "3 of the 5 people needed" in out["report"]["reason"]
    assert "this_week_vs_previous_four" not in out and out["priorities"] == []


def test_a_quiet_week_is_ready_with_no_priority_and_says_what_was_reportable(engine):
    team_id = make_team(engine, effects=())
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        reports.build_report(db, team, WEEK, NOW)
        out = view.overview(db, team, WEEK.start, TODAY)
    assert out["report"]["state"] == "no_priority_finding"
    assert out["report"]["status"] == "ready"
    weekly = out["this_week_vs_previous_four"]
    assert weekly["steady"] and len(weekly["steady"]) + len(weekly["withheld_metrics"]) >= 5


def test_a_week_asked_for_mixes_in_nothing_current(engine):
    team_id = ready(engine)
    with session_scope(engine) as db:
        supervisor = boss(db)
        asked = tools.team_overview(db, supervisor, team_id, TODAY, str(WEEK.start))
        latest = tools.team_overview(db, supervisor, team_id, TODAY)
    for key in ("readings", "open_alerts", "weekly_report"):
        assert key not in asked
        assert key in latest  # kept for callers of the first version
    with pytest.raises(HarnessError, match="date like"), session_scope(engine) as db:
        tools.team_overview(db, boss(db), team_id, TODAY, "last week")


# Evidence, opened only through its own team's report


def test_evidence_opens_only_through_the_report_that_cites_it(engine):
    team_id = ready(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        earlier = reports.build_report(
            db, team, reports.week_of(WEEK.start - timedelta(days=7)), NOW
        )
        report = db.scalar(
            select(TeamReport).where(
                TeamReport.team_id == team.id, TeamReport.week_start == WEEK.start
            )
        )
        evidence_id = report.body["priorities"][0]["evidence_id"]
        record = view.finding_evidence(db, team, str(report.id), evidence_id)
        assert record["label"] == "Sustained change"
        assert record["baseline"] == report.evidence[evidence_id]["windows"][1]
        assert record["scanned"] == report.evidence[evidence_id]["windows"][0]
        finding = view.overview(db, team, WEEK.start, TODAY)["priorities"][0]
        assert record["target"] == finding["target"]  # the weeks it held, as the screen says
        assert record["coverage"]["roster"] == 7 and record["limitations"]
        section_id = report.body["sections"][0]["evidence_id"]
        weekly = view.finding_evidence(db, team, str(report.id), section_id)
        assert weekly["label"] == "This week vs. the previous four weeks"
        for report_id, key in (
            (str(earlier.id), evidence_id),  # the right team, the wrong report
            (str(report.id), "000000000000"),  # a guessed id
            ("not-a-uuid", evidence_id),
            (str(uuid.uuid4()), evidence_id),
        ):
            with pytest.raises(view.NotFound):
                view.finding_evidence(db, team, report_id, key)
        # Another team cannot reach this report by its id.
        stranger = memberships.create_team(db, boss(db), "Other", None, NOW)
        with pytest.raises(view.NotFound):
            view.finding_evidence(db, stranger, str(report.id), evidence_id)


def test_through_mcp_another_supervisor_learns_nothing(engine):
    team_id = ready(engine)
    with session_scope(engine) as db:
        intruder = User(email="intruder@example.com", status="approved", role="supervisor")
        db.add(intruder)
        db.flush()
        intruder_id, boss_id = intruder.id, boss(db).id
        report = db.scalar(select(TeamReport).where(TeamReport.team_id == uuid.UUID(team_id)))
        report_id, evidence_id = str(report.id), report.body["priorities"][0]["evidence_id"]
    server = build_mcp(engine)
    args = {"team_id": team_id, "report_id": report_id, "evidence_id": evidence_id}
    failed, text = call_mcp(server, intruder_id, "team_finding_evidence", **args)
    assert failed and "No such team" in text and "min" not in text
    failed, found = call_mcp(server, boss_id, "team_finding_evidence", **args)
    assert not failed and found["evidence_id"] == evidence_id
    failed, text = call_mcp(server, boss_id, "team_finding_evidence", **args | {"evidence_id": "x"})
    assert failed and "No such evidence" in text
    failed, week = call_mcp(server, boss_id, "team_overview", team_id=team_id, week=str(WEEK.end))
    assert not failed and week["report"]["week"]["start"] == str(WEEK.start)


# The calendar, for the asked week only


def zero_calendar(engine, count: int) -> None:
    """Synced calendars with no meetings at all: observed zeros, not gaps."""
    days = pd.date_range(TODAY - timedelta(days=90), TODAY - timedelta(days=1), freq="D")
    metrics = ("meeting_minutes", "meetings", "after_hours_minutes", "back_to_back")
    frame = pd.DataFrame({m: 0.0 for m in (*metrics, "focus_minutes", "out_of_office")}, index=days)
    with session_scope(engine) as db:
        people = db.scalars(select(User).where(User.email.like("member%")).order_by(User.email))
        for person in list(people)[:count]:
            save_daily(db, person.id, calendar.SOURCE, frame)


@pytest.mark.parametrize(
    "setup, state",
    [
        (lambda e: None, "unavailable"),  # nobody synced: missing, never zero
        (lambda e: give_calendars(e, 3, None), "below_minimum"),
        (lambda e: give_calendars(e, 7, None), "observed"),  # enough, and no clear change
        (lambda e: zero_calendar(e, 7), "observed"),  # synced and empty: an observed zero
    ],
)
def test_the_calendar_state_is_said_and_missing_is_never_zero(engine, setup, state):
    team_id = reported(engine)  # the week's report, as the Monday job makes it
    setup(engine)
    with session_scope(engine) as db:
        out = view.meeting_load(db, team_of(db, team_id), WEEK.start, TODAY)
    assert out["state"] == state
    assert out["week"]["start"] == str(WEEK.start)
    assert out["baseline"]["end"] == str(WEEK.start - timedelta(days=1))
    assert "missing" in out["definition"] and "Scheduled meeting time" in out["definition"]
    if state == "unavailable":
        assert out["figures"] == [] and "median" not in json.dumps(out)
    if state == "observed":
        assert out["clear_changes"] == []
        [time] = [f for f in out["figures"] if f["metric"] == "meeting_minutes"]
        assert time["label"] == "Scheduled meeting time" and "q1_week" not in time


def test_an_observed_zero_is_reported_as_zero(engine):
    team_id = reported(engine)  # the week's report, as the Monday job makes it
    zero_calendar(engine, 7)
    with session_scope(engine) as db:
        out = view.meeting_load(db, team_of(db, team_id), WEEK.start, TODAY)
    [time] = [f for f in out["figures"] if f["metric"] == "meeting_minutes"]
    assert time["median_week"] == 0 and time["contributors"] == 7


def test_a_busy_week_is_a_clear_change_and_another_week_is_not_borrowed(engine):
    team_id = reported(engine)  # the week's report, as the Monday job makes it
    give_calendars(engine, 7, BUSY)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        busy = view.meeting_load(db, team, WEEK.start, TODAY)
        before = view.meeting_load(db, team, WEEK.start - timedelta(days=7), TODAY)
        current = view.meeting_load(db, team, TODAY, TODAY)
    assert {"metric": "meeting_minutes", "direction": "higher", "heavier_load": True} in busy[
        "clear_changes"
    ]
    assert before["week"]["start"] == str(WEEK.start - timedelta(days=7))
    # No report that week, and everyone joined after it: no group then, so no figures borrowed.
    assert before["cohort"]["counted"] == 0 and before["cohort"]["joined_later"] == 7
    assert before["state"] == "unavailable" and before["figures"] == []
    assert current["state"] == "week_not_over" and "figures" not in current


# A change, followed up as it stood then


def test_a_change_is_in_progress_in_its_week_and_measured_once_a_report_covers_it(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        db.add(
            TeamAction(
                team_id=team.id,
                kind="challenge",
                title="No meetings after 5 pm",
                body="No team meetings or calls after 5 pm on working days.",
                metric="sleep_minutes",
                starts_on=WEEK.start - timedelta(days=14),
                ends_on=WEEK.end,
                status="approved",
                source="supervisor",
                proposed_at=NOW - timedelta(days=20),
                decided_at=NOW - timedelta(days=20),
            )
        )
        db.flush()
        during = reports.week_of(WEEK.start - timedelta(days=7))
        reports.build_report(db, team, during, NOW - timedelta(days=7))
        reports.build_report(db, team, WEEK, NOW)
        then = view.overview(db, team, during.start, TODAY)
        now = view.overview(db, team, None, TODAY)
        [past] = then["follow_up"]
        [latest] = now["follow_up"]
        assert past["state"] == "in_progress" and "result" not in past
        assert past["as_of"] == str(during.end + timedelta(days=1))
        assert latest["state"] == "ended" and latest["result"]["report_id"]
        assert latest["tried"] and outcome.CONTRIBUTION in latest["result"]["caveats"]
        assert latest["result"]["reference"]["kind"] == "before_the_change"  # not linked
        assert outcome.REBOUND in latest["result"]["caveats"]
        assert latest["result"]["outcome"] in outcome.OUTCOMES and "verdict" not in latest["result"]
        record = view.finding_evidence(
            db, team, latest["result"]["report_id"], latest["result"]["evidence_id"]
        )
    assert record["label"] == "Result of a team change"
    assert record["outcome_label"] == outcome.OUTCOMES[record["outcome"]]
    assert record["target"] == {"start": str(WEEK.start - timedelta(days=14)), "end": str(WEEK.end)}


# The app reads the same representation


def api_client(engine, email: str):
    from fastapi.testclient import TestClient

    from app.api import auth
    from app.api.main import create_app
    from app.auth import accounts

    app = create_app()

    def db():
        with session_scope(engine) as session:
            yield session

    app.dependency_overrides[auth.get_db] = db
    app.dependency_overrides[auth.now] = lambda: NOW
    client = TestClient(app)
    with session_scope(engine) as session:
        person = session.scalar(select(User).where(User.email == email))
        accounts.set_password(session, person, "correct horse battery")
    token = client.post(
        "/auth/login", json={"email": email, "password": "correct horse battery"}
    ).json()["token"]
    return client, {"Authorization": f"Bearer {token}"}


def test_the_screen_gets_labelled_findings_and_opens_their_evidence(engine):
    team_id = ready(engine)
    with session_scope(engine) as db:
        db.add(User(email="intruder@example.com", status="approved", role="supervisor"))
    client, headers = api_client(engine, "boss@example.com")
    report = client.get(f"/teams/{team_id}/reports/{WEEK.start}", headers=headers).json()
    [found] = report["findings"]
    assert found["label"] == "Sustained change" and found["baseline"]["start"]
    assert report["weekly"]["label"] == "This week vs. the previous four weeks"
    assert "reportable metrics changed this week" in report["weekly"]["summary"]
    url = f"/teams/{team_id}/reports/{WEEK.start}/evidence"
    opened = client.get(f"{url}/{found['evidenceId']}", headers=headers)
    assert opened.status_code == 200
    body = opened.json()
    assert body["label"] == "Sustained change" and body["baseline"] == found["baseline"]
    assert body["coverage"]["roster"] == 7 and body["limitations"]
    missing = client.get(f"{url}/000000000000", headers=headers)
    assert missing.status_code == 404
    other_week = f"/teams/{team_id}/reports/{WEEK.start - timedelta(days=70)}/evidence"
    assert client.get(f"{other_week}/{found['evidenceId']}", headers=headers).status_code == 404
    stranger, theirs = api_client(engine, "intruder@example.com")
    refused = stranger.get(f"{url}/{found['evidenceId']}", headers=theirs)
    assert refused.status_code in (403, 404) and "min" not in refused.text


def test_a_withheld_report_has_no_findings_and_no_evidence_to_open(engine):
    team_id = make_team(engine, size=3)
    with session_scope(engine) as db:
        reports.build_report(db, team_of(db, team_id), WEEK, NOW)
    client, headers = api_client(engine, "boss@example.com")
    report = client.get(f"/teams/{team_id}/reports/{WEEK.start}", headers=headers).json()
    assert report["findings"] == [] and report["weekly"] is None and report["evidence"] == {}


# Review round, 2026-11-27: free text, the week's own group, and lighter weeks


def test_no_free_text_title_or_stored_sentence_reaches_mcp(engine):
    """A supervisor's own change title and an alert's stored sentence can name someone (#246):
    neither the latest nor a dated answer carries them, only controlled labels."""
    from app.db.models import TeamAlert

    team_id = ready(engine)
    secret = "Dana migraine"
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        db.add(
            TeamAction(
                team_id=team.id,
                kind="challenge",
                title=f"Quiet mornings for {secret}",
                body=f"Because of {secret}.",
                metric="sleep_minutes",
                starts_on=WEEK.start - timedelta(days=14),
                ends_on=WEEK.end,
                status="approved",
                source="supervisor",
                play="custom",
                proposed_at=NOW - timedelta(days=20),
                decided_at=NOW - timedelta(days=20),
            )
        )
        db.add(
            TeamAlert(
                team_id=team.id,
                metric="sleep_minutes",
                direction="down",
                kind="concern",
                text=f"Time asleep fell. It lined up with your note: {secret} (Oct 20).",
                evidence={},
                raised_at=NOW,
            )
        )
        db.flush()
        report = db.scalar(select(TeamReport).where(TeamReport.team_id == team.id))
        report.headline = f"Needs attention: {secret}"  # as if a stored sentence carried it
        latest = tools.team_overview(db, boss(db), team_id, TODAY)
        dated = tools.team_overview(db, boss(db), team_id, TODAY, str(WEEK.start))
    for answer in (latest, dated):
        text = json.dumps(answer)
        assert "Dana" not in text and "migraine" not in text
        assert "Custom team change" in text
    assert latest["open_alerts"] == [f"Time asleep lower across the team (raised {NOW:%b %-d})"]
    assert latest["weekly_report"]["headline"] == "Sustained change: Time asleep lower"


def test_a_past_weeks_calendar_counts_the_reports_group_still_in_the_team(engine):
    from app.db.models import TeamMembership

    team_id = ready(engine)  # the week's Fitbit report, made on NOW from the 7 members
    give_calendars(engine, 7, BUSY)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        before = view.meeting_load(db, team, WEEK.start, TODAY)
        # After the report: one member left, and someone with a full calendar history joined.
        leaver = db.scalars(select(TeamMembership).where(TeamMembership.team_id == team.id)).first()
        leaver.left_at = NOW + timedelta(days=1)
        newcomer = User(email="member99@example.com", status="approved")
        db.add(newcomer)
        db.flush()
        from test_coach import calendar_days

        save_daily(db, newcomer.id, calendar.SOURCE, calendar_days(99, BUSY))
        memberships.join(db, team, newcomer, NOW + timedelta(days=1))
        after = view.meeting_load(db, team, WEEK.start, TODAY)
    assert before["cohort"]["same_group_as_report"] is True
    assert before["coverage"]["roster"] == 7
    assert after["cohort"] | {"rule": ""} == {
        "rule": "",
        "basis": "the members when that week's report was made",
        "group_as_of": NOW.isoformat(),
        "counted": 6,
        "joined_later": 1,
        "left_since": 1,
        "same_group_as_report": False,
    }
    [time] = [f for f in after["figures"] if f["metric"] == "meeting_minutes"]
    assert time["contributors"] == 6  # neither the newcomer nor the leaver
    assert any(
        "1 of the people in that week's Fitbit report have left" in line
        for line in after["limitations"]
    )


@pytest.mark.parametrize(
    "busy, expected, heavier",
    [
        ({"meeting_minutes": 90.0}, "higher", True),
        ({"meeting_minutes": -100.0}, "lower", False),  # a lighter week is not "none"
        (None, "none", False),
    ],
)
def test_a_clear_change_is_named_in_either_direction(engine, busy, expected, heavier):
    team_id = reported(engine)  # the week's report, as the Monday job makes it
    give_calendars(engine, 7, busy)
    with session_scope(engine) as db:
        out = view.meeting_load(db, team_of(db, team_id), WEEK.start, TODAY)
    [time] = [f for f in out["figures"] if f["metric"] == "meeting_minutes"]
    assert time["clear_change"] == expected
    assert time["heavier_load"] is heavier
    [meetings] = [f for f in out["figures"] if f["metric"] == "meetings"]
    assert meetings["clear_change"] == "not judged" and meetings["heavier_load"] is None


def test_an_observed_zero_week_is_no_change_not_a_fall(engine):
    team_id = reported(engine)  # the week's report, as the Monday job makes it
    zero_calendar(engine, 7)
    with session_scope(engine) as db:
        out = view.meeting_load(db, team_of(db, team_id), WEEK.start, TODAY)
    [time] = [f for f in out["figures"] if f["metric"] == "meeting_minutes"]
    assert time["median_week"] == 0 and time["clear_change"] == "none"


def test_a_same_day_joiner_cannot_lift_a_withheld_calendar_figure_over_the_minimum(engine):
    """Four calendars at the moment of the report; a fifth person with calendar history joins
    later that day. The historical figure must stay withheld: a date comparison would have
    counted them, made five and shown a figure the report's group cannot support."""
    team_id = ready(engine)  # the report, made at NOW
    give_calendars(engine, 4, BUSY)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        newcomer = User(email="member99@example.com", status="approved")
        db.add(newcomer)
        db.flush()
        from test_coach import calendar_days

        save_daily(db, newcomer.id, calendar.SOURCE, calendar_days(99, BUSY))
        memberships.join(db, team, newcomer, NOW + timedelta(hours=7))  # the same day, later
        out = view.meeting_load(db, team, WEEK.start, TODAY)
    assert out["state"] == "below_minimum"
    assert out["cohort"]["joined_later"] == 1 and out["cohort"]["same_group_as_report"] is True
    assert all(f["contributors"] == 4 and "median_week" not in f for f in out["figures"])


def test_someone_who_left_before_the_report_that_day_is_not_said_to_have_left_after(engine):
    from app.db.models import TeamMembership

    team_id = make_team(engine)  # joined at NOW
    give_calendars(engine, 7, BUSY)
    made = NOW + timedelta(hours=8)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        leaver = db.scalars(select(TeamMembership).where(TeamMembership.team_id == team.id)).first()
        leaver.left_at = NOW + timedelta(hours=7)  # left that morning, before the report
        db.flush()
        reports.build_report(db, team, WEEK, made)
        out = view.meeting_load(db, team, WEEK.start, TODAY)
    assert out["cohort"]["left_since"] == 0 and out["cohort"]["counted"] == 6
    assert out["cohort"]["same_group_as_report"] is True
    assert not any("have left since" in line for line in out["limitations"])


def test_a_week_without_a_report_says_whose_calendars_it_used(engine):
    team_id = make_team(engine)
    give_calendars(engine, 7, BUSY)
    with session_scope(engine) as db:
        out = view.meeting_load(db, team_of(db, team_id), WEEK.start, TODAY)
    assert out["cohort"]["basis"].startswith("no report for that week")
    assert out["cohort"]["same_group_as_report"] is False
    assert "No Fitbit report for that week to match." in out["limitations"]
