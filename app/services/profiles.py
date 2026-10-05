"""Governed client profile: brand, audience, services, schedule + consents, approved assets, team."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.enums import ApprovalState, AssetStatus
from app.core.errors import ConflictError, NotFoundError
from app.core.rbac import ClinicContext, Permission
from app.models import ClinicProfile
from app.repositories.assets import AssetRepository
from app.repositories.profiles import ProfileRepository
from app.schemas.profiles import (
    AudienceSection,
    BrandSection,
    ClinicProfileRead,
    ClinicProfileUpdate,
    ConsentRead,
    ScheduleSection,
    ServicesSection,
)
from app.services import assets as asset_service
from app.services import audit
from app.services.clinics import list_team

SECTIONS = ("brand", "audience", "services", "schedule")
MAX_APPROVED_ASSETS_IN_PROFILE = 100


def _load(session: Session, ctx: ClinicContext) -> ClinicProfile:
    profile = ProfileRepository(session).get(ctx.clinic_id)
    if profile is None:
        raise NotFoundError("Profile not found")
    return profile


def get_profile(session: Session, ctx: ClinicContext) -> ClinicProfileRead:
    profile = _load(session, ctx)
    consents = ProfileRepository(session).consents_for_clinic(ctx.clinic_id)
    approved, _ = AssetRepository(session).list_for_clinic(
        ctx.clinic_id,
        status=AssetStatus.UPLOADED,
        approval_state=ApprovalState.APPROVED,
        clients_only=not ctx.can(Permission.REPORTS_WRITE),
        limit=MAX_APPROVED_ASSETS_IN_PROFILE,
    )
    return ClinicProfileRead(
        clinic_id=profile.clinic_id,
        version=profile.version,
        brand=BrandSection.model_validate(profile.brand or {}),
        audience=AudienceSection.model_validate(profile.audience or {}),
        services=ServicesSection.model_validate(profile.services or {}),
        schedule=ScheduleSection.model_validate(profile.schedule or {}),
        consents=[ConsentRead.model_validate(c) for c in consents],
        approved_assets=asset_service.to_reads(session, ctx, approved),
        team=list_team(session, ctx),
        updated_at=profile.updated_at,
    )


def update_profile(session: Session, ctx: ClinicContext, data: ClinicProfileUpdate) -> ClinicProfileRead:
    profile = _load(session, ctx)
    if profile.version != data.version:
        raise ConflictError(f"Profile changed since you loaded it (now version {profile.version}). Reload.")
    changed = []
    for section in SECTIONS:
        value = getattr(data, section)
        if value is not None:
            setattr(profile, section, value.model_dump(mode="json"))
            changed.append(section)
    if changed:
        profile.version += 1
        profile.updated_by_user_id = ctx.principal.user_id
        audit.record(
            session,
            actor=ctx.principal,
            action="profile.update",
            resource_type="clinic_profile",
            resource_id=ctx.clinic_id,
            clinic_id=ctx.clinic_id,
            details={"sections": changed, "version": profile.version},
        )
        session.commit()
    return get_profile(session, ctx)
