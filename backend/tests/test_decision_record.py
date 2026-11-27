# ruff: noqa: F811 (the fixtures imported from test_coach)
"""A decision recorded through MCP (docs/change-memory.md): a pending draft only the app can
confirm, idempotent on the caller's request id, linked only to what the supervisor named, tracked
only when asked, and whether the team tried it kept apart from approval."""

import asyncio
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from test_coach import NOW, TODAY, WEEK, engine, make_team  # noqa: F401
from test_mcp import build as build_mcp
from test_mcp import call as call_mcp
from test_supervisor_view import api_client, boss, reported, team_of

from app.db.models import Notification, TeamAction, TeamNote, User
from app.db.session import session_scope
from app.harness import tools
from app.harness.tools import HarnessError, TeamChangeIn
from app.teams import actions as team_actions
from app.teams import playbook, view

TOKEN = uuid.uuid4()


def record(db, team_id: str, user=None, now=NOW, today=TODAY, **change) -> dict:
    fields = {"request_id": "req-evening-1", "play": "evening_boundary"}
    fields |= {"starts_on": today + timedelta(days=3)} | change
    fields.setdefault("ends_on", fields["starts_on"] + timedelta(days=13))
    return tools.record_team_change(
        db, user or boss(db), team_id, TeamChangeIn(**fields), TOKEN, now, today
    )


def drafts(db, team_id: str) -> list[TeamAction]:
    team = team_of(db, team_id)
    return db.scalars(select(TeamAction).where(TeamAction.team_id == team.id)).all()


def notified(db) -> int:
    return db.scalar(select(func.count()).select_from(Notification))


