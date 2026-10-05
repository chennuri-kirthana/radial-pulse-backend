from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field, HttpUrl

from app.core.enums import PresencePlatform, PresenceVerification
from app.schemas.assessments import EvidenceRead
from app.schemas.common import ApiModel


class PresenceProfileCreate(ApiModel):
    """A person adds where the clinic is online. People-added profiles start CONFIRMED."""

    platform: PresencePlatform
    url: HttpUrl
    external_id: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)


class PresenceProfileUpdate(ApiModel):
    verification: PresenceVerification | None = None
    external_id: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)


class PresenceProfileRead(ApiModel):
    id: UUID
    clinic_id: UUID
    platform: PresencePlatform
    url: str
    external_id: str | None
    display_name: str | None
    verification: PresenceVerification
    confidence: float | None
    discovered_by: str
    evidence: list[EvidenceRead]
    verified_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
