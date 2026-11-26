"""Planned team changes: the supervisor starts one, the briefing suggests one with a reason, the
order learns from this team's results, and an ended change says how the team went during it.
Made-up teams only."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_team_agent import NOW, TODAY, client, engine, make_team, signed_in  # noqa: F401

from app.db.models import Notification, Team, TeamAction
from app.db.session import session_scope
from app.synthetic import Step
from app.teams import playbook

SLEEP_DROP = {
    "metric": "sleep_minutes",
    "kind": "concern",
    "status": "lasting",
    "evidence_id": "e_sleep",
    "text": "Time asleep has been lower for 3 weeks running.",
}


def _team(engine) -> Team:  # noqa: F811
    team_id = make_team(engine, size=5)
    with session_scope(engine) as db:
        return db.get(Team, uuid.UUID(team_id))


def _action(play: str, status: str, decided_days_ago: int = 40) -> TeamAction:
    return TeamAction(
        id=uuid.uuid4(),
        kind="challenge",
        title=play,
        body=play,
        metric="sleep_minutes",
        status=status,
        play=play,
        decided_at=NOW - timedelta(days=decided_days_ago),
    )


def test_what_went_better_comes_first_and_a_recent_decline_is_left_out():
    candidates = playbook.plays_for("stress_score")  # a meeting-free day, breaks between meetings
    better = _action("meeting_breaks", "approved")
    worse = _action("meeting_free_day", "approved")
    results = {str(better.id): "better", str(worse.id): "worse"}
    ordered = [p.id for p in playbook.rank(candidates, [better, worse], results, TODAY)]
    assert ordered == ["meeting_breaks", "meeting_free_day"]
    declined = _action("meeting_breaks", "declined", decided_days_ago=5)
    assert [p.id for p in playbook.rank(candidates, [declined], {}, TODAY)] == ["meeting_free_day"]
    old_decline = _action("meeting_breaks", "declined", decided_days_ago=40)
    assert "meeting_breaks" in [p.id for p in playbook.rank(candidates, [old_decline], {}, TODAY)]


def test_every_play_is_about_the_team_and_measurable():
    from app.analysis.team import TEAM_METRICS
    from app.teams.agent import _unsafe

    for play in playbook.PLAYS:
        assert not _unsafe(f"{play.title} {play.body}"), play.id
        assert play.fits and set(play.fits) <= set(TEAM_METRICS)


def test_a_lasting_concern_gets_one_suggestion_and_a_waiting_one_blocks_the_next(engine):  # noqa: F811
    team_id = make_team(engine, size=5)
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        action, reason = playbook.suggest(db, team, [SLEEP_DROP], [], {}, TODAY, NOW)
        assert (action.status, action.source, action.play) == (
            "proposed",
            "agent",
            "evening_boundary",
        )
        assert action.metric == "sleep_minutes" and action.starts_on == TODAY + timedelta(days=1)
        assert reason["evidence_ids"] == ["e_sleep"]
        assert playbook.suggest(db, team, [SLEEP_DROP], [], {}, TODAY, NOW) is None


def test_a_coming_event_like_a_past_dip_gets_a_change_from_its_day(engine):  # noqa: F811
    team_id = make_team(engine, size=5)
    event_day = TODAY + timedelta(days=10)
    warning = {
        "text": "Release 2.0 is on ...",
        "evidence_ids": ["e_coming", "e_past", "e_dip"],
        "on": event_day,
        "note": "Release 2.0",
        "concerns": ["recovery_score"],
    }
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        action, reason = playbook.suggest(db, team, [], [warning], {}, TODAY, NOW)
        assert action.starts_on == event_day and action.metric == "recovery_score"
        assert reason["why"] == "before Release 2.0"


def test_nothing_is_suggested_without_a_reason(engine):  # noqa: F811
    team_id = make_team(engine, size=5)
    new_drop = {**SLEEP_DROP, "status": "new"}
    better = {**SLEEP_DROP, "kind": "improvement"}
    with session_scope(engine) as db:
        team = db.get(Team, uuid.UUID(team_id))
        assert playbook.suggest(db, team, [new_drop, better], [], {}, TODAY, NOW) is None
        assert db.scalars(select(TeamAction)).all() == []


# The API


def test_the_supervisor_starts_a_change_and_every_member_is_told(engine, client):  # noqa: F811
    client, _ = client
    team_id = make_team(engine)
    boss = signed_in(client, engine, "boss@example.com")
    plays = client.get(f"/teams/{team_id}/playbook", headers=boss).json()
    assert [p["id"] for p in plays] == [p.id for p in playbook.PLAYS]
    made = client.post(f"/teams/{team_id}/actions", headers=boss, json={"play": "evening_boundary"})
    assert made.status_code == 201
    body = made.json()
    assert body["membersTold"] == 7
    action = body["action"]
    assert (action["status"], action["source"], action["play"]) == (
        "approved",
        "supervisor",
        "evening_boundary",
    )
    assert (
        action["startsOn"] == str(TODAY + timedelta(days=1)) and action["metric"] == "sleep_minutes"
    )
    with session_scope(engine) as db:
        told = db.scalars(select(Notification).where(Notification.kind == "team_challenge")).all()
        assert len(told) == 7 and all("Evening boundary" in n.title for n in told)


def test_a_change_of_their_own_is_checked_like_a_note(engine, client):  # noqa: F811
    client, _ = client
    team_id = make_team(engine)
    boss = signed_in(client, engine, "boss@example.com")
    own = {
        "play": "custom",
        "title": "Fridays end at 4",
        "body": "The team finishes at 4 pm on Fridays.",
        "metric": "stress_score",
        "days": 21,
    }
    made = client.post(f"/teams/{team_id}/actions", headers=boss, json=own)
    assert made.status_code == 201 and made.json()["action"]["play"] == "custom"
    started = TODAY + timedelta(days=1)
    assert made.json()["action"]["endsOn"] == str(started + timedelta(days=20))


@pytest.mark.parametrize(
    "sent, code",
    [
        ({"play": "custom", "title": "Fridays end at 4"}, "bad_change"),
        (
            {
                "play": "custom",
                "title": "Rest",
                "body": "Lighter days for Sarah",
                "metric": "strain",
            },
            "unsafe_change",
        ),
        (
            {"play": "custom", "title": "Rest", "body": "member03 works less", "metric": "strain"},
            "unsafe_change",
        ),
        (
            {
                "play": "custom",
                "title": "Rest",
                "body": "Everyone sees a doctor",
                "metric": "strain",
            },
            "unsafe_change",
        ),
        ({"play": "nap_pods"}, "bad_change"),
        ({"play": "meeting_free_day", "metric": "weight"}, "bad_change"),
        ({"play": "meeting_free_day", "startsOn": str(TODAY - timedelta(days=1))}, "bad_start"),
        ({"play": "meeting_free_day", "startsOn": str(TODAY + timedelta(days=90))}, "bad_start"),
    ],
)
def test_a_change_that_cannot_be_planned_says_why(engine, client, sent, code):  # noqa: F811
    client, _ = client
    team_id = make_team(engine)
    boss = signed_in(client, engine, "boss@example.com")
    refused = client.post(f"/teams/{team_id}/actions", headers=boss, json=sent)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == code
    with session_scope(engine) as db:
        assert db.scalars(select(TeamAction)).all() == []


def test_too_long_a_change_is_refused(engine, client):  # noqa: F811
    client, _ = client
    team_id = make_team(engine)
    boss = signed_in(client, engine, "boss@example.com")
    refused = client.post(
        f"/teams/{team_id}/actions", headers=boss, json={"play": "step_goal", "days": 60}
    )
    assert refused.status_code == 422


def test_only_the_teams_supervisor_plans_its_changes(engine, client):  # noqa: F811
    client, _ = client
    team_id = make_team(engine)
    from app.db.models import User

    with session_scope(engine) as db:
        db.add(User(email="other@example.com", status="approved", role="supervisor"))
    stranger = signed_in(client, engine, "other@example.com")
    member = signed_in(client, engine, "member00@example.com")
    plan = {"play": "meeting_free_day"}
    assert client.post(f"/teams/{team_id}/actions", headers=stranger, json=plan).status_code == 404
    assert client.post(f"/teams/{team_id}/actions", headers=member, json=plan).status_code == 403
    assert client.get(f"/teams/{team_id}/playbook", headers=member).status_code == 403


@pytest.mark.parametrize("effect, verdict", [(60.0, "better"), (0.0, "no_change")])
def test_an_ended_change_says_how_the_team_went_during_it(engine, client, effect, verdict):  # noqa: F811
    client, _ = client
    began = TODAY - timedelta(days=30)
    effects = (Step("sleep_minutes", began, effect),) if effect else ()
    team_id = make_team(engine, effects=effects)
    with session_scope(engine) as db:
        db.add(
            TeamAction(
                team_id=uuid.UUID(team_id),
                kind="challenge",
                title="No meetings after 5 pm",
                body="No team meetings or calls after 5 pm on working days.",
                metric="sleep_minutes",
                starts_on=began,
                ends_on=began + timedelta(days=13),
                status="approved",
                source="supervisor",
                play="no_late_meetings",
                proposed_at=NOW - timedelta(days=31),
                decided_at=NOW - timedelta(days=31),
            )
        )
    boss = signed_in(client, engine, "boss@example.com")
    (action,) = client.get(f"/teams/{team_id}/actions", headers=boss).json()
    assert action["result"]["verdict"] == verdict
    assert action["result"]["evidence"]["tool"] == "team_change"
    if verdict == "better":
        assert "Time asleep rose during it" in action["result"]["text"]


def test_a_change_still_running_has_no_result_yet(engine, client):  # noqa: F811
    client, _ = client
    team_id = make_team(engine)
    boss = signed_in(client, engine, "boss@example.com")
    client.post(f"/teams/{team_id}/actions", headers=boss, json={"play": "step_goal"})
    (action,) = client.get(f"/teams/{team_id}/actions", headers=boss).json()
    assert action["result"] is None
