"""Governed client profile contract (read by every team; written through Central only)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from app.schemas.assets import AssetRead
from app.schemas.clinics import TeamMemberRead
from app.schemas.common import ApiModel

HexColor = Annotated[str, Field(pattern=r"^#[0-9A-Fa-f]{6}$")]
Weekday = Annotated[str, Field(pattern=r"^(mon|tue|wed|thu|fri|sat|sun)$")]
ClockTime = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]


class BrandSection(ApiModel):
    tagline: str | None = Field(default=None, max_length=200)
    tone_of_voice: str | None = Field(default=None, max_length=500)
    primary_color: HexColor | None = None
    secondary_color: HexColor | None = None
    logo_asset_id: UUID | None = None
    words_to_use: list[str] = Field(default_factory=list, max_length=50)
    words_to_avoid: list[str] = Field(default_factory=list, max_length=50)


class AudienceSection(ApiModel):
    segments: list[str] = Field(default_factory=list, max_length=20)
    languages: list[str] = Field(default_factory=list, max_length=10)
    service_areas: list[str] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=2000)


class ServiceItem(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=1000)


class ServicesSection(ApiModel):
    items: list[ServiceItem] = Field(default_factory=list, max_length=200)


class OpeningSlot(ApiModel):
    opens: ClockTime
    closes: ClockTime


class ScheduleSection(ApiModel):
    timezone: str = "Asia/Kolkata"
    opening_hours: dict[Weekday, list[OpeningSlot]] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=1000)


class ConsentRead(ApiModel):
    id: UUID
    consent_type: str
    granted: bool
    granted_at: datetime | None
    revoked_at: datetime | None


class ClinicProfileRead(ApiModel):
    """The tenant-scoped client context other teams build on."""

    clinic_id: UUID
    version: int
    brand: BrandSection
    audience: AudienceSection
    services: ServicesSection
    schedule: ScheduleSection
    consents: list[ConsentRead]
    approved_assets: list[AssetRead]
    team: list[TeamMemberRead]
    updated_at: datetime | None


class ClinicProfileUpdate(ApiModel):
    """Replace whole sections. ``version`` must equal the version you read (else 409)."""

    version: int = Field(ge=1)
    brand: BrandSection | None = None
    audience: AudienceSection | None = None
    services: ServicesSection | None = None
    schedule: ScheduleSection | None = None
