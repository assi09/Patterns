"""What Patterns holds about the person, and their say over it: keep, reword, delete."""

import uuid
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import Field
from sqlalchemy import select

from app.agent.facts import MAX_FACT_CHARS
from app.api.auth import Db, approved_user
from app.api.errors import ApiError
from app.api.schemas import ApiModel
from app.db import memory
from app.db.models import MemoryFact, User
from app.reminders.store import utc

router = APIRouter(prefix="/memory", tags=["memory"])
Person = Annotated[User, Depends(approved_user)]


class FactOut(ApiModel):
    id: str
    kind: str
    text: str
    status: str
    start: date | None
    end: date | None
    created_at: datetime


class MemoryOut(ApiModel):
    waiting: list[FactOut]  # cards to keep or decline
    kept: list[FactOut]
    noticed: list[FactOut]  # heard once, used for nothing yet; shown so nothing is hidden


class Decision(ApiModel):
    keep: bool


class Wording(ApiModel):
    text: str = Field(min_length=1, max_length=MAX_FACT_CHARS)


def _out(row: MemoryFact) -> FactOut:
    return FactOut(
        id=str(row.id),
        kind=row.kind,
        text=row.text,
        status=row.status,
        start=row.start_day,
        end=row.end_day,
        created_at=utc(row.created_at),
    )


def _rejected(error: memory.MemoryRejected) -> ApiError:
    return ApiError(422, "invalid_request", str(error))


@router.get("", response_model=MemoryOut)
def get_memory(db: Db, user: Person) -> MemoryOut:
    rows = list(
        db.scalars(
            select(MemoryFact)
            .where(MemoryFact.user_id == user.id, MemoryFact.status != "declined")
            .order_by(MemoryFact.created_at.desc())
        )
    )

    def having(status: str) -> list[FactOut]:
        return [_out(row) for row in rows if row.status == status]

    return MemoryOut(
        waiting=having("proposed"), kept=having("approved"), noticed=having("candidate")
    )


@router.post("/facts/{fact_id}/decision", response_model=FactOut)
def decide(fact_id: uuid.UUID, body: Decision, db: Db, user: Person) -> FactOut:
    try:
        return _out(memory.decide_fact(db, user.id, fact_id, body.keep))
    except memory.MemoryRejected as error:
        raise _rejected(error) from error


@router.patch("/facts/{fact_id}", response_model=FactOut)
def reword(fact_id: uuid.UUID, body: Wording, db: Db, user: Person) -> FactOut:
    try:
        return _out(memory.edit_fact(db, user.id, fact_id, body.text))
    except memory.MemoryRejected as error:
        raise _rejected(error) from error


@router.delete("/facts/{fact_id}", status_code=204)
def forget(fact_id: uuid.UUID, db: Db, user: Person) -> Response:
    try:
        memory.delete_fact(db, user.id, fact_id)
    except memory.MemoryRejected as error:
        raise ApiError(404, "not_found", str(error)) from error
    return Response(status_code=204)
