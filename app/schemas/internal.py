from __future__ import annotations

from uuid import UUID

from app.schemas.clinics import ClinicRead
from app.schemas.common import ApiModel


class InternalClinicRead(ClinicRead):
    """A clinic with its business name, for other teams' backends."""

    client_organization_name: str


# ---- Phase 1 for the SEO team (Digital Growth Team): active client clinics only, minimal fields ----


class InternalActiveClinic(ApiModel):
    """One active client clinic in the list: its id and name only."""

    clinic_id: UUID
    name: str


class InternalClinicAddress(ApiModel):
    """The clinic's postal address.

    From ``clinics.address_line`` (as ``line``), ``city``, ``state``, ``postal_code``, ``country``.
    """

    line: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    country: str


class InternalClinicNap(ApiModel):
    """Name, address, phone (NAP) and website of one active client clinic. Nothing else.

    ``website_url`` is null when the clinic has no website.
    """

    clinic_id: UUID
    name: str
    address: InternalClinicAddress
    phone: str | None
    website_url: str | None
