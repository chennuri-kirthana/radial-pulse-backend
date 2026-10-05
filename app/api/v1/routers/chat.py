"""Client Collaboration (chat): clinic <-> Radial Pulse team.

OWNER: Person 1 (API) + Person 2 (web/mobile UI). Design: docs/architecture/chat-connections-settings.md.

* One conversation per clinic. History lives in PostgreSQL (row-level security like every clinic table).
* New messages arrive by POLLING: call ``GET …/chat/messages?after=<last id>`` every 10-15 s while the
  chat is open, and ``GET /chat/inbox`` for the unread badge. A WebSocket push can come later and
  would only deliver — history stays here.
* Attachments use the normal assets upload flow (kind ``chat_attachment``).
* Messages must not contain patient health information (decision D19; show the notice in the UI).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.rbac import ClinicContext, Permission, Principal
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.schemas.chat import ChatInbox, ChatMarkRead, ChatMessageCreate, ChatMessagePage, ChatMessageRead
from app.services import chat as service

router = APIRouter(prefix="/clinics/{clinic_id}/chat", tags=["chat"], responses=ERRORS)
inbox_router = APIRouter(prefix="/chat", tags=["chat"], responses=ERRORS)


@router.get(
    "/messages",
    response_model=ChatMessagePage,
    summary="Messages, oldest first. No cursor = newest page; before = older; after = new ones (polling)",
)
def list_messages(
    before: UUID | None = Query(default=None, description="Load messages older than this message id"),
    after: UUID | None = Query(default=None, description="Load messages newer than this message id"),
    limit: int = Query(default=50, ge=1, le=100),
    ctx: ClinicContext = Depends(clinic_access(Permission.CHAT_READ)),
    db: Session = Depends(get_db),
) -> ChatMessagePage:
    return service.list_messages(db, ctx, before=before, after=after, limit=limit)


@router.post(
    "/messages",
    response_model=ChatMessageRead,
    status_code=status.HTTP_201_CREATED,
    summary="Send a message (text and/or one attachment)",
)
def send_message(
    body: ChatMessageCreate,
    ctx: ClinicContext = Depends(clinic_access(Permission.CHAT_WRITE)),
    db: Session = Depends(get_db),
) -> ChatMessageRead:
    return ChatMessageRead.model_validate(service.send_message(db, ctx, body))


@router.post(
    "/read",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Mark the chat read (up to a message, or everything)",
)
def mark_read(
    body: ChatMarkRead,
    ctx: ClinicContext = Depends(clinic_access(Permission.CHAT_READ)),
    db: Session = Depends(get_db),
) -> Response:
    service.mark_read(db, ctx, body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@inbox_router.get(
    "/inbox",
    response_model=ChatInbox,
    summary='My chats with unread counts (the "Unread Chats" tile and the chat list)',
)
def inbox(
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> ChatInbox:
    return service.inbox(db, principal, limit)