def test_a_recorded_change_waits_for_the_app_and_tells_nobody(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        out = record(db, team_id)
        [action] = drafts(db, team_id)
        assert notified(db) == 0
    assert out["status"] == "pending" and out["members_notified"] == 0
    assert out["shown_in_app"] == "Suggested in chat — awaiting your confirmation"
    assert out["title"] == playbook.PLAY["evening_boundary"].title
    assert out["tracking"] is None and out["linked_event_id"] is None
    assert (action.status, action.source, action.token_id) == ("proposed", "assistant", TOKEN)
    assert action.metric is None and action.comparison is None  # not tracked, never measured
    assert action.ends_on == TODAY + timedelta(days=16)  # the end it was given
    assert action.implementation is None


def test_a_retry_returns_the_same_record_and_a_reused_id_is_refused(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        first = record(db, team_id)
        again = record(db, team_id)
        assert len(drafts(db, team_id)) == 1
        with pytest.raises(HarnessError, match="already used for a different change"):
            record(db, team_id, play="meeting_free_day")
    assert again["change_id"] == first["change_id"] and again["repeat"] is True


def test_a_retry_racing_the_first_returns_the_first(engine, monkeypatch):
    """Two calls with one request_id at once: the second meets the unique request id when it
    writes, and returns the record the first one made instead of an error."""
    team_id = make_team(engine)
    with session_scope(engine) as db:
        first = record(db, team_id)
    real = tools._repeat
    calls = []

    def unseen_once(db, team, change, ends_on):
        calls.append(1)
        return None if len(calls) == 1 else real(db, team, change, ends_on)

    monkeypatch.setattr(tools, "_repeat", unseen_once)
    with session_scope(engine) as db:
        again = record(db, team_id)
        assert len(drafts(db, team_id)) == 1
    assert again["change_id"] == first["change_id"] and len(calls) == 2


@pytest.mark.parametrize(
    "change, refused",
    [
        ({"play": "custom"}, "Only a playbook change"),
        ({"play": "four_day_week"}, "Only a playbook change"),
        ({"starts_on": TODAY - timedelta(days=1)}, "starts_on"),
        ({"starts_on": TODAY + timedelta(days=61)}, "starts_on"),
        ({"ends_on": TODAY + timedelta(days=2)}, "ends_on"),  # before it starts
        ({"ends_on": TODAY + timedelta(days=70)}, "ends_on"),
        ({"event_id": str(uuid.uuid4())}, "event_id"),
        ({"finding": {"report_id": str(uuid.uuid4()), "evidence_id": "abc"}}, "finding"),
        (
            {"tracking": {"metric": "mood", "observe_from": TODAY, "observe_to": TODAY}},
            "tracking.metric",
        ),
        (
            {
                "tracking": {
                    "metric": "sleep_minutes",
                    "observe_from": TODAY - timedelta(days=7),  # an outcome already seen
                    "observe_to": TODAY,
                }
            },
            "chosen before any outcome exists",
        ),
    ],
)
def test_a_bad_record_is_refused_naming_its_field_and_stores_nothing(engine, change, refused):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        with pytest.raises(HarnessError, match=refused):
            record(db, team_id, **change)
        assert drafts(db, team_id) == []


def test_only_the_teams_own_supervisor_can_record(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        other = User(email="other@example.com", status="approved", role="supervisor")
        member = db.scalar(select(User).where(User.role == "member"))
        db.add(other)
        db.flush()
        for who in (other, member):
            with pytest.raises(HarnessError):
                record(db, team_id, user=who)
        assert drafts(db, team_id) == []


def test_links_are_only_to_the_teams_own_event_and_finding(engine):
    team_id = reported(engine)
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        event = TeamNote(team_id=team.id, text="Release", starts_on=TODAY, category="deadline")
        db.add(event)
        db.flush()
        overview = view.overview(db, team, WEEK.start, TODAY)
        line = (overview["this_week_vs_previous_four"]["changed"] or [None])[0] or (
            overview["this_week_vs_previous_four"]["steady"][0]
        )
        finding = {"report_id": overview["report"]["report_id"], "evidence_id": line["evidence_id"]}
        out = record(db, team_id, event_id=str(event.id), finding=finding)
        [action] = drafts(db, team_id)
    assert out["linked_event_id"] == str(event.id)
    assert out["linked_finding"] == finding
    assert action.finding_evidence_id == finding["evidence_id"]


def test_a_tracked_change_is_observed_only_and_never_measured_against_the_28_days(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        tracking = {
            "metric": "sleep_minutes",
            "observe_from": TODAY + timedelta(days=4),
            "observe_to": TODAY + timedelta(days=4),  # the first night only
        }
        out = record(db, team_id, tracking=tracking, ends_on=TODAY + timedelta(days=5))
        team = team_of(db, team_id)
        [action] = drafts(db, team_id)
        team_actions.decide(db, team, action, True, NOW)
        later = TODAY + timedelta(days=30)
        assert playbook.results_of(db, team, later) == {}
        [followed] = view.follow_up(db, team, later)
    assert out["tracking"]["comparison"] == "observation only"
    assert action.comparison == "observation_only" and action.metric == "sleep_minutes"
    assert followed["state"] == "ended" and "result" not in followed


def test_whether_it_was_tried_is_the_supervisors_report_and_known_only_from_then(engine):
    team_id = make_team(engine)
    client, auth = api_client(engine, "boss@example.com")
    with session_scope(engine) as db:
        record(db, team_id, starts_on=TODAY)
        [action] = drafts(db, team_id)
        action_id = str(action.id)
    url = f"/teams/{team_id}/actions/{action_id}/implementation"
    refused = client.put(url, json={"tried": True}, headers=auth)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "not_approved"
    listed = client.get(f"/teams/{team_id}/actions", headers=auth).json()
    assert listed[0]["source"] == "assistant" and listed[0]["implementation"] is None
    approved = client.post(f"/teams/{team_id}/actions/{action_id}/approve", headers=auth)
    assert approved.status_code == 200
    marked = client.put(url, json={"tried": True}, headers=auth).json()
    assert marked["implementation"] == "tried" and marked["implementationAt"]
    with session_scope(engine) as db:
        team = team_of(db, team_id)
        [action] = drafts(db, team_id)
        action.implementation_at = NOW + timedelta(days=5)  # marked on day 5 of the change
        db.flush()
        [then] = view.follow_up(db, team, TODAY + timedelta(days=2))
        [later] = view.follow_up(db, team, TODAY + timedelta(days=6))
    assert then["state"] == "in_progress"
    assert then["tried"] == "not reported: whether the team tried it is unknown"  # not yet marked
    assert later["tried"] == "reported tried by the supervisor"
    cleared = client.put(url, json={"tried": None}, headers=auth).json()
    assert cleared["implementation"] is None


def test_a_one_day_decision_keeps_its_one_day_and_needs_its_end_stated(engine):
    """'Keep Thursday evening free', saved without tracking: no length is picked for it."""
    team_id = make_team(engine)
    server = build_mcp(engine)
    with session_scope(engine) as db:
        boss_id = boss(db).id
    today = date.today()
    thursday = today + timedelta(days=(3 - today.weekday()) % 7 or 7)
    change = {"request_id": "thursday-0001", "play": "evening_boundary", "starts_on": str(thursday)}
    error, text = call_mcp(server, boss_id, "record_team_change", team_id=team_id, change=change)
    assert error and "ends_on" in text
    with session_scope(engine) as db:
        assert drafts(db, team_id) == []
    change["ends_on"] = str(thursday)
    for _ in range(2):  # saved, then retried
        error, out = call_mcp(server, boss_id, "record_team_change", team_id=team_id, change=change)
        assert not error and (out["starts_on"], out["ends_on"]) == (str(thursday), str(thursday))
    client, auth = api_client(engine, "boss@example.com")
    [listed] = client.get(f"/teams/{team_id}/actions", headers=auth).json()
    assert (listed["startsOn"], listed["endsOn"]) == (str(thursday), str(thursday))
    assert listed["status"] == "proposed" and listed["metric"] is None


def test_an_approved_change_is_unknown_until_reported(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        record(db, team_id, starts_on=TODAY)
        team = team_of(db, team_id)
        [action] = drafts(db, team_id)
        team_actions.decide(db, team, action, True, NOW)
        [followed] = view.follow_up(db, team, TODAY + timedelta(days=20))
    assert followed["state"] == "ended"
    assert followed["tried"] == "not reported: whether the team tried it is unknown"


def test_a_change_not_started_cannot_be_marked(engine):
    team_id = make_team(engine)
    client, auth = api_client(engine, "boss@example.com")
    with session_scope(engine) as db:
        record(db, team_id)  # starts in three days
        [action] = drafts(db, team_id)
        team_actions.decide(db, team_of(db, team_id), action, True, NOW)
        action_id = str(action.id)
    response = client.put(
        f"/teams/{team_id}/actions/{action_id}/implementation", json={"tried": False}, headers=auth
    )
    assert response.status_code == 409 and response.json()["error"]["code"] == "not_started"


# Through the MCP server itself


def test_mcp_records_a_draft_and_offers_no_way_to_decide_it(engine):
    team_id = make_team(engine)
    server = build_mcp(engine)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert "record_team_change" in names
    for verb in ("approve", "decline", "decide", "delete", "edit", "tried", "implement"):
        assert not any(verb in name for name in names), verb
    with session_scope(engine) as db:
        boss_id = boss(db).id
    today = date.today()
    change = {"request_id": "mcp-req-0001", "play": "meeting_free_day"}
    change |= {"starts_on": str(today), "ends_on": str(today)}
    error, out = call_mcp(server, boss_id, "record_team_change", team_id=team_id, change=change)
    error2, again = call_mcp(server, boss_id, "record_team_change", team_id=team_id, change=change)
    assert not error and not error2 and out["status"] == "pending"
    assert again["change_id"] == out["change_id"]
    smuggled = change | {"request_id": "mcp-req-0002", "status": "approved"}
    error, text = call_mcp(server, boss_id, "record_team_change", team_id=team_id, change=smuggled)
    assert error  # extra fields are refused by the schema
    with session_scope(engine) as db:
        assert [a.status for a in drafts(db, team_id)] == ["proposed"]
        assert notified(db) == 0


def test_mcp_refuses_another_supervisors_team_as_no_such_team(engine):
    team_id = make_team(engine)
    server = build_mcp(engine)
    with session_scope(engine) as db:
        other = User(email="other@example.com", status="approved", role="supervisor")
        db.add(other)
        db.flush()
        other_id = other.id
    change = {"request_id": "mcp-req-0003", "play": "step_goal"}
    change |= {"starts_on": str(date.today()), "ends_on": str(date.today())}
    error, text = call_mcp(server, other_id, "record_team_change", team_id=team_id, change=change)
    assert error and "No such team" in text


def test_an_event_category_survives_approval(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        boss_user = boss(db)
        event = tools.TeamEventIn(title="Release", starts_on=TODAY, category="deadline")
        held = tools.send_team_event(db, boss_user, team_id, event, TOKEN, NOW)
        from app.harness import approvals

        approvals.approve(db, boss_user, held["submission_id"], NOW)
        note = db.scalar(select(TeamNote))
    assert note.category == "deadline"


def test_a_change_title_is_never_free_text_through_mcp(engine):
    team_id = make_team(engine)
    with session_scope(engine) as db:
        out = record(db, team_id)
    assert out["title"] in {p.title for p in playbook.PLAYS}
    with session_scope(engine) as db:
        [action] = drafts(db, team_id)
        action.title = "Quiet mornings for Dana"  # as if edited in the app
        db.flush()
        assert view.action_title(action) == out["title"]
