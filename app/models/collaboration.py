"""Client Collaboration (chat): one conversation per clinic between the clinic and Radial Pulse.

* Everyone who can open the clinic's chat (``chat:read``) is in the conversation: the clinic's
  DSM, Platform Administrators, and the clinic's own people. No separate participants table.
* Messages are never edited or hard-deleted (the audit rule). Attachments are normal assets
  (kind ``chat_attachment``), uploaded with the presigned S3 flow first.
* ``sender_name`` / ``sender_side`` are copied at send time so every reader can show the bubble
  even when row-level security hides the sender's user row from them.
* Delivery is by polling (``GET …/chat/messages?after=…``). A WebSocket push can be added later
  without changing these tables (docs/architecture/chat-connections-settings.md).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ChatSide
from app.db.base import Base, UUIDPrimaryKeyMixin, str_enum, utcnow


class ChatMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_clinic_time", "clinic_id", "created_at", "id"),
        Index(
            "ix_chat_messages_attachment_asset_id",
            "attachment_asset_id",
            postgresql_where=text("attachment_asset_id IS NOT NULL"),
        ),
        CheckConstraint("body IS NOT NULL OR attachment_asset_id IS NOT NULL", name="body_or_attachment"),
        #: The file is from the SAME clinic, and cannot be hard-deleted while a message uses it.
        ForeignKeyConstraint(
            ["attachment_asset_id", "clinic_id"], ["assets.id", "assets.clinic_id"], ondelete="RESTRICT"
        ),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    sender_name: Mapped[str] = mapped_column(String(200))
    sender_side: Mapped[ChatSide] = mapped_column(str_enum(ChatSide, length=16))
    body: Mapped[str | None] = mapped_column(Text)
    attachment_asset_id: Mapped[uuid.UUID | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())


class ChatReadState(UUIDPrimaryKeyMixin, Base):
    """How far ONE person has read ONE clinic's chat. Drives the unread counts."""

    __tablename__ = "chat_read_states"
    __table_args__ = (UniqueConstraint("clinic_id", "user_id"),)

    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    last_read_at: Mapped[datetime] = mapped_column(default=utcnow)
