"""Settings screens.

* Platform settings (Admin → Settings → General): one row, readable by everyone signed in
  (e.g. the support email under Help & Support), changed only by Platform Administrators.
* Integrations (Admin → Settings → Integrations): what is set up in this environment. No secrets.
* My notifications (everyone → Settings → Notifications): on/off per category and channel.
* My profile photo (everyone → Settings → My Profile): presigned upload to ``users/{id}/avatar/``.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import ConnectionPlatform, NotificationCategory, NotificationChannel
from app.core.errors import DomainValidationError, NotFoundError
from app.core.rbac import Principal
from app.db.base import utcnow
from app.integrations.oauth import PLATFORM_LABELS, PLATFORM_PROVIDER, configured_providers
from app.integrations.storage import ObjectStorage
from app.models import NotificationPreference, PlatformSettings, User
from app.repositories.settings import SettingsRepository
from app.repositories.users import UserRepository
from app.schemas.settings import (
    AvatarConfirm,
    AvatarUploadRequest,
    AvatarUploadResponse,
    IntegrationsStatus,
    NotificationSetting,
    NotificationSettings,
    NotificationSettingsUpdate,
    PlatformIntegration,
    PlatformSettingsRead,
    PlatformSettingsUpdate,
)
from app.services import audit

AVATAR_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
AVATAR_MAX_BYTES = 5 * 1024 * 1024


# ------------------------------------------------------------------ platform settings
def _platform_row(session: Session) -> PlatformSettings:
    row = SettingsRepository(session).platform()
    if row is None:
        # Migration 0010 creates the row. Only the fast SQLite tests (no migrations) get here.
        row = PlatformSettings(id=1)
        session.add(row)
        session.flush()
    return row


def get_platform_settings(session: Session) -> PlatformSettingsRead:
    return PlatformSettingsRead.model_validate(_platform_row(session))


def update_platform_settings(
    session: Session, principal: Principal, data: PlatformSettingsUpdate
) -> PlatformSettingsRead:
    row = _platform_row(session)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(row, field, value)
    row.updated_by_user_id = principal.user_id
    audit.record(
        session,
        actor=principal,
        action="settings.platform_update",
        resource_type="platform_settings",
        resource_id="1",
        clinic_id=None,
        details={"fields": sorted(changes)},
    )
    session.commit()
    return PlatformSettingsRead.model_validate(row)


# ------------------------------------------------------------------ integrations
def integrations(settings: Settings) -> IntegrationsStatus:
    ready = configured_providers(settings)
    return IntegrationsStatus(
        connections=[
            PlatformIntegration(
                platform=p, label=PLATFORM_LABELS[p], configured=PLATFORM_PROVIDER[p] in ready
            )
            for p in ConnectionPlatform
        ],
        invite_email=settings.invite_email_backend,
        file_storage=bool(settings.s3_assets_bucket),
        archive="s3" if settings.archive_bucket else "local",
    )


# ------------------------------------------------------------------ my notification switches
def my_notification_settings(session: Session, principal: Principal) -> NotificationSettings:
    saved = {
        (p.category, p.channel): p.enabled
        for p in SettingsRepository(session).preferences_for(principal.user_id)
    }
    return NotificationSettings(
        items=[
            NotificationSetting(category=c, channel=ch, enabled=saved.get((c, ch), True))
            for c in NotificationCategory
            for ch in NotificationChannel
        ]
    )


def update_my_notification_settings(
    session: Session, principal: Principal, data: NotificationSettingsUpdate
) -> NotificationSettings:
    repo = SettingsRepository(session)
    for item in data.items:
        row = repo.preference(principal.user_id, item.category, item.channel)
        if row is None:
            repo.add(
                NotificationPreference(
                    user_id=principal.user_id,
                    category=item.category,
                    channel=item.channel,
                    enabled=item.enabled,
                )
            )
        else:
            row.enabled = item.enabled
    audit.record(
        session,
        actor=principal,
        action="user.notification_settings",
        resource_type="user",
        resource_id=principal.user_id,
        clinic_id=None,
        details={"changed": [f"{i.category.value}/{i.channel.value}={i.enabled}" for i in data.items]},
    )
    session.commit()
    return my_notification_settings(session, principal)


# ------------------------------------------------------------------ my profile photo
def _avatar_prefix(user_id: UUID) -> str:
    return f"users/{user_id}/avatar/"


def _me(session: Session, principal: Principal) -> User:
    user = UserRepository(session).get(principal.user_id)
    if user is None:  # pragma: no cover - the principal was just built from this row
        raise NotFoundError("User not found")
    return user


def request_avatar_upload(
    principal: Principal, data: AvatarUploadRequest, storage: ObjectStorage, settings: Settings
) -> AvatarUploadResponse:
    mime = data.mime_type.lower()
    if mime not in AVATAR_TYPES:
        raise DomainValidationError("Use a JPEG, PNG or WebP image")
    if data.size_bytes > AVATAR_MAX_BYTES:
        raise DomainValidationError("The photo must be 5 MB or smaller")
    key = f"{_avatar_prefix(principal.user_id)}{uuid.uuid4()}.{AVATAR_TYPES[mime]}"
    url, headers = storage.presign_put(key, mime, settings.s3_presign_ttl_seconds, data.size_bytes)
    return AvatarUploadResponse(
        upload_url=url,
        headers=headers,
        key=key,
        expires_at=utcnow() + timedelta(seconds=settings.s3_presign_ttl_seconds),
    )


def confirm_avatar(
    session: Session, principal: Principal, data: AvatarConfirm, storage: ObjectStorage
) -> None:
    if not data.key.startswith(_avatar_prefix(principal.user_id)) or ".." in data.key:
        raise DomainValidationError("This is not your upload")
    info = storage.head(data.key)
    if info is None:
        raise DomainValidationError("The photo was not uploaded yet")
    if info.size_bytes > AVATAR_MAX_BYTES or (info.content_type or "").lower() not in AVATAR_TYPES:
        storage.delete(data.key)
        raise DomainValidationError("The uploaded file is not a photo of 5 MB or less")
    user = _me(session, principal)
    previous = user.avatar_key
    user.avatar_key = data.key
    audit.record(
        session,
        actor=principal,
        action="user.avatar_update",
        resource_type="user",
        resource_id=user.id,
        clinic_id=None,
    )
    session.commit()
    if previous and previous != data.key:
        storage.delete(previous)


def remove_avatar(session: Session, principal: Principal, storage: ObjectStorage | None) -> None:
    user = _me(session, principal)
    previous = user.avatar_key
    if previous is None:
        return
    user.avatar_key = None
    audit.record(
        session,
        actor=principal,
        action="user.avatar_remove",
        resource_type="user",
        resource_id=user.id,
        clinic_id=None,
    )
    session.commit()
    if storage is not None:
        storage.delete(previous)
