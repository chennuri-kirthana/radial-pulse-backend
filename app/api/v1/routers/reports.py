from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.rbac import ClinicContext, Permission
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.schemas.common import Page
from app.schemas.reporting import ReportArtifactCreate, ReportArtifactRead
from app.services import reporting as service

router = APIRouter(prefix="/clinics/{clinic_id}/reports", tags=["reports"], responses=ERRORS)


@router.get("", response_model=Page[ReportArtifactRead], summary="Clinic users only see PUBLISHED reports")
def list_reports(
    report_type: str | None = Query(default=None, max_length=64),
    limit: Limit = 50,
    offset: Offset = 0,
    ctx: ClinicContext = Depends(clinic_access(Permission.REPORTS_READ)),
    db: Session = Depends(get_db),
) -> Page[ReportArtifactRead]:
    items, total = service.list_reports(db, ctx, report_type, limit, offset)
    return Page[ReportArtifactRead](items=items, total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=ReportArtifactRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a report version",
)
def create_report(
    body: ReportArtifactCreate,
    ctx: ClinicContext = Depends(clinic_access(Permission.REPORTS_WRITE)),
    db: Session = Depends(get_db),
) -> ReportArtifactRead:
    return ReportArtifactRead.model_validate(service.create_report(db, ctx, body))


@router.get("/{report_id}", response_model=ReportArtifactRead)
def get_report(
    report_id: UUID,
    ctx: ClinicContext = Depends(clinic_access(Permission.REPORTS_READ)),
    db: Session = Depends(get_db),
) -> ReportArtifactRead:
    return ReportArtifactRead.model_validate(service.get_report(db, ctx, report_id))
