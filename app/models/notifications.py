"""In-app notifications and each person's switches (db/schema-v15.sql section 6)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, FetchedValue, ForeignKey, String, Text, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import NotificationCategory, NotificationChannel
from app.db.base import Base, CreatedAt, str_enum, uuid_pk


class Notification(CreatedAt, Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    clinic_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    category: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(500))
    read_at: Mapped[datetime | None]


class NotificationPreference(Base):
    """One on/off switch per person, category and channel. No row = on."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    category: Mapped[NotificationCategory] = mapped_column(
        str_enum(NotificationCategory, 40), primary_key=True
    )
    channel: Mapped[NotificationChannel] = mapped_column(str_enum(NotificationChannel, 16), primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), server_onupdate=FetchedValue())
