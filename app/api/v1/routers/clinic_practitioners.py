"""Clinic practitioners: which practitioners work at a clinic, and that clinic's details for them."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.rbac import ClinicContext, Permission
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.schemas.practitioners import (
    ClinicPractitionerCreate,
    ClinicPractitionerRead,
    ClinicPractitionerUpdate,
    PractitionerLookup,
)
from app.services import practitioners

router = APIRouter(
    prefix="/clinics/{clinic_id}/clinic-practitioners", tags=["clinic practitioners"], responses=ERRORS
)
_read = clinic_access(Permission.CLINIC_PRACTITIONERS_READ)
_manage = clinic_access(Permission.CLINIC_PRACTITIONERS_MANAGE)


@router.get("", response_model=list[ClinicPractitionerRead])
def list_links(
    include_inactive: bool = False, ctx: ClinicContext = Depends(_read), db: Session = Depends(get_db)
) -> list[ClinicPractitionerRead]:
    """Primary practitioner first."""
    return practitioners.list_links(db, ctx, include_inactive=include_inactive)


@router.get("/lookup", response_model=PractitionerLookup | None, summary="Find by registration number")
def lookup(
    registration_number: str = Query(min_length=1, max_length=64),
    _: ClinicContext = Depends(_manage),
    db: Session = Depends(get_db),
) -> PractitionerLookup | None:
    """Before adding a new practitioner, look for an existing one (also from another business) and
    link it instead of creating a copy. ``null`` = not found."""
    return practitioners.lookup(db, registration_number)


@router.post("", response_model=ClinicPractitionerRead, status_code=status.HTTP_201_CREATED)
def add_link(
    body: ClinicPractitionerCreate, ctx: ClinicContext = Depends(_manage), db: Session = Depends(get_db)
) -> ClinicPractitionerRead:
    """Link an existing practitioner (``practitioner_id``) or create a new one (``practitioner``)."""
    return practitioners.add_link(db, ctx, body)


@router.get("/{practitioner_id}", response_model=ClinicPractitionerRead)
def get_link(
    practitioner_id: UUID, ctx: ClinicContext = Depends(_read), db: Session = Depends(get_db)
) -> ClinicPractitionerRead:
    return practitioners.get_link(db, ctx, practitioner_id)


@router.patch("/{practitioner_id}", response_model=ClinicPractitionerRead, summary="This clinic's details")
def update_link(
    practitioner_id: UUID,
    body: ClinicPractitionerUpdate,
    ctx: ClinicContext = Depends(_manage),
    db: Session = Depends(get_db),
) -> ClinicPractitionerRead:
    """Schedule, weekly holiday, fee, time zone, notes, primary, active. Not the practitioner himself."""
    return practitioners.update_link(db, ctx, practitioner_id, body)
