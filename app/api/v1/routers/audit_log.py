from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.rbac import ClinicContext, Permission
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.schemas.common import Page
from app.schemas.governance import AuditEventRead
from app.services import governance as service

router = APIRouter(prefix="/clinics/{clinic_id}/audit-events", tags=["audit-log"], responses=ERRORS)


@router.get("", response_model=Page[AuditEventRead], summary="Who did what in this clinic (append-only)")
def list_audit_events(
    limit: Limit = 50,
    offset: Offset = 0,
    ctx: ClinicContext = Depends(clinic_access(Permission.AUDIT_LOG_READ)),
    db: Session = Depends(get_db),
) -> Page[AuditEventRead]:
    items, total = service.list_audit_events(db, ctx, limit, offset)
    return Page[AuditEventRead](items=items, total=total, limit=limit, offset=offset)
