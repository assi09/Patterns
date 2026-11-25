"""HR invitations under overlapping requests, on PostgreSQL (docs/escalation.md).

Regression: two requests that each cleared the team's old invitation and then saved their own
could leave two live links, and the earlier invitee could replace the supervisor's intended HR
contact. Only the current link may change the HR contact: issuing, replacing and accepting take
turns on the team's row, and the database holds one open invitation per team.

Runs where FA_TEST_POSTGRES_URL points at a PostgreSQL server it may create databases on (CI sets
it; locally, the docker-compose one). Each run makes and drops its own database.
"""

import os
import threading
import time
import uuid
from datetime import UTC, datetime

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db.models import HrInvite, Team, User
from app.email import Email
from app.teams import hr, memberships

ADMIN_URL = os.environ.get("FA_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="FA_TEST_POSTGRES_URL is not set")
NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)
BLOCKED = 0.5  # long enough for a thread that is not waiting on a lock to have finished


class Outbox:
    def __init__(self):
        self.sent: list[Email] = []

    def send(self, email: Email) -> None:
        self.sent.append(email)


def token_in(email: Email) -> str:
    return next(w for w in email.text.split() if "/sign-up?hr=" in w).split("hr=")[1]


@pytest.fixture
def engine():
    admin = make_url(ADMIN_URL)
    name = f"hr_race_{uuid.uuid4().hex[:10]}"
    plain = admin.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(plain, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    url = admin.set(database=name).render_as_string(hide_password=False)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()
    with psycopg.connect(plain, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def seed(engine) -> uuid.UUID:
    with Session(engine) as db:
        boss = User(email="boss@example.com", status="approved", role="supervisor")
        current = User(email="hr@example.com", status="approved", role="hr")
        db.add_all([boss, current])
        db.flush()
        team = memberships.create_team(db, boss, "Design", None, NOW)
        team.hr_id = current.id
        db.commit()
        return team.id


def invite(engine, team_id, email: str, box: Outbox) -> Session:
    """Issues an invitation in a session left open, holding whatever it locked."""
    db = Session(engine)
    team = db.get(Team, team_id)
    boss = db.get(User, team.supervisor_id)
    hr.set_contact(db, team, boss, email, NOW, box, "https://app.example")
    return db


def in_thread(work):
    outcome: dict = {}

    def run():
        try:
            outcome["value"] = work()
        except ApiError as error:
            outcome["error"] = error.code

    thread = threading.Thread(target=run)
    thread.start()
    return thread, outcome


def open_invites(engine, team_id) -> list[str]:
    with Session(engine) as db:
        return list(
            db.scalars(
                select(HrInvite.email).where(
                    HrInvite.team_id == team_id, HrInvite.accepted_at.is_(None)
                )
            )
        )


def accept_as(engine, email: str, token: str):
    with Session(engine) as db:
        user = User(email=email, status="pending", role="member")
        db.add(user)
        db.flush()
        hr.accept(db, user, token, NOW)
        db.commit()


def hr_contact(engine, team_id) -> str:
    with Session(engine) as db:
        team = db.get(Team, team_id)
        return db.get(User, team.hr_id).email


@pytest.mark.parametrize("locked", [True, False])
def test_overlapping_invitations_leave_one_live_link(engine, monkeypatch, locked):
    """A's invitation is issued and not yet committed when B's arrives. With the team lock, B
    waits for A and then replaces it; without it, the one-open-invitation index refuses B. Either
    way exactly one link is live, and only it can change the HR contact."""
    if not locked:
        monkeypatch.setattr(hr, "_lock", lambda db, team_id: db.get(Team, team_id))  # no lock
    team_id = seed(engine)
    box_a, box_b = Outbox(), Outbox()
    first = invite(engine, team_id, "first@example.com", box_a)

    def second():
        with Session(engine) as db:
            team = db.get(Team, team_id)
            boss = db.get(User, team.supervisor_id)
            hr.set_contact(db, team, boss, "second@example.com", NOW, box_b, "https://app.example")
            db.commit()

    thread, outcome = in_thread(second)
    time.sleep(BLOCKED)
    assert thread.is_alive()  # B waits on A: the lock, or the index's pending row
    first.commit()
    first.close()
    thread.join(10)
    assert not thread.is_alive()

    live = open_invites(engine, team_id)
    assert len(live) == 1
    if locked:
        assert live == ["second@example.com"] and "error" not in outcome
        stale, current = token_in(box_a.sent[0]), token_in(box_b.sent[0])
        stale_email, current_email = "first@example.com", "second@example.com"
    else:
        assert live == ["first@example.com"] and outcome["error"] == "changed_meanwhile"
        stale, current = None, token_in(box_a.sent[0])
        current_email = "first@example.com"
    if stale:
        with pytest.raises(ApiError) as refused:
            accept_as(engine, stale_email, stale)
        assert refused.value.code == "invite_invalid"
        assert hr_contact(engine, team_id) == "hr@example.com"
    accept_as(engine, current_email, current)
    assert hr_contact(engine, team_id) == current_email


def test_an_old_link_accepted_during_a_replacement_does_not_take_the_role(engine):
    """The old link is accepted while a replacement is being issued: acceptance waits for the
    team, finds its invitation gone, and changes nothing; the current contact stays."""
    team_id = seed(engine)
    box_old, box_new = Outbox(), Outbox()
    issued = invite(engine, team_id, "old.link@example.com", box_old)
    issued.commit()
    issued.close()
    replacing = invite(engine, team_id, "new.link@example.com", box_new)

    thread, outcome = in_thread(
        lambda: accept_as(engine, "old.link@example.com", token_in(box_old.sent[0]))
    )
    time.sleep(BLOCKED)
    assert thread.is_alive()  # acceptance waits for the replacement to finish
    replacing.commit()
    replacing.close()
    thread.join(10)

    assert outcome.get("error") == "invite_invalid"
    assert hr_contact(engine, team_id) == "hr@example.com"
    assert open_invites(engine, team_id) == ["new.link@example.com"]
    accept_as(engine, "new.link@example.com", token_in(box_new.sent[0]))
    assert hr_contact(engine, team_id) == "new.link@example.com"


def test_a_removal_that_waited_on_an_acceptance_still_removes(engine):
    """Reverse order: the team has no HR contact and an open invitation. The invitee's
    acceptance holds the team; the supervisor's removal, which loaded the team (no HR contact)
    before waiting, completes after it. The removal must act on the row as it is then, so the
    final HR contact is empty, not the invitee kept by a skipped update."""
    team_id = seed(engine)
    with Session(engine) as db:
        db.get(Team, team_id).hr_id = None
        db.commit()
    box = Outbox()
    issued = invite(engine, team_id, "invitee@example.com", box)
    issued.commit()
    issued.close()

    accepting = Session(engine)
    newcomer = User(email="invitee@example.com", status="pending", role="member")
    accepting.add(newcomer)
    accepting.flush()
    hr.accept(accepting, newcomer, token_in(box.sent[0]), NOW)  # holds the team, uncommitted

    def remove():
        with Session(engine) as db:
            team = db.get(Team, team_id)  # loaded before the wait: no HR contact yet
            assert team.hr_id is None
            boss = db.get(User, team.supervisor_id)
            result = hr.set_contact(db, team, boss, None, NOW, Outbox(), "https://app.example")
            db.commit()
            return result

    thread, outcome = in_thread(remove)
    time.sleep(BLOCKED)
    assert thread.is_alive()  # the removal waits for the acceptance
    accepting.commit()
    accepting.close()
    thread.join(10)

    assert outcome.get("value") == (None, False) and "error" not in outcome
    with Session(engine) as db:
        assert db.get(Team, team_id).hr_id is None  # really removed
    assert open_invites(engine, team_id) == []
