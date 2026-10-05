"""Platform settings (Admin → Settings → General / Integrations).

Everyone signed in can READ the general settings (the apps show the support email under
Help & Support). Only Platform Administrators (``settings:manage``) change them or see Integrations.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.config import Settings
from app.core.rbac import Permission, Principal
from app.dependencies.adapters import settings_dependency
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.dependencies.tenancy import platform_permission
from app.schemas.settings import IntegrationsStatus, PlatformSettingsRead, PlatformSettingsUpdate
from app.services import settings as service

router = APIRouter(prefix="/settings", tags=["settings"], responses=ERRORS)


@router.get(
    "/platform", response_model=PlatformSettingsRead, summary="Organization name, support contact, timezone"
)
def get_platform_settings(
    _: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> PlatformSettingsRead:
    return service.get_platform_settings(db)


@router.patch("/platform", response_model=PlatformSettingsRead, summary="Change the general settings (Admin)")
def update_platform_settings(
    body: PlatformSettingsUpdate,
    principal: Principal = Depends(platform_permission(Permission.SETTINGS_MANAGE)),
    db: Session = Depends(get_db),
) -> PlatformSettingsRead:
    return service.update_platform_settings(db, principal, body)


@router.get(
    "/integrations", response_model=IntegrationsStatus, summary="Which outside services are set up (Admin)"
)
def integrations(
    _: Principal = Depends(platform_permission(Permission.SETTINGS_MANAGE)),
    settings: Settings = Depends(settings_dependency),
) -> IntegrationsStatus:
    return service.integrations(settings)
