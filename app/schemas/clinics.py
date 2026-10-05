from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, HttpUrl, model_validator

from app.core.enums import ClinicRole, ClinicStage, ClinicStageGroup, WorkArea
from app.schemas.common import ApiModel, CountryCode, Email, PatchModel, ShortText


class _Location(ApiModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


# ----------------------------------------------------------------------- clinics
class ClinicCreate(_Location):
    name: ShortText
    #: Attach to an existing organization (another branch). Omit to create a new organization.
    organization_id: UUID | None = None
    specialty: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    email: Email | None = None
    address_line: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: CountryCode = "IN"
    phone: str | None = Field(default=None, max_length=32)
    website_url: HttpUrl | None = None
    #: The main practitioner, created with the clinic (the "Doctor Name" in lists). Optional.
    primary_practitioner_name: ShortText | None = None

    @model_validator(mode="after")
    def _lat_lng_together(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("latitude and longitude must be given together")
        return self


class ClinicUpdate(_Location, PatchModel):
    """Edit clinic details. Stage and archiving have their own routes."""

    not_null_fields = ("name",)

    name: ShortText | None = None
    specialty: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    email: Email | None = None
    address_line: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=32)
    website_url: HttpUrl | None = None
    #: An uploaded clinic_photo asset of THIS clinic (or null to remove the photo).
    cover_asset_id: UUID | None = None


class ClinicRead(ApiModel):
    id: UUID
    organization_id: UUID
    name: str
    specialty: str | None
    description: str | None
    email: str | None
    address_line: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str
    phone: str | None
    website_url: str | None
    latitude: float | None
    longitude: float | None
    cover_asset_id: UUID | None
    stage: ClinicStage
    #: The Admin tab this stage belongs to (prospects / in_progress / active).
    stage_group: ClinicStageGroup
    stage_changed_at: datetime
    is_active: bool
    archived_reason: str | None
    created_at: datetime
    updated_at: datetime


class PersonRef(ApiModel):
    id: UUID
    full_name: str | None
    email: str


class AreaCount(ApiModel):
    area: WorkArea
    open_count: int


class ClinicListItem(ClinicRead):
    """A row of the Clinics / My Client Portfolio table."""

    primary_practitioner_name: str | None
    #: The clinic's Digital Success Manager (null = not assigned).
    dsm: PersonRef | None
    #: Open work items per area — the "SEO 3 · GBP 2" chips. Only areas with open items.
    open_work: list[AreaCount]


class StageChange(ApiModel):
    stage: ClinicStage
    note: str | None = Field(default=None, max_length=2000)


class StageHistoryRead(ApiModel):
    id: UUID
    clinic_id: UUID
    from_stage: ClinicStage | None
    to_stage: ClinicStage
    note: str | None
    changed_by_user_id: UUID | None
    changed_at: datetime


class ArchiveRequest(ApiModel):
    reason: str = Field(min_length=3, max_length=2000)


# ------------------------------------------------------------------ practitioners
class PractitionerCreate(ApiModel):
    """Add a practitioner to this clinic.

    Either describe a NEW person (``full_name`` + details), or give ``practitioner_id`` to link a
    doctor who already works at another branch of the same business.
    """

    #: Link an existing practitioner of the same business (then leave the person fields out).
    practitioner_id: UUID | None = None
    full_name: ShortText | None = None
    specialty: str | None = Field(default=None, max_length=120)
    qualifications: str | None = Field(default=None, max_length=300)
    registration_number: str | None = Field(default=None, max_length=64)
    bio: str | None = Field(default=None, max_length=5000)
    #: Make this the clinic's main practitioner (replaces the current one).
    is_primary: bool = False
    #: Link an existing clinic user login (optional — most practitioners will not have one).
    user_id: UUID | None = None

    @model_validator(mode="after")
    def _new_or_existing(self) -> Self:
        person_fields = ("full_name", "specialty", "qualifications", "registration_number", "bio", "user_id")
        if self.practitioner_id is None and self.full_name is None:
            raise ValueError("give full_name for a new practitioner, or practitioner_id to link one")
        if self.practitioner_id is not None and any(getattr(self, f) is not None for f in person_fields):
            raise ValueError("when linking with practitioner_id, leave the person's details out")
        return self


class PractitionerUpdate(PatchModel):
    """Name/specialty/qualifications/registration/bio change the PERSON (every branch they work
    at). ``is_primary`` and ``is_active`` apply to THIS clinic only."""

    not_null_fields = ("full_name", "is_primary", "is_active")

    full_name: ShortText | None = None
    specialty: str | None = Field(default=None, max_length=120)
    qualifications: str | None = Field(default=None, max_length=300)
    registration_number: str | None = Field(default=None, max_length=64)
    bio: str | None = Field(default=None, max_length=5000)
    is_primary: bool | None = None
    is_active: bool | None = None


class PractitionerRead(ApiModel):
    id: UUID
    clinic_id: UUID
    full_name: str
    specialty: str | None
    qualifications: str | None
    registration_number: str | None
    bio: str | None
    is_primary: bool
    user_id: UUID | None
    is_active: bool
    created_at: datetime


# -------------------------------------------------------------------------- team
class TeamMemberCreate(ApiModel):
    """Add a clinic-side person. Creates the (clinic_user) account if the email is new, and sends
    an invite email. Role `clinic_administrator` (default) or `clinic_team_member` (clinic staff: view-only
    plus uploading photos/files).
    """

    email: Email
    full_name: str | None = Field(default=None, max_length=200)
    role: ClinicRole = ClinicRole.CLINIC_ADMINISTRATOR


class TeamMemberUpdate(ApiModel):
    is_active: bool


class TeamMemberRead(ApiModel):
    id: UUID
    clinic_id: UUID
    user_id: UUID
    email: str
    full_name: str | None
    role: ClinicRole
    is_active: bool
    #: False until the person signs in for the first time.
    has_signed_in: bool


# ------------------------------------------------------------ portfolio allocation
class AssignmentSet(ApiModel):
    """Make this Digital Success Manager THE DSM of the clinic (replaces the current one)."""

    user_id: UUID


class AssignmentRead(ApiModel):
    id: UUID
    clinic_id: UUID
    user_id: UUID
    is_active: bool
    assigned_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime
