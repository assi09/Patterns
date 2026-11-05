"""Episodes: what crosses between chats, when, and how long it lasts."""

from datetime import UTC, date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select

from app.agent.context import MemoryItem, select_memory
from app.db import chat as store
from app.db import memory
from app.db.models import Conversation, Finding, MemoryEpisode, User
from app.db.session import session_scope

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)
LATER = NOW + memory.EPISODE_IDLE + timedelta(minutes=1)


def claim(text: str, kind: str = "change", metric: str = "sleep_minutes") -> dict:
    return {"text": text, "kind": kind, "metric": metric, "evidence_ids": []}


@pytest.fixture
def engine(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    return create_engine(url)


@pytest.fixture
def person(engine):
    with session_scope(engine) as db:
        user = User(email="person@example.com", password_hash="x", status="approved")
        db.add(user)
        db.flush()
        return user.id


def chat(engine, person, claims, used=NOW, refused=False):
    with session_scope(engine) as db:
        conversation = store.create_conversation(db, person)
        store.add_question(db, person, "How is it going?", None, conversation)
        store.add_answer(
            db,
            person,
            "Here is what I found.",
            claims=claims,
            evidence=[],
            answered_by="sleep",
            routed=True,
            consulted=[],
            refused=refused,
            run_id=None,
            conversation_id=conversation.id,
        )
        conversation.updated_at = used
        return conversation.id


def episodes(engine) -> list[tuple[str, list[str]]]:
    with session_scope(engine) as db:
        return [(e.text, e.metrics) for e in db.scalars(select(MemoryEpisode))]


def run(engine, person, now=LATER) -> int:
    with session_scope(engine) as db:
        return memory.consolidate(db, person, now)


def test_a_chat_in_use_leaves_no_episode_yet(engine, person):
    chat(engine, person, [claim("Sleep dropped.")])
    assert run(engine, person, NOW + timedelta(minutes=5)) == 0


def test_an_idle_chat_leaves_one_dated_line(engine, person):
    chat(engine, person, [claim("Sleep dropped.")])
    assert run(engine, person) == 1
    assert episodes(engine) == [("Nov 5: Sleep dropped.", ["sleep_minutes"])]


def test_running_again_changes_nothing(engine, person):
    chat(engine, person, [claim("Sleep dropped.")])
    run(engine, person)
    assert run(engine, person) == 0


def test_changes_come_before_steady_notes_and_two_claims_at_most(engine, person):
    claims = [
        claim("Steps held steady.", "no_change", "steps"),
        claim("Bedtime goes with efficiency.", "association", "bedtime_hour"),
        claim("Sleep dropped.", "change"),
    ]
    chat(engine, person, claims)
    run(engine, person)
    [(text, metrics)] = episodes(engine)
    assert text == "Nov 5: Sleep dropped. Bedtime goes with efficiency."
    assert metrics == ["sleep_minutes", "bedtime_hour"]


def test_a_chat_with_nothing_verified_leaves_nothing(engine, person):
    chat(engine, person, [])
    chat(engine, person, [claim("Last night was short.", "day")])
    chat(engine, person, [claim("Sleep dropped.")], refused=True)
    assert run(engine, person) == 0


def test_what_the_person_typed_never_crosses(engine, person):
    chat(engine, person, [claim("Sleep dropped.")])
    run(engine, person)
    assert "How is it going?" not in str(episodes(engine))


def test_a_long_claim_is_left_out_rather_than_cut(engine, person):
    chat(engine, person, [claim("A" * 299), claim("Sleep dropped.")])
    run(engine, person)
    assert episodes(engine)[0][0] == "Nov 5: Sleep dropped."


def test_a_chat_used_again_is_refreshed_not_duplicated(engine, person):
    conversation = chat(engine, person, [claim("Sleep dropped.")])
    run(engine, person)
    with session_scope(engine) as db:
        row = db.get(Conversation, conversation)
        store.add_answer(
            db,
            person,
            "More.",
            claims=[claim("Sleep recovered.")],
            evidence=[],
            answered_by="sleep",
            routed=True,
            consulted=[],
            refused=False,
            run_id=None,
            conversation_id=row.id,
        )
        row.updated_at = NOW + timedelta(days=1)
    assert run(engine, person, LATER + timedelta(days=1)) == 1
    assert len(episodes(engine)) == 1 and "Nov 6: Sleep recovered." in episodes(engine)[0][0]


def test_an_edit_that_removes_every_claim_removes_the_episode(engine, person):
    conversation = chat(engine, person, [claim("Sleep dropped.")])
    run(engine, person)
    with session_scope(engine) as db:
        first = store.history(db, person, None, conversation)[0]
        store.replace_from(db, person, first.id)
        db.get(Conversation, conversation).updated_at = NOW + timedelta(days=1)
    assert run(engine, person, LATER + timedelta(days=1)) == 1
    assert episodes(engine) == []


def test_one_persons_episodes_never_reach_another(engine, person):
    chat(engine, person, [claim("Sleep dropped.")])
    run(engine, person)
    with session_scope(engine) as db:
        stranger = User(email="other@example.com", password_hash="x", status="approved")
        db.add(stranger)
        db.flush()
        assert memory.memory_items(db, stranger.id, LATER) == []


def test_old_episodes_expire(engine, person):
    chat(engine, person, [claim("Sleep dropped.")])
    run(engine, person)
    with session_scope(engine) as db:
        gone = memory.expire(db, person, NOW + timedelta(days=memory.EPISODE_DAYS + 1))
    assert gone["episodes"] == 1 and episodes(engine) == []


def test_the_background_pass_consolidates_and_expires_for_everyone(engine, person):
    chat(engine, person, [claim("Sleep dropped.")])
    with session_scope(engine) as db:
        db.add(
            Finding(
                user_id=person,
                run_id="r",
                metric="steps",
                kind="change",
                text="Old.",
                evidence_ids=[],
                window_start=date(2026, 1, 1),
                window_end=date(2026, 1, 2),
                created_at=NOW - timedelta(days=memory.FINDING_DAYS + 1),
            )
        )
    counts = memory.maintain_all(lambda: session_scope(engine), LATER)
    assert counts == {"episodes": 1, "expired": 1}


def item(name: str, start=None, end=None) -> MemoryItem:
    return MemoryItem(
        kind="episode",
        id=name,
        text=name,
        metrics=("steps",),
        created=NOW - timedelta(days=45),
        importance=0.5,
        start=start,
        end=end,
    )


def test_memory_about_recent_dates_ranks_above_the_same_memory_without_them():
    today = NOW.date()
    recent = item("recent", today - timedelta(days=10), today - timedelta(days=5))
    old = item("old", today - timedelta(days=200), today - timedelta(days=190))
    chosen = select_memory([old, item("undated"), recent], {"steps"}, NOW)
    assert chosen[0].id == "recent"
