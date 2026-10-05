"""Presence profiles: where the clinic is online (website, GBP, social, directories)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import PresenceVerification
from app.core.errors import ConflictError, NotFoundError
from app.core.rbac import ClinicContext
from app.models import PresenceProfile
from app.repositories.presence import PresenceRepository
from app.schemas.assessments import evidence_list
from app.schemas.presence import PresenceProfileCreate, PresenceProfileRead, PresenceProfileUpdate
from app.services import audit


def to_read(p: PresenceProfile) -> PresenceProfileRead:
    return PresenceProfileRead(
        id=p.id,
        clinic_id=p.clinic_id,
        platform=p.platform,
        url=p.url,
        external_id=p.external_id,
        display_name=p.display_name,
        verification=p.verification,
        confidence=float(p.confidence) if p.confidence is not None else None,
        discovered_by=p.discovered_by,
        evidence=evidence_list(p.evidence),
        verified_by_user_id=p.verified_by_user_id,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def list_profiles(session: Session, ctx: ClinicContext, limit: int, offset: int) -> tuple[list[Any], int]:
    rows, total = PresenceRepository(session).list_for_clinic(ctx.clinic_id, limit, offset)
    return [to_read(p) for p in rows], total


def add_profile(session: Session, ctx: ClinicContext, data: PresenceProfileCreate) -> PresenceProfileRead:
    profile = PresenceProfile(
        clinic_id=ctx.clinic_id,
        platform=data.platform,
        url=str(data.url),
        external_id=data.external_id,
        display_name=data.display_name,
        verification=PresenceVerification.CONFIRMED,  # a person asserted it
        discovered_by=f"user:{ctx.user_id}",
        verified_by_user_id=ctx.user_id,
    )
    session.add(profile)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("This profile is already recorded for the clinic") from exc
    audit.record(
        session,
        actor=ctx.principal,
        action="presence_profile.add",
        resource_type="presence_profile",
        resource_id=profile.id,
        clinic_id=ctx.clinic_id,
        details={"platform": data.platform.value},
    )
    session.commit()
    return to_read(profile)


def update_profile(
    session: Session, ctx: ClinicContext, profile_id: UUID, data: PresenceProfileUpdate
) -> PresenceProfileRead:
    profile = PresenceRepository(session).get_in_clinic(ctx.clinic_id, profile_id)
    if profile is None:
        raise NotFoundError("Presence profile not found")
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(profile, field, value)
    if "verification" in changes:
        profile.verified_by_user_id = ctx.user_id
    audit.record(
        session,
        actor=ctx.principal,
        action="presence_profile.update",
        resource_type="presence_profile",
        resource_id=profile.id,
        clinic_id=ctx.clinic_id,
        details={"fields": sorted(changes), "verification": profile.verification.value},
    )
    session.commit()
    return to_read(profile)
