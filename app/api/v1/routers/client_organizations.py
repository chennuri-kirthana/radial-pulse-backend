"""Client Organizations (the businesses). Created and renamed by the Platform Administrator."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.rbac import Permission, Principal
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.dependencies.tenancy import platform_permission
from app.schemas.clinics import ClientOrganizationCreate, ClientOrganizationRead, ClientOrganizationUpdate
from app.schemas.common import Page
from app.services import clinics

router = APIRouter(prefix="/client-organizations", tags=["client organizations"], responses=ERRORS)
_admin = platform_permission(Permission.CLIENT_ORGANIZATIONS_MANAGE)


@router.get("", response_model=Page[ClientOrganizationRead], summary="The businesses I can see")
def list_client_organizations(
    q: str | None = Query(default=None, max_length=200),
    limit: Limit = 50,
    offset: Offset = 0,
    _: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Page[ClientOrganizationRead]:
    return clinics.list_client_organizations(db, q=q, limit=limit, offset=offset)


@router.post("", response_model=ClientOrganizationRead, status_code=status.HTTP_201_CREATED)
def create_client_organization(
    body: ClientOrganizationCreate, principal: Principal = Depends(_admin), db: Session = Depends(get_db)
) -> ClientOrganizationRead:
    return clinics.create_client_organization(db, principal, body)


@router.get("/{client_organization_id}", response_model=ClientOrganizationRead)
def get_client_organization(
    client_organization_id: UUID, _: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> ClientOrganizationRead:
    return clinics.get_client_organization(db, client_organization_id)


@router.patch("/{client_organization_id}", response_model=ClientOrganizationRead)
def update_client_organization(
    client_organization_id: UUID,
    body: ClientOrganizationUpdate,
    principal: Principal = Depends(_admin),
    db: Session = Depends(get_db),
) -> ClientOrganizationRead:
    return clinics.update_client_organization(db, principal, client_organization_id, body)
