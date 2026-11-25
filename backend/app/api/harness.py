"""Connecting a harness (docs/mcp.md): personal tokens for the MCP server, and approving what a
harness sent. A token is shown once; what a harness sends changes nothing until approved here."""

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import Field

from app.api.auth import Db, Now, approved_user
from app.api.schemas import ApiModel
from app.db.models import AccessToken, HarnessSubmission, User
from app.harness import approvals, tokens

router = APIRouter(tags=["harness"])
Person = Annotated[User, Depends(approved_user)]


class NewToken(ApiModel):
    name: str = Field(min_length=1, max_length=60)  # "Claude Code on my laptop"


class TokenOut(ApiModel):
    id: str
    name: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class MadeToken(TokenOut):
    token: str  # shown once, never again


class SubmissionOut(ApiModel):
    id: str
    kind: Literal["calendar_days", "team_event"]
    status: Literal["pending", "approved", "declined"]
    payload: dict[str, Any]
    team_id: str | None
    created_at: datetime


def _token(row: AccessToken) -> TokenOut:
    return TokenOut(
        id=str(row.id),
        name=row.name,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
    )


def _submission(row: HarnessSubmission) -> SubmissionOut:
    return SubmissionOut(
        id=str(row.id),
        kind=row.kind,
        status=row.status,
        payload=row.payload,
        team_id=str(row.team_id) if row.team_id else None,
        created_at=row.created_at,
    )


@router.post("/me/tokens", response_model=MadeToken, status_code=201)
def make_token(body: NewToken, db: Db, clock: Now, user: Person) -> MadeToken:
    row, token = tokens.make(db, user, body.name, clock)
    return MadeToken(**_token(row).model_dump(), token=token)


@router.get("/me/tokens", response_model=list[TokenOut])
def list_tokens(db: Db, user: Person) -> list[TokenOut]:
    return [_token(row) for row in tokens.listing(db, user)]


@router.delete("/me/tokens/{token_id}", status_code=204)
def revoke_token(token_id: str, db: Db, clock: Now, user: Person) -> Response:
    tokens.revoke(db, user, token_id, clock)
    return Response(status_code=204)


@router.get("/me/harness", response_model=list[SubmissionOut])
def waiting(db: Db, user: Person) -> list[SubmissionOut]:
    """What a harness sent that waits for this person's approval."""
    return [_submission(row) for row in approvals.pending(db, user)]


@router.post("/me/harness/{submission_id}/approve", response_model=SubmissionOut)
def approve(submission_id: str, db: Db, clock: Now, user: Person) -> SubmissionOut:
    return _submission(approvals.approve(db, user, submission_id, clock))


@router.post("/me/harness/{submission_id}/decline", response_model=SubmissionOut)
def decline(submission_id: str, db: Db, clock: Now, user: Person) -> SubmissionOut:
    return _submission(approvals.decline(db, user, submission_id, clock))
