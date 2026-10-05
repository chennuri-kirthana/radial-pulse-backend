from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.core.enums import PlatformRole, UserStatus
from app.schemas.common import ApiModel, Email, PatchModel


class UserCreate(ApiModel):
    """Pre-provision a staff user. They get an invite email and sign in with Google using this email."""

    email: Email
    full_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    platform_role: PlatformRole


class UserUpdate(PatchModel):
    not_null_fields = ("is_active",)

    full_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    #: false = deactivated: cannot sign in. Their clinics stay allocated until the Admin moves them.
    is_active: bool | None = None


class UserRead(ApiModel):
    id: UUID
    email: str
    full_name: str | None
    phone: str | None
    platform_role: PlatformRole
    is_active: bool
    #: Worked out: deactivated / invited (never signed in) / active.
    status: UserStatus
    last_invited_at: datetime | None
    last_login_at: datetime | None
    created_at: datetime


class UserListItem(UserRead):
    """A row of the Users screen."""

    #: Clinics this Digital Success Manager looks after now (0 for other roles).
    assigned_clinic_count: int


class MeUpdate(ApiModel):
    """What a signed-in person may change about themselves (Settings → My Profile)."""

    full_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
