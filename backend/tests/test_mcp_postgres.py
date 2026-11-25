"""Approving what a harness sent, under two taps at once, on PostgreSQL (docs/mcp.md): the send is
locked while it is decided, so it applies once. Runs where FA_TEST_POSTGRES_URL is set."""

import threading
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_hr_invite_postgres import ADMIN_URL, engine  # noqa: F401 (the fixture)

from app.api.errors import ApiError
from app.db.models import HarnessSubmission, Team, TeamNote, User
from app.harness import approvals
from app.teams import memberships

pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="FA_TEST_POSTGRES_URL is not set")
NOW = datetime(2026, 11, 26, 9, tzinfo=UTC)


def test_two_approvals_at_once_apply_a_team_event_once(engine):  # noqa: F811
    with Session(engine) as db:
        boss = User(email="boss@example.com", status="approved", role="supervisor")
        db.add(boss)
        db.flush()
        team = memberships.create_team(db, boss, "Design", None, NOW)
        sent = HarnessSubmission(
            user_id=boss.id,
            team_id=team.id,
            kind="team_event",
            payload={"title": "Launch", "starts_on": "2026-11-27"},
            status="pending",
            created_at=NOW,
        )
        db.add(sent)
        db.commit()
        boss_id, sent_id = boss.id, str(sent.id)

    first = Session(engine)
    approvals.approve(first, first.get(User, boss_id), sent_id, NOW)  # holds the send, uncommitted
    outcome: dict = {}

    def second():
        with Session(engine) as db:
            try:
                approvals.approve(db, db.get(User, boss_id), sent_id, NOW)
                db.commit()
                outcome["applied"] = True
            except ApiError as error:
                outcome["error"] = error.code

    thread = threading.Thread(target=second)
    thread.start()
    thread.join(0.5)
    assert thread.is_alive()  # the second tap waits for the first
    first.commit()
    first.close()
    thread.join(10)

    assert outcome == {"error": "already_decided"}
    with Session(engine) as db:
        assert len(db.scalars(select(TeamNote)).all()) == 1
        assert db.scalar(select(HarnessSubmission.status)) == "approved"
        assert db.scalar(select(Team.name)) == "Design"
