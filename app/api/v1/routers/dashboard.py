from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.rbac import Principal
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.schemas.dashboard import DashboardSummary
from app.services import dashboard as service

router = APIRouter(prefix="/dashboard", tags=["dashboard"], responses=ERRORS)


@router.get(
    "/summary",
    response_model=DashboardSummary,
    summary="Dashboard tiles and charts (Admin: all clinics; DSM: their clinics)",
)
def dashboard_summary(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> DashboardSummary:
    return service.summary(db, principal)
