"""Client Collaboration: messages between the clinic and its DSM / Radial Pulse."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.rbac import ClinicContext, Permission
from app.dependencies.adapters import get_optional_storage, get_storage
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.integrations.storage import ObjectStorage
from app.schemas.collaboration import (
    CollaborationAttachmentUploadRequest,
    CollaborationMessageCreate,
    CollaborationMessageRead,
)
from app.schemas.common import Page, UploadTicket, ViewLink
from app.services import collaboration

router = APIRouter(
    prefix="/clinics/{clinic_id}/collaboration-messages", tags=["collaboration messages"], responses=ERRORS
)
_read = clinic_access(Permission.COLLABORATION_MESSAGES_READ)
_send = clinic_access(Permission.COLLABORATION_MESSAGES_SEND)


@router.get("", response_model=Page[CollaborationMessageRead], summary="Threads, latest activity first")
def list_threads(
    limit: Limit = 50, offset: Offset = 0, ctx: ClinicContext = Depends(_read), db: Session = Depends(get_db)
) -> Page[CollaborationMessageRead]:
    return collaboration.list_threads(db, ctx, limit=limit, offset=offset)


@router.get("/{message_id}/replies", response_model=list[CollaborationMessageRead])
def list_replies(
    message_id: UUID, ctx: ClinicContext = Depends(_read), db: Session = Depends(get_db)
) -> list[CollaborationMessageRead]:
    return collaboration.list_replies(db, ctx, message_id)


@router.post("/attachments/uploads", response_model=UploadTicket, summary="Attachment, step 1")
def request_attachment_upload(
    body: CollaborationAttachmentUploadRequest,
    ctx: ClinicContext = Depends(_send),
    storage: ObjectStorage = Depends(get_storage),
) -> UploadTicket:
    """Image (JPEG / PNG / WebP) or PDF, at most 20 MB. PUT it, then send the message with the key."""
    return collaboration.request_attachment_upload(ctx, body, storage)


@router.post("", response_model=CollaborationMessageRead, status_code=status.HTTP_201_CREATED)
def send_message(
    body: CollaborationMessageCreate,
    ctx: ClinicContext = Depends(_send),
    db: Session = Depends(get_db),
    storage: ObjectStorage | None = Depends(get_optional_storage),
) -> CollaborationMessageRead:
    """Admin, DSM, Clinic Administrator, a linked practitioner (Team Members read only).
    Replies go to the FIRST message of a thread (a reply to a reply → 409)."""
    return collaboration.send_message(db, ctx, body, storage)


@router.get("/{message_id}/attachment", response_model=ViewLink, summary="Short-lived link to the attachment")
def attachment_view(
    message_id: UUID,
    ctx: ClinicContext = Depends(_read),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> ViewLink:
    """Every link handed out is audited."""
    return collaboration.attachment_view(db, ctx, message_id, storage)


@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_message(
    message_id: UUID, ctx: ClinicContext = Depends(_read), db: Session = Depends(get_db)
) -> None:
    """Platform Administrator only. Messages are never edited."""
    collaboration.delete_message(db, ctx, message_id)
