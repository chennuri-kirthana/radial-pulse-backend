"""The "Practitioner Profile" screen: one read, one Edit (docs/01-decisions.md section 14)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.rbac import ClinicContext, Permission
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.schemas.practitioner_profile import PractitionerProfileRead, PractitionerProfileUpdate
from app.services import practitioner_profile

router = APIRouter(
    prefix="/clinics/{clinic_id}/practitioner-profile", tags=["practitioner profile"], responses=ERRORS
)
_read = clinic_access(Permission.CLINIC_PRACTITIONERS_READ)


@router.get("", response_model=PractitionerProfileRead)
def get_profile(
    practitioner_id: UUID | None = None, ctx: ClinicContext = Depends(_read), db: Session = Depends(get_db)
) -> PractitionerProfileRead:
    """The clinic's main practitioner (or ``practitioner_id``; a practitioner sees his own).
    The 7 days come Monday..Sunday; empty values are null ("Not provided")."""
    return practitioner_profile.get_profile(db, ctx, practitioner_id)


@router.patch("/{practitioner_id}", response_model=PractitionerProfileRead)
def update_profile(
    practitioner_id: UUID,
    body: PractitionerProfileUpdate,
    ctx: ClinicContext = Depends(_read),
    db: Session = Depends(get_db),
) -> PractitionerProfileRead:
    """Edit. ``practitioner``: the practitioner himself, the DSM, the admin (not a Clinic
    Administrator). ``clinic_practitioner`` (schedule, holiday, fee, time zone, notes): admin, DSM,
    Clinic Administrator (not the practitioner → 403). Bad values → 400 with ``fields``."""
    return practitioner_profile.update_profile(db, ctx, practitioner_id, body)
