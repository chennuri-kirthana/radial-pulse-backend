from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import Field

from app.core.enums import ClinicMemberRole
from app.schemas.common import ApiModel, Email, PatchModel


class ClinicMemberRead(ApiModel):
    clinic_id: UUID
    user_id: UUID
    role: ClinicMemberRole
    is_active: bool
    email: str
    full_name: str | None
    phone: str | None
    #: False until the person signs in for the first time.
    has_signed_in: bool
    created_at: datetime


class ClinicMemberCreate(ApiModel):
    """Add a Clinic Administrator or Clinic Team Member. A new email is invited (Cognito account
    created); an existing clinic-member login is linked to this clinic."""

    email: Email
    full_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=32)
    role: ClinicMemberRole


class ClinicMemberUpdate(PatchModel):
    not_null_fields: ClassVar[tuple[str, ...]] = ("role", "is_active")

    role: ClinicMemberRole | None = None
    is_active: bool | None = None
