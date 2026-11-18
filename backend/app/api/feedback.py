"""What testers write to the team from the app: a report about one answer, or feedback on a chat.

A person can point a report only at their own answers and chats. Each one is stored with a copy of
the answer it is about, and emailed to the admins so the team sees it the same day; a failed email
never loses the feedback, which stays in the database for the operations page.
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import select

from app import email as mail
from app.api.auth import Db, Now, admin_user, approved_user
from app.api.errors import ApiError
from app.api.schemas import ApiModel
from app.config import settings
from app.db.models import ChatMessage, Conversation, Feedback, User

router = APIRouter(tags=["feedback"])
logger = logging.getLogger(__name__)

Person = Annotated[User, Depends(approved_user)]
Admin = Annotated[User, Depends(admin_user)]
MAX_TEXT = 2000
QUOTE_CHARS = 1500


class FeedbackIn(ApiModel):
    kind: Literal["report", "feedback"]
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None  # a report is about one answer


class FeedbackOut(ApiModel):
    id: uuid.UUID
    kind: str
    text: str
    created_at: datetime
    quoted: str | None = None


class FeedbackRow(FeedbackOut):
    """The admin's view: who wrote it, so the team can follow up."""

    email: str


def _notify(row: Feedback, who: str) -> None:
    """Best effort: an email that fails is logged, and the feedback is kept regardless."""
    what = "Report on an answer" if row.kind == "report" else "Feedback on a chat"
    text = f"{what} from {who}:\n\n{row.text}"
    if row.quoted:
        text += f"\n\nThe answer it is about:\n{row.quoted}"
    html = "<br>".join(line.replace("&", "&amp;").replace("<", "&lt;") for line in text.split("\n"))
    try:
        mailer = mail.mailer_from_settings(settings)
        for to in settings.admin_emails:
            mailer.send(mail.Email(to=to, subject=f"[Patterns] {what}", text=text, html=html))
    except mail.MailError:
        logger.warning("Could not email new feedback")


@router.post("/feedback", response_model=FeedbackOut, status_code=201)
def send_feedback(body: FeedbackIn, db: Db, user: Person, clock: Now) -> FeedbackOut:
    text = body.text.strip()
    if not text:
        raise ApiError(422, "invalid_request", "Write a few words first.")
    conversation_id, quoted = body.conversation_id, None
    if body.message_id is not None:
        message = db.get(ChatMessage, body.message_id)
        if message is None or message.user_id != user.id:
            raise ApiError(404, "not_found", "That answer is no longer in your chats.")
        conversation_id = message.conversation_id
        quoted = message.text[:QUOTE_CHARS]
    elif conversation_id is not None:
        chat = db.get(Conversation, conversation_id)
        if chat is None or chat.user_id != user.id:
            raise ApiError(404, "not_found", "That chat is no longer in your chats.")
    row = Feedback(
        user_id=user.id,
        kind=body.kind,
        text=text,
        conversation_id=conversation_id,
        message_id=body.message_id,
        quoted=quoted,
        created_at=clock,
    )
    db.add(row)
    db.flush()
    _notify(row, user.email)
    return FeedbackOut(
        id=row.id, kind=row.kind, text=row.text, created_at=row.created_at, quoted=row.quoted
    )


@router.get("/admin/feedback", response_model=list[FeedbackRow])
def list_feedback(db: Db, _: Admin) -> list[FeedbackRow]:
    """The latest feedback, newest first, for the operations page."""
    rows = db.execute(
        select(Feedback, User.email)
        .join(User, User.id == Feedback.user_id)
        .order_by(Feedback.created_at.desc())
        .limit(100)
    ).all()
    return [
        FeedbackRow(
            id=f.id,
            kind=f.kind,
            text=f.text,
            created_at=f.created_at,
            quoted=f.quoted,
            email=email,
        )
        for f, email in rows
    ]
