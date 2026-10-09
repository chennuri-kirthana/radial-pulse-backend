"""Portfolio Allocations: which Digital Success Manager looks after which Client Organization."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.rbac import Permission, Principal
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.dependencies.tenancy import platform_permission
from app.schemas.portfolio_allocations import PortfolioAllocationRead, PortfolioAllocationSet
from app.services import portfolio_allocations

router = APIRouter(prefix="/portfolio-allocations", tags=["portfolio allocations"], responses=ERRORS)
_admin = platform_permission(Permission.PORTFOLIO_ALLOCATIONS_MANAGE)


@router.get("", response_model=list[PortfolioAllocationRead], summary="Allocations I can see")
def list_allocations(
    client_organization_id: UUID | None = None,
    user_id: UUID | None = None,
    is_active: bool | None = None,
    _: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[PortfolioAllocationRead]:
    """Platform Administrator: all (also past DSMs). DSM: My Client Portfolio. Clinic people: the
    DSM of their own business."""
    return portfolio_allocations.list_allocations(
        db, client_organization_id=client_organization_id, user_id=user_id, is_active=is_active
    )


@router.put("/{client_organization_id}", response_model=PortfolioAllocationRead)
def set_allocation(
    client_organization_id: UUID,
    body: PortfolioAllocationSet,
    principal: Principal = Depends(_admin),
    db: Session = Depends(get_db),
) -> PortfolioAllocationRead:
    """Give the business to this DSM (the previous DSM's row stays, inactive). The new DSM gets a
    notification. The user must be a Digital Success Manager (else 409)."""
    return portfolio_allocations.set_allocation(db, principal, client_organization_id, body)


@router.delete("/{client_organization_id}", status_code=status.HTTP_204_NO_CONTENT)
def end_allocation(
    client_organization_id: UUID, principal: Principal = Depends(_admin), db: Session = Depends(get_db)
) -> None:
    """The business has no DSM any more (it becomes a new lead again: only the admin sees it)."""
    portfolio_allocations.end_allocation(db, principal, client_organization_id)
