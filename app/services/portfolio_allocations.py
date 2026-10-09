"""Portfolio Allocation: a whole Client Organization (all its clinics, also new branches) is given
to ONE active Digital Success Manager. Past DSMs stay as inactive rows. Only the Platform
Administrator allocates (docs/01-decisions.md section 3)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.enums import NotificationCategory
from app.core.errors import NotFoundError
from app.core.rbac import Principal
from app.models import ClientOrganization, PortfolioAllocation, User
from app.schemas.portfolio_allocations import PortfolioAllocationRead, PortfolioAllocationSet
from app.services import audit, notify


def _query() -> Select[PortfolioAllocation, ClientOrganization, User]:
    return (
        select(PortfolioAllocation, ClientOrganization, User)
        .join(ClientOrganization, ClientOrganization.id == PortfolioAllocation.client_organization_id)
        .join(User, User.id == PortfolioAllocation.user_id)
    )


def _read(alloc: PortfolioAllocation, org: ClientOrganization, user: User) -> PortfolioAllocationRead:
    return PortfolioAllocationRead(
        client_organization_id=org.id,
        client_organization_name=org.name,
        user_id=user.id,
        user_full_name=user.full_name,
        user_email=user.email,
        is_active=alloc.is_active,
        created_at=alloc.created_at,
        updated_at=alloc.updated_at,
    )


def list_allocations(
    session: Session, *, client_organization_id: UUID | None, user_id: UUID | None, is_active: bool | None
) -> list[PortfolioAllocationRead]:
    """What the caller may see: the admin all; a DSM his own (My Client Portfolio); clinic people
    the allocation of their own business."""
    query = _query()
    if client_organization_id is not None:
        query = query.where(PortfolioAllocation.client_organization_id == client_organization_id)
    if user_id is not None:
        query = query.where(PortfolioAllocation.user_id == user_id)
    if is_active is not None:
        query = query.where(PortfolioAllocation.is_active.is_(is_active))
    rows = session.execute(query.order_by(ClientOrganization.name, PortfolioAllocation.created_at.desc()))
    return [_read(alloc, org, user) for alloc, org, user in rows]


def set_allocation(
    session: Session, principal: Principal, client_organization_id: UUID, body: PortfolioAllocationSet
) -> PortfolioAllocationRead:
    """Allocate (or move) the business to ``body.user_id``. Same DSM again = no change."""
    org = session.get(ClientOrganization, client_organization_id)
    if org is None:
        raise NotFoundError("Client Organization not found")
    if session.get(User, body.user_id) is None:
        raise NotFoundError("User not found")
    current = session.scalar(
        select(PortfolioAllocation).where(
            PortfolioAllocation.client_organization_id == org.id, PortfolioAllocation.is_active.is_(True)
        )
    )
    if current is not None and current.user_id == body.user_id:
        return _get(session, org.id, body.user_id)

    previous_user_id = current.user_id if current is not None else None
    if current is not None:
        current.is_active = False  # the past DSM stays as an inactive row
        session.flush()  # only one active row per business: end the old one first
    row = session.get(PortfolioAllocation, (org.id, body.user_id))
    if row is None:
        session.add(PortfolioAllocation(client_organization_id=org.id, user_id=body.user_id))
    else:
        row.is_active = True
    session.flush()  # a user who is not a DSM fails here (trigger): 409
    audit.record(
        session,
        actor_user_id=principal.user_id,
        action="portfolio_allocation.created" if previous_user_id is None else "portfolio_allocation.changed",
        resource_type="client_organization",
        resource_id=org.id,
        clinic_id=None,
        details={
            "user_id": str(body.user_id),
            "previous_user_id": str(previous_user_id) if previous_user_id else None,
        },
    )
    notify.send(
        session,
        user_id=body.user_id,
        category=NotificationCategory.PORTFOLIO_ALLOCATED,
        title=f"{org.name} is now in your client portfolio",
        link=f"/client-organizations/{org.id}",
    )
    session.commit()
    return _get(session, org.id, body.user_id)


def end_allocation(session: Session, principal: Principal, client_organization_id: UUID) -> None:
    current = session.scalar(
        select(PortfolioAllocation).where(
            PortfolioAllocation.client_organization_id == client_organization_id,
            PortfolioAllocation.is_active.is_(True),
        )
    )
    if current is None:
        raise NotFoundError("This Client Organization has no active Digital Success Manager")
    current.is_active = False
    audit.record(
        session,
        actor_user_id=principal.user_id,
        action="portfolio_allocation.ended",
        resource_type="client_organization",
        resource_id=client_organization_id,
        clinic_id=None,
        details={"user_id": str(current.user_id)},
    )
    session.commit()


def _get(session: Session, org_id: UUID, user_id: UUID) -> PortfolioAllocationRead:
    row = session.execute(
        _query().where(
            PortfolioAllocation.client_organization_id == org_id, PortfolioAllocation.user_id == user_id
        )
    ).one()
    return _read(*row)
