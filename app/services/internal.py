"""Read-only data for other teams' backends (/api/v1/internal), as database role ``radial_service``.

That role may read: client organizations, clinics, clinic profiles, practitioners, clinic links,
online profiles, APPROVED photos, connected accounts (never ``secret_ref``: no column grant) and
their resources. It can't write anything, not even audit rows, so no file view links are given.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import ClinicStage
from app.core.errors import NotFoundError
from app.models import (
    ClientOrganization,
    Clinic,
    ClinicOnlineProfile,
    ClinicPractitioner,
    ClinicProfile,
    ConnectedAccount,
    ConnectedAccountResource,
    Photo,
    Practitioner,
)
from app.schemas.clinic_profiles import ClinicOnlineProfileRead, ClinicProfileRead
from app.schemas.clinics import ClinicRead
from app.schemas.common import Page
from app.schemas.connected_accounts import ConnectedAccountRead, ConnectedAccountResourceRead
from app.schemas.internal import (
    InternalActiveClinic,
    InternalClinicAddress,
    InternalClinicNap,
    InternalClinicRead,
)
from app.schemas.photos import PhotoRead
from app.schemas.practitioners import ClinicPractitionerRead
from app.services.practitioners import link_read

#: Every connected_accounts column EXCEPT secret_ref (the role has no grant on it).
_ACCOUNT_COLUMNS = [c for c in ConnectedAccount.__table__.columns if c.name != "secret_ref"]


def list_clinics(session: Session, *, limit: int, offset: int) -> Page[InternalClinicRead]:
    total = session.scalar(select(func.count()).select_from(Clinic)) or 0
    rows = session.execute(
        select(Clinic, ClientOrganization.name)
        .join(ClientOrganization, ClientOrganization.id == Clinic.client_organization_id)
        .order_by(Clinic.name, Clinic.id)
        .limit(limit)
        .offset(offset)
    )
    items = [_clinic_read(c, org_name) for c, org_name in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


def get_clinic(session: Session, clinic_id: UUID) -> InternalClinicRead:
    row = session.execute(
        select(Clinic, ClientOrganization.name)
        .join(ClientOrganization, ClientOrganization.id == Clinic.client_organization_id)
        .where(Clinic.id == clinic_id)
    ).first()
    if row is None:
        raise NotFoundError("Clinic not found")
    clinic, org_name = row
    return _clinic_read(clinic, org_name)


def clinic_profile(session: Session, clinic_id: UUID) -> ClinicProfileRead:
    _require_clinic(session, clinic_id)
    profile = session.get(ClinicProfile, clinic_id)
    if profile is None:
        return ClinicProfileRead(
            clinic_id=clinic_id, brand={}, audience={}, services={}, schedule={}, version=0, updated_at=None
        )
    return ClinicProfileRead.model_validate(profile)


def clinic_practitioners(session: Session, clinic_id: UUID) -> list[ClinicPractitionerRead]:
    _require_clinic(session, clinic_id)
    rows = session.execute(
        select(ClinicPractitioner, Practitioner)
        .join(Practitioner, Practitioner.id == ClinicPractitioner.practitioner_id)
        .where(ClinicPractitioner.clinic_id == clinic_id, ClinicPractitioner.is_active.is_(True))
        .order_by(ClinicPractitioner.is_primary.desc(), Practitioner.full_name)
    )
    return [link_read(link, p) for link, p in rows]


def online_profiles(session: Session, clinic_id: UUID) -> list[ClinicOnlineProfileRead]:
    _require_clinic(session, clinic_id)
    rows = session.scalars(
        select(ClinicOnlineProfile)
        .where(ClinicOnlineProfile.clinic_id == clinic_id)
        .order_by(ClinicOnlineProfile.platform)
    )
    return [ClinicOnlineProfileRead.model_validate(r) for r in rows]


def approved_photos(session: Session, clinic_id: UUID) -> list[PhotoRead]:
    """The database shows this role APPROVED photos only."""
    _require_clinic(session, clinic_id)
    rows = session.scalars(
        select(Photo).where(Photo.clinic_id == clinic_id).order_by(Photo.created_at.desc())
    )
    return [PhotoRead.model_validate(p) for p in rows]


def connected_accounts(session: Session, clinic_id: UUID) -> list[ConnectedAccountRead]:
    _require_clinic(session, clinic_id)
    rows = session.execute(
        select(*_ACCOUNT_COLUMNS)
        .where(ConnectedAccount.clinic_id == clinic_id)
        .order_by(ConnectedAccount.provider)
    ).mappings()
    return [ConnectedAccountRead.model_validate(dict(r)) for r in rows]


def connected_account_resources(session: Session, clinic_id: UUID) -> list[ConnectedAccountResourceRead]:
    _require_clinic(session, clinic_id)
    rows = session.scalars(
        select(ConnectedAccountResource)
        .where(ConnectedAccountResource.clinic_id == clinic_id)
        .order_by(ConnectedAccountResource.resource_type, ConnectedAccountResource.external_id)
    )
    return [ConnectedAccountResourceRead.model_validate(r) for r in rows]


# ---- Phase 1 for the SEO team: ACTIVE CLIENT clinics only ----

#: "Active client" = stage active_client and not archived. Every Phase 1 query uses this filter, so a
#: lead or an archived clinic is never counted, listed or returned.
_ACTIVE_CLIENT = (Clinic.stage == ClinicStage.ACTIVE_CLIENT, Clinic.is_active.is_(True))


def list_active_clinics(session: Session, *, limit: int, offset: int) -> Page[InternalActiveClinic]:
    """How many active client clinics there are, and one page of their ids and names."""
    total = session.scalar(select(func.count()).select_from(Clinic).where(*_ACTIVE_CLIENT)) or 0
    rows = session.execute(
        select(Clinic.id, Clinic.name)
        .where(*_ACTIVE_CLIENT)
        .order_by(Clinic.name, Clinic.id)
        .limit(limit)
        .offset(offset)
    )
    items = [InternalActiveClinic(clinic_id=clinic_id, name=name) for clinic_id, name in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


def clinic_nap(session: Session, clinic_id: UUID) -> InternalClinicNap:
    """Name, address, phone and website of one active client clinic.

    Not found, not an active client, or archived: the same 404, so a caller can't learn which.
    """
    row = session.execute(
        select(
            Clinic.id,
            Clinic.name,
            Clinic.address_line,
            Clinic.city,
            Clinic.state,
            Clinic.postal_code,
            Clinic.country,
            Clinic.phone,
            Clinic.website_url,
        ).where(Clinic.id == clinic_id, *_ACTIVE_CLIENT)
    ).first()
    if row is None:
        raise NotFoundError("Clinic not found")
    return InternalClinicNap(
        clinic_id=row.id,
        name=row.name,
        address=InternalClinicAddress(
            line=row.address_line,
            city=row.city,
            state=row.state,
            postal_code=row.postal_code,
            country=row.country,
        ),
        phone=row.phone,
        website_url=row.website_url,
    )


def _clinic_read(clinic: Clinic, org_name: str) -> InternalClinicRead:
    return InternalClinicRead(
        **ClinicRead.model_validate(clinic).model_dump(), client_organization_name=org_name
    )


def _require_clinic(session: Session, clinic_id: UUID) -> None:
    if session.scalar(select(Clinic.id).where(Clinic.id == clinic_id)) is None:
        raise NotFoundError("Clinic not found")
