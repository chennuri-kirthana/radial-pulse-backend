"""Clinics: list, new leads, details, stage, archive / restore, stage history."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.enums import ClinicStage
from app.core.rbac import ClinicContext, Permission, Principal
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access, platform_permission
from app.schemas.clinics import (
    ClinicArchive,
    ClinicCreate,
    ClinicRead,
    ClinicStageChangeRead,
    ClinicStageUpdate,
    ClinicUpdate,
)
from app.schemas.common import Page
from app.services import clinics

router = APIRouter(prefix="/clinics", tags=["clinics"], responses=ERRORS)


@router.get("", response_model=Page[ClinicRead], summary="The clinics I can see")
def list_clinics(
    q: str | None = Query(default=None, max_length=200, description="Search name or city"),
    stage: ClinicStage | None = None,
    is_active: bool | None = None,
    client_organization_id: UUID | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
    _: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Page[ClinicRead]:
    """Platform Administrator: every clinic (new leads too). DSM: the clinics of My Client Portfolio.
    Clinic people and practitioners: their own clinics."""
    return clinics.list_clinics(
        db,
        q=q,
        stage=stage,
        is_active=is_active,
        client_organization_id=client_organization_id,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=ClinicRead, status_code=status.HTTP_201_CREATED, summary="Add a new lead")
def create_clinic(
    body: ClinicCreate,
    principal: Principal = Depends(platform_permission(Permission.CLIENT_ORGANIZATIONS_MANAGE)),
    db: Session = Depends(get_db),
) -> ClinicRead:
    """Platform Administrator only. Without ``client_organization_id`` the business is created in
    the same step (named ``client_organization_name``, or the clinic's name)."""
    return clinics.create_clinic(db, principal, body)


@router.get("/{clinic_id}", response_model=ClinicRead)
def get_clinic(
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_READ)), db: Session = Depends(get_db)
) -> ClinicRead:
    return clinics.get_clinic(db, ctx)


@router.patch("/{clinic_id}", response_model=ClinicRead, summary="Edit clinic details")
def update_clinic(
    body: ClinicUpdate,
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_WRITE)),
    db: Session = Depends(get_db),
) -> ClinicRead:
    return clinics.update_clinic(db, ctx, body)


@router.post("/{clinic_id}/stage", response_model=ClinicRead, summary="Move the clinic to another stage")
def change_stage(
    body: ClinicStageUpdate,
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_MANAGE)),
    db: Session = Depends(get_db),
) -> ClinicRead:
    return clinics.change_stage(db, ctx, body)


@router.get("/{clinic_id}/clinic-stage-changes", response_model=list[ClinicStageChangeRead])
def stage_changes(
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_MANAGE)), db: Session = Depends(get_db)
) -> list[ClinicStageChangeRead]:
    """Stage history, newest first (Platform Administrator and DSM)."""
    return clinics.stage_changes(db, ctx)


@router.post("/{clinic_id}/archive", response_model=ClinicRead)
def archive_clinic(
    body: ClinicArchive,
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_MANAGE)),
    db: Session = Depends(get_db),
) -> ClinicRead:
    return clinics.archive_clinic(db, ctx, body)


@router.post("/{clinic_id}/restore", response_model=ClinicRead)
def restore_clinic(
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_MANAGE)), db: Session = Depends(get_db)
) -> ClinicRead:
    return clinics.restore_clinic(db, ctx)
