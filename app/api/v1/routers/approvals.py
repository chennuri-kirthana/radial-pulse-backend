from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.enums import ApprovalState
from app.core.errors import ProblemDetails
from app.core.rbac import ClinicContext, Permission
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.schemas.common import Page
from app.schemas.governance import ApprovalActionRequest, ApprovalRead
from app.services import governance as service

router = APIRouter(prefix="/clinics/{clinic_id}/approvals", tags=["approvals"], responses=ERRORS)


@router.post(
    "/actions",
    response_model=ApprovalRead,
    summary="submit / approve / reject / redo / publish / handoff",
    responses={409: {"model": ProblemDetails, "description": "Action not allowed in the current state"}},
)
def apply_action(
    body: ApprovalActionRequest,
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_READ)),
    db: Session = Depends(get_db),
) -> ApprovalRead:
    """The per-action permission (e.g. approvals:decide, media:review) is checked by the service.

    ``comment`` is an internal note (Radial Pulse staff only); ``clinic_message`` is what the
    clinic reads (e.g. why a photo must be retaken)."""
    return service.to_read(db, ctx, service.apply_action(db, ctx, body))


@router.get("", response_model=Page[ApprovalRead])
def list_approvals(
    state: ApprovalState | None = Query(default=None),
    resource_type: str | None = Query(default=None, max_length=64, description="e.g. asset"),
    limit: Limit = 50,
    offset: Offset = 0,
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_READ)),
    db: Session = Depends(get_db),
) -> Page[ApprovalRead]:
    items, total = service.list_approvals(db, ctx, state, limit, offset, resource_type)
    return Page[ApprovalRead](items=service.to_reads(db, ctx, items), total=total, limit=limit, offset=offset)


@router.get("/{approval_id}", response_model=ApprovalRead)
def get_approval(
    approval_id: UUID,
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_READ)),
    db: Session = Depends(get_db),
) -> ApprovalRead:
    return service.to_read(db, ctx, service.get_approval(db, ctx, approval_id))
