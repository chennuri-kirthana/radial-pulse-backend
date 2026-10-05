"""Practitioners (doctors and other professionals) of a clinic. Records, not logins.

One practitioner record per person per business; the same doctor can be linked to several
branches (clinic_practitioners)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.rbac import ClinicContext, Permission
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.schemas.clinics import PractitionerCreate, PractitionerRead, PractitionerUpdate
from app.schemas.common import Page
from app.services import clinics as service

router = APIRouter(prefix="/clinics/{clinic_id}/practitioners", tags=["practitioners"], responses=ERRORS)


@router.get("", response_model=Page[PractitionerRead], summary="Practitioners (main one first)")
def list_practitioners(
    limit: Limit = 50,
    offset: Offset = 0,
    ctx: ClinicContext = Depends(clinic_access(Permission.PRACTITIONERS_READ)),
    db: Session = Depends(get_db),
) -> Page[PractitionerRead]:
    items, total = service.list_practitioners(db, ctx, limit, offset)
    return Page[PractitionerRead](items=items, total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=PractitionerRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new practitioner, or link one from another branch of the same business",
)
def create_practitioner(
    body: PractitionerCreate,
    ctx: ClinicContext = Depends(clinic_access(Permission.PRACTITIONERS_WRITE)),
    db: Session = Depends(get_db),
) -> PractitionerRead:
    return service.create_practitioner(db, ctx, body)


@router.patch(
    "/{practitioner_id}",
    response_model=PractitionerRead,
    summary="Edit the person (all branches) or their main/active flags at THIS clinic",
)
def update_practitioner(
    practitioner_id: UUID,
    body: PractitionerUpdate,
    ctx: ClinicContext = Depends(clinic_access(Permission.PRACTITIONERS_WRITE)),
    db: Session = Depends(get_db),
) -> PractitionerRead:
    return service.update_practitioner(db, ctx, practitioner_id, body)
