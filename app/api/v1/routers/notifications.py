from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.rbac import Principal
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.schemas.common import Page
from app.schemas.work import NotificationRead
from app.services import work as service

router = APIRouter(prefix="/notifications", tags=["notifications"], responses=ERRORS)


@router.get("", response_model=Page[NotificationRead], summary="My in-app notifications")
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: Limit = 50,
    offset: Offset = 0,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Page[NotificationRead]:
    items, total = service.list_notifications(db, principal, unread_only, limit, offset)
    return Page[NotificationRead](items=items, total=total, limit=limit, offset=offset)


@router.post("/{notification_id}/read", response_model=NotificationRead)
def mark_read(
    notification_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> NotificationRead:
    return NotificationRead.model_validate(service.mark_notification_read(db, principal, notification_id))
