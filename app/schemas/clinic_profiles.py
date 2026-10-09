from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.core.enums import OnlineProfilePlatform, OnlineProfileVerification
from app.schemas.common import ApiModel, PatchModel


class ClinicProfileRead(ApiModel):
    clinic_id: UUID
    brand: dict[str, Any]
    audience: dict[str, Any]
    services: dict[str, Any]
    schedule: dict[str, Any]
    #: 0 = nothing saved yet. Send it back with PUT.
    version: int
    updated_at: datetime | None


class ClinicProfileUpdate(ApiModel):
    """Replace the profile. ``version`` must be the one you read (someone else saved in between → 409)."""

    brand: dict[str, Any] = Field(default_factory=dict)
    audience: dict[str, Any] = Field(default_factory=dict)
    services: dict[str, Any] = Field(default_factory=dict)
    schedule: dict[str, Any] = Field(default_factory=dict)
    version: int = Field(ge=0)


class ClinicOnlineProfileRead(ApiModel):
    id: UUID
    clinic_id: UUID
    platform: OnlineProfilePlatform
    url: str
    external_id: str | None
    display_name: str | None
    verification: OnlineProfileVerification
    confidence: float | None
    discovered_by: str
    created_at: datetime
    updated_at: datetime


class ClinicOnlineProfileCreate(ApiModel):
    platform: OnlineProfilePlatform
    #: cleaned by the database (https, lower-case host, no www., no trailing /)
    url: str = Field(min_length=1, max_length=1000, pattern=r"^(?i:https?://)\S+$")
    external_id: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)


class ClinicOnlineProfileUpdate(PatchModel):
    """Confirm or reject (staff only), or fix the name / id."""

    verification: OnlineProfileVerification | None = None
    external_id: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)
