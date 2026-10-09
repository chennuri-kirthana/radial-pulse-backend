"""My in-app notifications (each person sees only their own)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.rbac import Principal
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.schemas.collaboration import NotificationRead
from app.schemas.common import Page
from app.services import collaboration

router = APIRouter(prefix="/notifications", tags=["notifications"], responses=ERRORS)


@router.get("", response_model=Page[NotificationRead], summary="My notifications, newest first")
def list_notifications(
    unread_only: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Page[NotificationRead]:
    return collaboration.list_notifications(
        db, principal, unread_only=unread_only, limit=limit, offset=offset
    )


@router.post("/{notification_id}/read", response_model=NotificationRead)
def mark_read(
    notification_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> NotificationRead:
    return collaboration.mark_read(db, principal, notification_id)


@router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_read(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> None:
    collaboration.mark_all_read(db, principal)
