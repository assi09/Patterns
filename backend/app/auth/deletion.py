"""Deleting an account and everything held about the person.

Every table with a person's data points at `users.id` with `ON DELETE CASCADE` (or `SET NULL` for
the anonymous team log), so deleting the user row removes it all in one statement. The tables are
found from the models rather than listed by hand, so a table added later is covered too, and the
rows are counted again afterwards: if any remain, the deletion is rolled back instead of leaving a
half-deleted person.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import Column, Table, delete, func, select
from sqlalchemy.orm import Session

from app.db.models import Base, Team, TeamMembership, User


class DeletionError(Exception):
    """The account could not be fully deleted; nothing was changed."""


@dataclass(frozen=True)
class Deletion:
    email: str
    rows: dict[str, int]  # table -> rows that pointed at the person and were deleted
    teams_closed: list[str]  # names of the teams they supervised, deleted with them


def _references() -> list[tuple[Table, Column, str | None]]:
    """Every column that points at `users.id`, with its `ondelete` rule."""
    found = []
    for table in Base.metadata.sorted_tables:
        for key in table.foreign_keys:
            if key.column.table.name == User.__tablename__:
                found.append((table, key.parent, key.ondelete))
    return found


def held(session: Session, user_id: uuid.UUID) -> dict[str, int]:
    """Rows that point at the person, by table (only tables with any)."""
    counts: dict[str, int] = {}
    for table, column, _ in _references():
        n = session.scalar(select(func.count()).select_from(table).where(column == user_id)) or 0
        if n:
            counts[table.name] = counts.get(table.name, 0) + n
    return counts


def teams_supervised(session: Session, user_id: uuid.UUID) -> list[Team]:
    return list(session.scalars(select(Team).where(Team.supervisor_id == user_id)))


def delete_account(session: Session, user: User) -> Deletion:
    """Deletes the person and everything that points at them, then checks nothing is left.

    The caller commits. Raises `DeletionError` (after which the caller must roll back) when a row
    survives, for example on SQLite without `PRAGMA foreign_keys=ON`.
    """
    user_id, email = user.id, user.email
    before = held(session, user_id)
    teams = teams_supervised(session, user_id)
    team_ids = [t.id for t in teams]
    session.execute(delete(User).where(User.id == user_id))
    session.flush()
    session.expunge_all()  # objects loaded before now may describe deleted rows

    # SET NULL rows (the team log's "someone joined") no longer match the id, so anything that
    # still does is a row the cascade missed.
    left = held(session, user_id)
    if session.get(User, user_id) is not None:
        left["users"] = 1
    if team_ids:
        orphans = session.scalar(
            select(func.count())
            .select_from(TeamMembership)
            .where(TeamMembership.team_id.in_(team_ids))
        )
        if orphans:
            left["team_memberships (of their teams)"] = orphans
    if left:
        raise DeletionError(f"rows still held after deleting {email}: {left}")
    return Deletion(email=email, rows=before, teams_closed=sorted(t.name for t in teams))
