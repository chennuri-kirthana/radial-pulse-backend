"""Platform settings, the clinic audit log, and the dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.rbac import ClinicContext, Permission, Principal
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access, platform_permission
from app.schemas.common import Page
from app.schemas.settings import (
    AuditEventRead,
    DashboardSummary,
    PlatformSettingsRead,
    PlatformSettingsUpdate,
)
from app.services import settings

router = APIRouter(tags=["settings"], responses=ERRORS)


@router.get("/platform-settings", response_model=PlatformSettingsRead)
def get_platform_settings(
    _: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> PlatformSettingsRead:
    """Everyone signed in reads them."""
    return settings.get_platform_settings(db)


@router.patch("/platform-settings", response_model=PlatformSettingsRead)
def update_platform_settings(
    body: PlatformSettingsUpdate,
    principal: Principal = Depends(platform_permission(Permission.PLATFORM_SETTINGS_MANAGE)),
    db: Session = Depends(get_db),
) -> PlatformSettingsRead:
    """Platform Administrator only."""
    return settings.update_platform_settings(db, principal, body)


@router.get(
    "/clinics/{clinic_id}/audit-events", response_model=Page[AuditEventRead], summary="Clinic activity log"
)
def list_audit_events(
    action: str | None = Query(default=None, max_length=64),
    limit: Limit = 50,
    offset: Offset = 0,
    ctx: ClinicContext = Depends(clinic_access(Permission.AUDIT_EVENTS_READ)),
    db: Session = Depends(get_db),
) -> Page[AuditEventRead]:
    """Admin, the DSM and the Clinic Administrator. Newest first. Nobody can change it."""
    return settings.list_audit_events(db, ctx, action=action, limit=limit, offset=offset)


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> DashboardSummary:
    """Counts over the clinics, work items, photos and reports the caller can see."""
    return settings.dashboard(db, principal)
