"""My own account: who am I, my profile, my photo, my notification switches."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.rbac import Principal
from app.dependencies.adapters import get_optional_storage, get_storage
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.integrations.storage import ObjectStorage
from app.schemas.auth import MeResponse
from app.schemas.common import UploadTicket
from app.schemas.users import (
    AvatarConfirm,
    AvatarUploadRequest,
    MeUpdate,
    NotificationPreferenceRead,
    NotificationPreferencesUpdate,
)
from app.services import users

router = APIRouter(prefix="/auth", tags=["auth"], responses=ERRORS)


@router.get("/me", response_model=MeResponse, summary="Who am I, and what can I do?")
def me(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    storage: ObjectStorage | None = Depends(get_optional_storage),
) -> MeResponse:
    """Sign-in happens in Cognito (email + password). This returns the platform view of the caller.

    No account, or a switched-off account → 403 ``account_disabled``."""
    return users.me(db, principal, storage)


@router.patch("/me", response_model=MeResponse, summary="Change my own name and phone")
def update_me(
    body: MeUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    storage: ObjectStorage | None = Depends(get_optional_storage),
) -> MeResponse:
    users.update_me(db, principal, body)
    return users.me(db, principal, storage)


@router.post(
    "/me/avatar/uploads", response_model=UploadTicket, summary="Profile photo, step 1: upload address"
)
def request_avatar_upload(
    body: AvatarUploadRequest,
    principal: Principal = Depends(get_principal),
    storage: ObjectStorage = Depends(get_storage),
) -> UploadTicket:
    """JPEG, PNG or WebP, at most 5 MB. PUT the file to ``upload_url`` with ``headers``, then confirm."""
    return users.request_avatar_upload(principal, body, storage)


@router.post("/me/avatar/confirm", status_code=status.HTTP_204_NO_CONTENT, summary="Profile photo, step 2")
def confirm_avatar(
    body: AvatarConfirm,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> None:
    users.confirm_avatar(db, principal, body, storage)


@router.delete("/me/avatar", status_code=status.HTTP_204_NO_CONTENT, summary="Remove my profile photo")
def remove_avatar(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> None:
    users.remove_avatar(db, principal)


@router.get("/me/notification-preferences", response_model=list[NotificationPreferenceRead])
def my_notification_preferences(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> list[NotificationPreferenceRead]:
    """Every category and channel. A switch nobody has touched is on."""
    return users.my_notification_preferences(db, principal)


@router.put("/me/notification-preferences", response_model=list[NotificationPreferenceRead])
def update_my_notification_preferences(
    body: NotificationPreferencesUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[NotificationPreferenceRead]:
    return users.update_my_notification_preferences(db, principal, body)
