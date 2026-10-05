from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.config import Settings
from app.core.rbac import Principal
from app.dependencies.adapters import get_optional_storage, get_storage, settings_dependency
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.integrations.storage import ObjectStorage
from app.schemas.auth import MeResponse
from app.schemas.settings import (
    AvatarConfirm,
    AvatarUploadRequest,
    AvatarUploadResponse,
    NotificationSettings,
    NotificationSettingsUpdate,
)
from app.schemas.users import MeUpdate
from app.services import identity, users
from app.services import settings as settings_service

router = APIRouter(prefix="/auth", tags=["auth"], responses=ERRORS)


@router.get("/me", response_model=MeResponse, summary="Who am I, and what can I do?")
def me(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    storage: ObjectStorage | None = Depends(get_optional_storage),
) -> MeResponse:
    """Sign-in happens in Cognito (Hosted UI, Google, PKCE). This returns the platform view of the caller."""
    return identity.me(db, principal, storage)


@router.patch(
    "/me", response_model=MeResponse, summary="Update my own name and phone (Settings → My Profile)"
)
def update_me(
    body: MeUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    storage: ObjectStorage | None = Depends(get_optional_storage),
) -> MeResponse:
    users.update_me(db, principal, body)
    return identity.me(db, principal, storage)


# ---------------------------------------------------------------- Settings → My Profile (photo)
@router.post(
    "/me/avatar/uploads",
    response_model=AvatarUploadResponse,
    summary="Profile photo, step 1: get an upload address (JPEG/PNG/WebP, max 5 MB)",
)
def request_avatar_upload(
    body: AvatarUploadRequest,
    principal: Principal = Depends(get_principal),
    storage: ObjectStorage = Depends(get_storage),
    settings: Settings = Depends(settings_dependency),
) -> AvatarUploadResponse:
    return settings_service.request_avatar_upload(principal, body, storage, settings)


@router.post(
    "/me/avatar/confirm", response_model=MeResponse, summary="Profile photo, step 2: use the uploaded photo"
)
def confirm_avatar(
    body: AvatarConfirm,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> MeResponse:
    settings_service.confirm_avatar(db, principal, body, storage)
    return identity.me(db, principal, storage)


@router.delete("/me/avatar", response_model=MeResponse, summary="Remove my profile photo")
def remove_avatar(
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
    storage: ObjectStorage | None = Depends(get_optional_storage),
) -> MeResponse:
    settings_service.remove_avatar(db, principal, storage)
    return identity.me(db, principal, storage)


# ---------------------------------------------------------------- Settings → Notifications
@router.get(
    "/me/notification-settings",
    response_model=NotificationSettings,
    summary="My notification switches (every category and channel)",
)
def my_notification_settings(
    principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> NotificationSettings:
    return settings_service.my_notification_settings(db, principal)


@router.put(
    "/me/notification-settings",
    response_model=NotificationSettings,
    status_code=status.HTTP_200_OK,
    summary="Change some of my notification switches",
)
def update_my_notification_settings(
    body: NotificationSettingsUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> NotificationSettings:
    return settings_service.update_my_notification_settings(db, principal, body)
