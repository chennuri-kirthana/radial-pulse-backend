"""Settings: platform-wide values (Admin → Settings → General) and each person's notification choices."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import DateFormat, NotificationCategory, NotificationChannel
from app.db.base import Base, UUIDPrimaryKeyMixin, str_enum, utcnow


class PlatformSettings(Base):
    """Exactly ONE row (id = 1). Everyone signed in can read it; only Platform Administrators change it."""

    __tablename__ = "platform_settings"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False, default=1)
    organization_name: Mapped[str] = mapped_column(String(200), default="Radial Pulse")
    #: Shown in the apps under "Help & Support".
    support_email: Mapped[str | None] = mapped_column(String(320))
    support_phone: Mapped[str | None] = mapped_column(String(32))
    #: IANA timezone used to show dates (the database always stores UTC).
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    date_format: Mapped[DateFormat] = mapped_column(
        str_enum(DateFormat, length=16), default=DateFormat.DD_MMM_YYYY
    )
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now(), onupdate=utcnow)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class NotificationPreference(UUIDPrimaryKeyMixin, Base):
    """One switch that a person turned OFF or ON. No row = the default (on)."""

    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "category", "channel"),)

    #: No separate index: the unique key (user_id, category, channel) starts with user_id.
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    category: Mapped[NotificationCategory] = mapped_column(str_enum(NotificationCategory, length=40))
    channel: Mapped[NotificationChannel] = mapped_column(str_enum(NotificationChannel, length=16))
    enabled: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now(), onupdate=utcnow)
