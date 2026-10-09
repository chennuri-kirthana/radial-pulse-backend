"""Improvement Work Items: tasks to fix Improvement Opportunities (or added by hand)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.enums import WorkItemStatus
from app.core.rbac import ClinicContext, Permission
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.schemas.improvement_work_items import (
    ImprovementWorkItemCreate,
    ImprovementWorkItemRead,
    ImprovementWorkItemUpdate,
)
from app.services import improvement_work_items as service

router = APIRouter(
    prefix="/clinics/{clinic_id}/improvement-work-items", tags=["improvement work items"], responses=ERRORS
)
_read = clinic_access(Permission.IMPROVEMENT_WORK_ITEMS_READ)
_manage = clinic_access(Permission.IMPROVEMENT_WORK_ITEMS_MANAGE)


@router.get("", response_model=list[ImprovementWorkItemRead], summary="Work items, by due date")
def list_work_items(
    status: WorkItemStatus | None = None,
    assignee_user_id: UUID | None = None,
    ctx: ClinicContext = Depends(_read),
    db: Session = Depends(get_db),
) -> list[ImprovementWorkItemRead]:
    """The clinic team sees all; a practitioner sees only the items assigned to him."""
    return service.list_work_items(db, ctx, status=status, assignee_user_id=assignee_user_id)


@router.post("", response_model=ImprovementWorkItemRead, status_code=status.HTTP_201_CREATED)
def create_work_item(
    body: ImprovementWorkItemCreate, ctx: ClinicContext = Depends(_manage), db: Session = Depends(get_db)
) -> ImprovementWorkItemRead:
    """DSM or Platform Administrator. The assignee must belong to the clinic (409) and is notified."""
    return service.create_work_item(db, ctx, body)


@router.get("/{item_id}", response_model=ImprovementWorkItemRead)
def get_work_item(
    item_id: UUID, ctx: ClinicContext = Depends(_read), db: Session = Depends(get_db)
) -> ImprovementWorkItemRead:
    return service.get_work_item(db, ctx, item_id)


@router.patch("/{item_id}", response_model=ImprovementWorkItemRead)
def update_work_item(
    item_id: UUID,
    body: ImprovementWorkItemUpdate,
    ctx: ClinicContext = Depends(_manage),
    db: Session = Depends(get_db),
) -> ImprovementWorkItemRead:
    """Status ``done`` sets ``completed_at``; any other status clears it."""
    return service.update_work_item(db, ctx, item_id, body)
