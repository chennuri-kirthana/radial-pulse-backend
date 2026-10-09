"""Client Collaboration: messages between the clinic and Radial Pulse (db/schema-v15.sql section 7).

Replies are one level deep (trigger). Reply counts are counted, not stored. No read markers.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, ForeignKeyConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import SenderSide
from app.db.base import Base, CreatedAt, str_enum, uuid_pk


class CollaborationMessage(CreatedAt, Base):
    __tablename__ = "collaboration_messages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["parent_message_id", "clinic_id"],
            ["collaboration_messages.id", "collaboration_messages.clinic_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    #: kept even if the sender's account is removed later
    sender_name: Mapped[str] = mapped_column(String(200))
    sender_side: Mapped[SenderSide] = mapped_column(str_enum(SenderSide, 16))
    body: Mapped[str | None] = mapped_column(Text)
    #: S3 key under clinics/<clinic_id>/
    attachment_key: Mapped[str | None] = mapped_column(String(512))
    attachment_name: Mapped[str | None] = mapped_column(String(255))
    parent_message_id: Mapped[uuid.UUID | None]
