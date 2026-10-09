from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import ClassVar, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.core.enums import ClinicStage
from app.schemas.common import ApiModel, CountryCode, Email, PastYear, PatchModel


class ClientOrganizationRead(ApiModel):
    id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class ClientOrganizationCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)


class ClientOrganizationUpdate(ApiModel):
    name: str = Field(min_length=1, max_length=200)


class _ClinicFields(PatchModel):
    """Details anyone who may edit the clinic can change (admin, DSM, Clinic Administrator)."""

    specialty: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    email: Email | None = None
    phone: str | None = Field(default=None, max_length=32)
    website_url: str | None = Field(default=None, max_length=500)
    address_line: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, max_digits=9, decimal_places=6)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, max_digits=9, decimal_places=6)
    #: The year the clinic started operating ("Operating since"). Not in the future.
    established_year: PastYear | None = None


class ClinicCreate(_ClinicFields):
    """New lead (Platform Administrator only).

    Give ``client_organization_id`` to add a branch to an existing business. Leave it out to create
    the business in the same step: it is named ``client_organization_name``, or the clinic's name.
    """

    name: str = Field(min_length=1, max_length=200)
    country: CountryCode = "IN"
    client_organization_id: UUID | None = None
    client_organization_name: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _one_way_to_choose_the_business(self) -> Self:
        if self.client_organization_id is not None and self.client_organization_name is not None:
            raise ValueError("give client_organization_id OR client_organization_name, not both")
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("give latitude and longitude together")
        return self


class ClinicUpdate(_ClinicFields):
    """Change the clinic's details. ``client_organization_id`` (move to another business) is for
    the Platform Administrator and the clinic's DSM only."""

    not_null_fields: ClassVar[tuple[str, ...]] = ("name", "country", "client_organization_id")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    country: CountryCode | None = None
    client_organization_id: UUID | None = None


class ClinicRead(ApiModel):
    id: UUID
    client_organization_id: UUID
    name: str
    specialty: str | None
    description: str | None
    email: str | None
    phone: str | None
    website_url: str | None
    address_line: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str
    latitude: Decimal | None
    longitude: Decimal | None
    established_year: int | None
    stage: ClinicStage
    is_active: bool
    archived_reason: str | None
    created_at: datetime
    updated_at: datetime


class ClinicStageUpdate(ApiModel):
    stage: ClinicStage
    #: Saved with the stage history (why it moved).
    note: str | None = Field(default=None, max_length=1000)


class ClinicArchive(ApiModel):
    archived_reason: str = Field(min_length=1, max_length=1000)


class ClinicStageChangeRead(ApiModel):
    id: UUID
    clinic_id: UUID
    from_stage: ClinicStage | None
    to_stage: ClinicStage
    note: str | None
    changed_by_user_id: UUID | None
    changed_at: datetime
