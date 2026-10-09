"""Client Collaboration (messages between the clinic and Radial Pulse) and my notifications.

Messages: text and/or one attachment (image / PDF); replies one level deep (trigger → 409); no
unread counts. Everyone who sees the clinic reads; Clinic Team Members don't send; you only send
as yourself; only the Platform Administrator deletes. Each attachment view link is audited.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.enums import SenderSide
from app.core.errors import ForbiddenError, InvalidRequestError, NotFoundError
from app.core.rbac import ClinicContext, Principal
from app.db.base import utcnow
from app.integrations.storage import ObjectStorage
from app.models import CollaborationMessage, Notification
from app.schemas.collaboration import (
    CollaborationAttachmentUploadRequest,
    CollaborationMessageCreate,
    CollaborationMessageRead,
    NotificationRead,
)
from app.schemas.common import Page, UploadTicket, ViewLink
from app.services import audit, uploads

ATTACHMENT_FILES = uploads.FileRule(
    types={"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "application/pdf": "pdf"},
    max_bytes=20 * 1024 * 1024,
)


# ------------------------------------------------------------------------------ notifications
def list_notifications(
    session: Session, principal: Principal, *, unread_only: bool, limit: int, offset: int
) -> Page[NotificationRead]:
    query = select(Notification).where(Notification.user_id == principal.user_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(Notification.created_at.desc(), Notification.id).limit(limit).offset(offset)
    )
    return Page(
        items=[NotificationRead.model_validate(n) for n in rows], total=total, limit=limit, offset=offset
    )


def mark_read(session: Session, principal: Principal, notification_id: UUID) -> NotificationRead:
    note = session.get(Notification, notification_id)
    if note is None or note.user_id != principal.user_id:
        raise NotFoundError("Notification not found")
    if note.read_at is None:
        note.read_at = utcnow()
        audit.record(
            session,
            actor_user_id=principal.user_id,
            action="notification.read",
            resource_type="notification",
            resource_id=note.id,
            clinic_id=None,
        )
        session.commit()
    return NotificationRead.model_validate(note)


def mark_all_read(session: Session, principal: Principal) -> None:
    result = session.execute(
        update(Notification)
        .where(Notification.user_id == principal.user_id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    audit.record(
        session,
        actor_user_id=principal.user_id,
        action="notification.all_read",
        resource_type="user",
        resource_id=principal.user_id,
        clinic_id=None,
        details={"count": getattr(result, "rowcount", 0)},
    )
    session.commit()


# ------------------------------------------------------------------------------ messages
def _read(
    m: CollaborationMessage, reply_count: int = 0, last_reply_at: datetime | None = None
) -> CollaborationMessageRead:
    return CollaborationMessageRead(
        id=m.id,
        clinic_id=m.clinic_id,
        sender_user_id=m.sender_user_id,
        sender_name=m.sender_name,
        sender_side=m.sender_side,
        body=m.body,
        attachment_name=m.attachment_name,
        has_attachment=m.attachment_key is not None,
        parent_message_id=m.parent_message_id,
        reply_count=reply_count,
        last_reply_at=last_reply_at,
        created_at=m.created_at,
    )


def list_threads(
    session: Session, ctx: ClinicContext, *, limit: int, offset: int
) -> Page[CollaborationMessageRead]:
    """First messages of each thread, newest first, with their reply count and last reply time."""
    replies = (
        select(
            CollaborationMessage.parent_message_id.label("parent_id"),
            func.count().label("reply_count"),
            func.max(CollaborationMessage.created_at).label("last_reply_at"),
        )
        .where(
            CollaborationMessage.clinic_id == ctx.clinic_id,
            CollaborationMessage.parent_message_id.is_not(None),
        )
        .group_by(CollaborationMessage.parent_message_id)
        .subquery()
    )
    base = select(CollaborationMessage).where(
        CollaborationMessage.clinic_id == ctx.clinic_id, CollaborationMessage.parent_message_id.is_(None)
    )
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.execute(
        select(CollaborationMessage, replies.c.reply_count, replies.c.last_reply_at)
        .outerjoin(replies, replies.c.parent_id == CollaborationMessage.id)
        .where(
            CollaborationMessage.clinic_id == ctx.clinic_id, CollaborationMessage.parent_message_id.is_(None)
        )
        .order_by(
            func.coalesce(replies.c.last_reply_at, CollaborationMessage.created_at).desc(),
            CollaborationMessage.id,
        )
        .limit(limit)
        .offset(offset)
    )
    items = [_read(m, count or 0, last) for m, count, last in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


def list_replies(session: Session, ctx: ClinicContext, message_id: UUID) -> list[CollaborationMessageRead]:
    _get(session, ctx, message_id)
    rows = session.scalars(
        select(CollaborationMessage)
        .where(
            CollaborationMessage.clinic_id == ctx.clinic_id,
            CollaborationMessage.parent_message_id == message_id,
        )
        .order_by(CollaborationMessage.created_at, CollaborationMessage.id)
    )
    return [_read(m) for m in rows]


def request_attachment_upload(
    ctx: ClinicContext, body: CollaborationAttachmentUploadRequest, storage: ObjectStorage
) -> UploadTicket:
    ext = ATTACHMENT_FILES.check(body.content_type, body.size_bytes)
    key = f"clinics/{ctx.clinic_id}/collaboration/{uuid.uuid4()}.{ext}"
    return uploads.ticket(storage, key, body.content_type, body.size_bytes)


def send_message(
    session: Session, ctx: ClinicContext, body: CollaborationMessageCreate, storage: ObjectStorage | None
) -> CollaborationMessageRead:
    key, ctype, size = body.attachment_key, body.attachment_content_type, body.attachment_size_bytes
    if key is not None:
        if (
            storage is None
            or ctype is None
            or size is None
            or not key.startswith(f"clinics/{ctx.clinic_id}/collaboration/")
        ):
            raise InvalidRequestError(
                "Use the key from the upload step.", fields={"attachment_key": "Not valid here."}
            )
        ATTACHMENT_FILES.check(ctype, size)
        uploads.check_uploaded(storage, key, size, ctype)
    if body.parent_message_id is not None:
        _get(session, ctx, body.parent_message_id)
    message = CollaborationMessage(
        clinic_id=ctx.clinic_id,
        sender_user_id=ctx.user_id,
        sender_name=ctx.principal.full_name or ctx.principal.email,
        sender_side=SenderSide.RADIAL_PULSE if ctx.is_staff else SenderSide.CLINIC,
        body=body.body,
        attachment_key=body.attachment_key,
        attachment_name=body.attachment_name,
        parent_message_id=body.parent_message_id,
    )
    session.add(message)
    session.flush()  # a reply to a reply fails here (threads are one level deep): 409
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="collaboration_message.sent",
        resource_type="collaboration_message",
        resource_id=message.id,
        clinic_id=ctx.clinic_id,
        details={
            "has_attachment": body.attachment_key is not None,
            "reply": body.parent_message_id is not None,
        },
    )
    session.commit()
    return _read(message)


def attachment_view(
    session: Session, ctx: ClinicContext, message_id: UUID, storage: ObjectStorage
) -> ViewLink:
    message = _get(session, ctx, message_id)
    if message.attachment_key is None:
        raise NotFoundError("This message has no attachment")
    url = uploads.view_link(storage, message.attachment_key)
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="collaboration_message.attachment_viewed",
        resource_type="collaboration_message",
        resource_id=message.id,
        clinic_id=ctx.clinic_id,
    )
    session.commit()
    return ViewLink(url=url, expires_in_seconds=uploads.VIEW_URL_TTL_SECONDS)


def delete_message(session: Session, ctx: ClinicContext, message_id: UUID) -> None:
    if not ctx.principal.is_platform_administrator:
        raise ForbiddenError("Only a Platform Administrator can delete messages.")
    message = _get(session, ctx, message_id)
    session.delete(message)
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="collaboration_message.deleted",
        resource_type="collaboration_message",
        resource_id=message_id,
        clinic_id=ctx.clinic_id,
    )
    session.commit()


def _get(session: Session, ctx: ClinicContext, message_id: UUID) -> CollaborationMessage:
    message = session.get(CollaborationMessage, message_id)
    if message is None or message.clinic_id != ctx.clinic_id:
        raise NotFoundError("Message not found")
    return message
