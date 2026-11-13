"""Deleting an account removes everything held about the person, and only that."""

import builtins
from datetime import UTC, date, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.agent.facts import FACT_KINDS
from app.auth import __main__ as cli
from app.auth.deletion import DeletionError, delete_account, held
from app.db.models import (
    AnswerTrace,
    ChatMessage,
    CheckIn,
    Conversation,
    DailyMetric,
    MemoryFact,
    Spend,
    Team,
    TeamEvent,
    TeamMembership,
    User,
)
from app.teams import memberships

NOW = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)


def _upgraded(tmp_path) -> str:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return url


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(_upgraded(tmp_path))

    # SQLite enforces ON DELETE CASCADE only with foreign keys on; Postgres always does.
    @event.listens_for(engine, "connect")
    def _fk(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


def _person(session: Session, email: str) -> User:
    user = User(email=email, status="approved")
    session.add(user)
    session.flush()
    return user


def _fill(session: Session, user: User) -> None:
    """Made-up rows in the tables a tester fills: metrics, chat, trace, spend, memory, check-in."""
    session.add(
        DailyMetric(
            user_id=user.id,
            source="google_health",
            day=date(2026, 11, 1),
            metric="steps",
            value=1234.0,
        )
    )
    session.add(CheckIn(user_id=user.id, day=date(2026, 11, 1), rating=3))
    chat = Conversation(user_id=user.id)
    session.add(chat)
    session.flush()
    question = ChatMessage(
        user_id=user.id, role="user", text="How did I sleep?", conversation_id=chat.id
    )
    answer = ChatMessage(
        user_id=user.id, role="assistant", text="About the same.", conversation_id=chat.id
    )
    session.add_all([question, answer])
    session.flush()
    session.add(
        AnswerTrace(message_id=answer.id, outcome="answered", stop_reason="answered", latency_ms=10)
    )
    session.add(Spend(user_id=user.id, kind="answer", cost_usd=0.01))
    session.add(MemoryFact(user_id=user.id, kind=FACT_KINDS[0], text="I work night shifts"))
    session.flush()


def _count(session: Session, model, *where) -> int:
    return session.scalar(select(func.count()).select_from(model).where(*where))


def test_deletes_everything_about_the_person_and_nothing_else(session):
    gone, kept = _person(session, "gone@example.com"), _person(session, "kept@example.com")
    supervisor = _person(session, "boss@example.com")
    _fill(session, gone)
    _fill(session, kept)
    team = memberships.create_team(session, supervisor, "Night shift", None, NOW)
    memberships.join(session, team, gone, NOW)
    memberships.join(session, team, kept, NOW)
    gone_id, kept_id = gone.id, kept.id
    held_before_kept = held(session, kept_id)

    before = held(session, gone_id)
    assert before["daily_metrics"] == 1 and before["chat_messages"] == 2
    assert before["team_memberships"] == 1

    done = delete_account(session, gone)
    session.commit()

    assert done.email == "gone@example.com" and done.rows == before and done.teams_closed == []
    assert held(session, gone_id) == {}
    assert session.get(User, gone_id) is None
    assert _count(session, AnswerTrace) == 1  # only the other person's answer is left
    # The other person and the team are untouched.
    assert held(session, kept_id) == held_before_kept
    assert _count(session, TeamMembership, TeamMembership.user_id == kept_id) == 1
    assert session.get(Team, team.id) is not None
    # The team log keeps that someone joined, with no one attached.
    assert _count(session, TeamEvent, TeamEvent.event == "joined", TeamEvent.user_id.is_(None)) == 1


def test_deleting_a_supervisor_deletes_their_teams(session):
    supervisor, member = _person(session, "boss@example.com"), _person(session, "m@example.com")
    team = memberships.create_team(session, supervisor, "Lab", None, NOW)
    memberships.join(session, team, member, NOW)
    team_id, member_id = team.id, member.id

    done = delete_account(session, supervisor)
    session.commit()

    assert done.teams_closed == ["Lab"]
    assert session.get(Team, team_id) is None
    assert _count(session, TeamMembership, TeamMembership.team_id == team_id) == 0
    assert session.get(User, member_id) is not None  # the member keeps their own account


def test_refuses_and_reports_when_a_row_survives(tmp_path):
    # Without foreign keys on, SQLite ignores the cascades: the check must catch it.
    engine = create_engine(_upgraded(tmp_path))
    with Session(engine) as session:
        user = _person(session, "gone@example.com")
        _fill(session, user)
        with pytest.raises(DeletionError, match="daily_metrics"):
            delete_account(session, user)


def _run(engine, monkeypatch, argv, typed):
    monkeypatch.setattr(cli, "session_scope", lambda: _scope(engine))
    monkeypatch.setattr(builtins, "input", lambda _prompt: typed)
    return cli.main(argv)


class _scope:
    def __init__(self, engine):
        self.session = Session(engine, expire_on_commit=False)

    def __enter__(self):
        return self.session

    def __exit__(self, kind, *_):
        if kind is None:
            self.session.commit()
        self.session.close()


def test_cli_deletes_only_after_the_email_is_typed_again(engine, monkeypatch, capsys):
    with Session(engine) as session:
        user = _person(session, "gone@example.com")
        _fill(session, user)
        session.commit()
        user_id = user.id

    assert _run(engine, monkeypatch, ["delete", "gone@example.com"], "someone@else.com") == 1
    assert "Not deleted" in capsys.readouterr().err
    with Session(engine) as session:
        assert session.get(User, user_id) is not None

    assert _run(engine, monkeypatch, ["delete", "Gone@Example.com"], " GONE@example.com ") == 0
    out = capsys.readouterr().out
    assert "nothing left" in out and "How did I sleep" not in out  # counts only, no content
    with Session(engine) as session:
        assert session.get(User, user_id) is None
        assert held(session, user_id) == {}


def test_cli_unknown_email(engine, monkeypatch, capsys):
    assert _run(engine, monkeypatch, ["delete", "nobody@example.com"], "") == 1
    assert "No account" in capsys.readouterr().err
