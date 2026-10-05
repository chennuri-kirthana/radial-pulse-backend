"""Client Collaboration (chat): one conversation per clinic between the clinic and Radial Pulse.

Rules (docs/architecture/chat-connections-settings.md):
* Anyone with ``chat:read`` in the clinic reads the conversation; ``chat:write`` sends.
* Messages are never edited or deleted. The audit log records THAT a message was sent, never its text.
* An attachment must be an uploaded asset of this clinic with kind ``chat_attachment``.
* Unread = messages from other people after my "read up to" mark. Sending moves my own mark.
* The "inbox" is the chats a person is part of: a DSM's assigned clinics, a clinic person's
  own clinics, and — for Platform Administrators, who can open every clinic — only the chats
  they have opened or written in (otherwise every clinic would count as unread).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import AssetKind, AssetStatus, ChatSide
from app.core.errors import DomainValidationError, NotFoundError
from app.core.rbac import ClinicContext, Permission, Principal
from app.db.base import utcnow
from app.models import ChatMessage
from app.repositories.assets import AssetRepository
from app.repositories.chat import ChatRepository
from app.repositories.users import UserRepository
from app.schemas.chat import (
    ChatInbox,
    ChatMarkRead,
    ChatMessageCreate,
    ChatMessagePage,
    ChatMessageRead,
    ChatThread,
)
from app.services import audit


def _sender(session: Session, principal: Principal) -> tuple[str, ChatSide]:
    user = UserRepository(session).get(principal.user_id)
    name = (user.full_name if user and user.full_name else None) or principal.email.split("@", 1)[0]
    return name, ChatSide.RADIAL_PULSE if principal.is_internal else ChatSide.CLINIC


def _principal(ctx: ClinicContext) -> Principal:
    if not isinstance(ctx.principal, Principal):  # the worker never chats
        raise DomainValidationError("Only people can use the chat")
    return ctx.principal


def list_messages(
    session: Session,
    ctx: ClinicContext,
    *,
    before: UUID | None,
    after: UUID | None,
    limit: int,
) -> ChatMessagePage:
    if before is not None and after is not None:
        raise DomainValidationError("use either before or after, not both")
    repo = ChatRepository(session)

    def cursor(message_id: UUID | None) -> ChatMessage | None:
        if message_id is None:
            return None
        found = repo.get_in_clinic(ctx.clinic_id, message_id)
        if found is None:
            raise NotFoundError("Message not found")
        return found

    items, more = repo.page(ctx.clinic_id, before=cursor(before), after=cursor(after), limit=limit)
    user_id = _principal(ctx).user_id
    return ChatMessagePage(
        items=[ChatMessageRead.model_validate(m) for m in items],
        has_more=more,
        unread_count=repo.unread_count(ctx.clinic_id, user_id),
    )


def send_message(session: Session, ctx: ClinicContext, data: ChatMessageCreate) -> ChatMessage:
    principal = _principal(ctx)
    if data.attachment_asset_id is not None:
        asset = AssetRepository(session).get_in_clinic(ctx.clinic_id, data.attachment_asset_id)
        if asset is None:
            raise NotFoundError("Attachment not found in this clinic")
        if asset.kind is not AssetKind.CHAT_ATTACHMENT or asset.status is not AssetStatus.UPLOADED:
            raise DomainValidationError("The attachment must be an uploaded file of kind chat_attachment")
    name, side = _sender(session, principal)
    repo = ChatRepository(session)
    message = repo.add(
        ChatMessage(
            clinic_id=ctx.clinic_id,
            sender_user_id=principal.user_id,
            sender_name=name,
            sender_side=side,
            body=data.body,
            attachment_asset_id=data.attachment_asset_id,
            created_at=repo.stamp_for_new_message(ctx.clinic_id),
        )
    )
    repo.mark_read(ctx.clinic_id, principal.user_id, message.created_at)
    audit.record(
        session,
        actor=principal,
        action="chat.message_sent",
        resource_type="chat_message",
        resource_id=message.id,
        clinic_id=ctx.clinic_id,
        details={"side": side.value, "has_attachment": data.attachment_asset_id is not None},
    )
    session.commit()
    return message


def mark_read(session: Session, ctx: ClinicContext, data: ChatMarkRead) -> None:
    principal = _principal(ctx)
    repo = ChatRepository(session)
    # "Everything": up to the newest message there is (its database time), not this server's clock.
    at = repo.newest_time(ctx.clinic_id) or utcnow()
    if data.up_to_message_id is not None:
        message = repo.get_in_clinic(ctx.clinic_id, data.up_to_message_id)
        if message is None:
            raise NotFoundError("Message not found")
        at = message.created_at
    repo.mark_read(ctx.clinic_id, principal.user_id, at)
    session.commit()


def _inbox_clinic_ids(session: Session, principal: Principal) -> list[UUID]:
    accessible = principal.accessible_clinic_ids()
    if accessible is None:  # Platform Administrator: only the chats they took part in
        return sorted(ChatRepository(session).clinics_with_read_state(principal.user_id), key=str)
    return sorted(
        (cid for cid in accessible if Permission.CHAT_READ in principal.clinic_permissions(cid)), key=str
    )


def inbox(session: Session, principal: Principal, limit: int) -> ChatInbox:
    repo = ChatRepository(session)
    clinic_ids = _inbox_clinic_ids(session, principal)
    threads = repo.threads(clinic_ids, principal.user_id, limit)
    unread = repo.unread_counts(clinic_ids, principal.user_id)
    return ChatInbox(
        items=[
            ChatThread(
                clinic_id=t.clinic_id,
                clinic_name=t.clinic_name,
                last_message=ChatMessageRead.model_validate(t.last_message),
                unread_count=t.unread_count,
            )
            for t in threads
        ],
        unread_threads=sum(1 for count in unread.values() if count),
        unread_messages=sum(unread.values()),
    )
