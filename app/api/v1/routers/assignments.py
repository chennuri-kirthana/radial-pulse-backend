"""Portfolio Allocation: which Digital Success Manager looks after a clinic. ONE at a time."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.rbac import ClinicContext, Permission, Principal
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access, platform_permission
from app.schemas.clinics import AssignmentRead, AssignmentSet
from app.services import clinics as service

router = APIRouter(prefix="/clinics/{clinic_id}", tags=["assignments"], responses=ERRORS)


@router.get(
    "/assignments",
    response_model=list[AssignmentRead],
    summary="The clinic's DSM now (is_active=true) and before (history)",
)
def list_assignments(
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_READ)), db: Session = Depends(get_db)
) -> list[AssignmentRead]:
    return [AssignmentRead.model_validate(a) for a in service.list_assignments(db, ctx)]


@router.put(
    "/assignment",
    response_model=AssignmentRead,
    summary='Set the clinic\'s DSM ("Update Assignment"). Replaces the current one',
)
def set_assignment(
    body: AssignmentSet,
    clinic_id: UUID = Path(),
    principal: Principal = Depends(platform_permission(Permission.ASSIGNMENTS_MANAGE)),
    db: Session = Depends(get_db),
) -> AssignmentRead:
    return AssignmentRead.model_validate(service.set_assignment(db, principal, clinic_id, body))


@router.delete(
    "/assignment",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Leave the clinic without a DSM",
)
def end_assignment(
    clinic_id: UUID = Path(),
    principal: Principal = Depends(platform_permission(Permission.ASSIGNMENTS_MANAGE)),
    db: Session = Depends(get_db),
) -> Response:
    service.end_assignment(db, principal, clinic_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
