"""People: ``users`` (db/schema-v15.sql section 1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PlatformRole
from app.db.base import Base, Timestamps, str_enum, uuid_pk


class User(Timestamps, Base):
    """A login. Created by an invite first; the Cognito ``sub`` is linked on the first sign-in
    (``rp_user_for_login``). Only a Platform Administrator changes role, active flag or email."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320))
    full_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    cognito_sub: Mapped[str | None] = mapped_column(String(64))
    platform_role: Mapped[PlatformRole] = mapped_column(str_enum(PlatformRole))
    #: S3 key under users/<id>/ (profile photo)
    avatar_key: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    last_login_at: Mapped[datetime | None]
