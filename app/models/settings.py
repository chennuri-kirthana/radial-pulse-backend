"""``platform_settings``: exactly one row (id = 1). Readable by everyone, changed by the admin."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import FetchedValue, SmallInteger, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PlatformSettings(Base):
    __tablename__ = "platform_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, server_default=text("1"))
    support_email: Mapped[str | None] = mapped_column(String(320))
    support_phone: Mapped[str | None] = mapped_column(String(32))
    timezone: Mapped[str] = mapped_column(String(64), server_default=text("'Asia/Kolkata'"))
    date_format: Mapped[str] = mapped_column(String(16), server_default=text("'DD MMM YYYY'"))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), server_onupdate=FetchedValue())
