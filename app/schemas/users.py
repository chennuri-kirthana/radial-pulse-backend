from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import Field

from app.core.enums import NotificationCategory, NotificationChannel, PlatformRole
from app.schemas.common import ApiModel, Email, PatchModel


class UserRead(ApiModel):
    id: UUID
    email: str
    full_name: str | None
    phone: str | None
    platform_role: PlatformRole
    is_active: bool
    #: False until the person signs in for the first time.
    has_signed_in: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(ApiModel):
    """Invite a person (Platform Administrator). Cognito emails them a temporary password."""

    email: Email
    full_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    platform_role: PlatformRole


class UserUpdate(PatchModel):
    """Platform Administrator: change anyone. Role, active flag and email are admin-only (database guard)."""

    not_null_fields: ClassVar[tuple[str, ...]] = ("platform_role", "is_active")

    full_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    platform_role: PlatformRole | None = None
    is_active: bool | None = None


class MeUpdate(PatchModel):
    """Settings → My Profile: my own name and phone."""

    full_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)


class AvatarUploadRequest(ApiModel):
    content_type: str
    size_bytes: int


class AvatarConfirm(ApiModel):
    key: str = Field(max_length=512)
    content_type: str
    size_bytes: int


class NotificationPreferenceRead(ApiModel):
    category: NotificationCategory
    channel: NotificationChannel
    is_enabled: bool


class NotificationPreferenceUpdate(ApiModel):
    category: NotificationCategory
    channel: NotificationChannel
    is_enabled: bool


class NotificationPreferencesUpdate(ApiModel):
    items: list[NotificationPreferenceUpdate] = Field(min_length=1, max_length=8)
