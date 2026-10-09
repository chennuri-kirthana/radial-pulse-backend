"""The clinic profile (brand, audience, services, schedule) and where the clinic is online."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.rbac import ClinicContext
from app.models import ClinicOnlineProfile, ClinicProfile
from app.schemas.clinic_profiles import (
    ClinicOnlineProfileCreate,
    ClinicOnlineProfileRead,
    ClinicOnlineProfileUpdate,
    ClinicProfileRead,
    ClinicProfileUpdate,
)
from app.services import audit

#: discovered_by for profiles a person typed in (agents put their own name there)
ADDED_BY_A_PERSON = "manual"


# ------------------------------------------------------------------------------ clinic profile
def get_profile(session: Session, ctx: ClinicContext) -> ClinicProfileRead:
    profile = session.get(ClinicProfile, ctx.clinic_id)
    if profile is None:
        return ClinicProfileRead(
            clinic_id=ctx.clinic_id,
            brand={},
            audience={},
            services={},
            schedule={},
            version=0,
            updated_at=None,
        )
    return ClinicProfileRead.model_validate(profile)


def update_profile(session: Session, ctx: ClinicContext, body: ClinicProfileUpdate) -> ClinicProfileRead:
    """Replace the 4 sections. ``version`` stops two people overwriting each other's edits."""
    profile = session.get(ClinicProfile, ctx.clinic_id, with_for_update=True)
    current = profile.version if profile is not None else 0
    if body.version != current:
        raise ConflictError("Someone else saved this profile in the meantime. Reload it and try again.")
    sections = body.model_dump(exclude={"version"})
    if profile is None:
        profile = ClinicProfile(clinic_id=ctx.clinic_id, version=1, **sections)
        session.add(profile)
    else:
        for name, value in sections.items():
            setattr(profile, name, value)
        profile.version = current + 1
    session.flush()
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="clinic_profile.updated",
        resource_type="clinic_profile",
        resource_id=ctx.clinic_id,
        clinic_id=ctx.clinic_id,
        details={"version": profile.version},
    )
    session.commit()
    session.refresh(profile)
    return ClinicProfileRead.model_validate(profile)


# ------------------------------------------------------------------------------ online profiles
def list_online_profiles(session: Session, ctx: ClinicContext) -> list[ClinicOnlineProfileRead]:
    rows = session.scalars(
        select(ClinicOnlineProfile)
        .where(ClinicOnlineProfile.clinic_id == ctx.clinic_id)
        .order_by(ClinicOnlineProfile.platform, ClinicOnlineProfile.created_at)
    )
    return [ClinicOnlineProfileRead.model_validate(r) for r in rows]


def add_online_profile(
    session: Session, ctx: ClinicContext, body: ClinicOnlineProfileCreate
) -> ClinicOnlineProfileRead:
    row = ClinicOnlineProfile(clinic_id=ctx.clinic_id, discovered_by=ADDED_BY_A_PERSON, **body.model_dump())
    session.add(row)
    session.flush()  # the same cleaned URL twice for one platform: 409
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="clinic_online_profile.added",
        resource_type="clinic_online_profile",
        resource_id=row.id,
        clinic_id=ctx.clinic_id,
        details={"platform": body.platform.value},
    )
    session.commit()
    session.refresh(row)  # the database cleaned the URL
    return ClinicOnlineProfileRead.model_validate(row)


def update_online_profile(
    session: Session, ctx: ClinicContext, profile_id: UUID, body: ClinicOnlineProfileUpdate
) -> ClinicOnlineProfileRead:
    row = _online(session, ctx.clinic_id, profile_id)
    changes = body.model_dump(exclude_unset=True)
    for name, value in changes.items():
        setattr(row, name, value)
    session.flush()
    if changes:
        audit.record(
            session,
            actor_user_id=ctx.user_id,
            action="clinic_online_profile.updated",
            resource_type="clinic_online_profile",
            resource_id=row.id,
            clinic_id=ctx.clinic_id,
            details={"fields": sorted(changes), "verification": row.verification.value},
        )
    session.commit()
    return ClinicOnlineProfileRead.model_validate(row)


def remove_online_profile(session: Session, ctx: ClinicContext, profile_id: UUID) -> None:
    row = _online(session, ctx.clinic_id, profile_id)
    session.delete(row)
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="clinic_online_profile.removed",
        resource_type="clinic_online_profile",
        resource_id=profile_id,
        clinic_id=ctx.clinic_id,
        details={"platform": row.platform.value, "url": row.url},
    )
    session.commit()


def _online(session: Session, clinic_id: UUID, profile_id: UUID) -> ClinicOnlineProfile:
    row = session.get(ClinicOnlineProfile, profile_id)
    if row is None or row.clinic_id != clinic_id:
        raise NotFoundError("Online profile not found")
    return row
