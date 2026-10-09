"""People: "who am I", my profile and switches, and the Platform Administrator's user list.

Invites: a person is created here first (``users`` row), then the Cognito account. On their first
sign-in ``rp_user_for_login`` links the two by email. Clinic-level invites (by a DSM or Clinic
Administrator) go through clinic members / clinic practitioners, which call ``create_invited``.
"""

from __future__ import annotations

import logging
import uuid
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.enums import NotificationCategory, NotificationChannel, PlatformRole
from app.core.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    UnauthorizedError,
    UpstreamError,
)
from app.core.rbac import Principal
from app.integrations.identity_directory import AlreadySignedUpError, IdentityDirectory
from app.integrations.storage import ObjectStorage
from app.models import NotificationPreference, User
from app.schemas.auth import ClinicAccess, MeResponse
from app.schemas.common import Page, UploadTicket
from app.schemas.users import (
    AvatarConfirm,
    AvatarUploadRequest,
    MeUpdate,
    NotificationPreferenceRead,
    NotificationPreferencesUpdate,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services import audit, uploads

logger = logging.getLogger(__name__)

#: How long the profile-photo link in /auth/me works.
AVATAR_URL_TTL_SECONDS = 300
AVATAR_FILES = uploads.FileRule(
    types={"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}, max_bytes=5 * 1024 * 1024
)


def to_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        platform_role=user.platform_role,
        is_active=user.is_active,
        has_signed_in=user.cognito_sub is not None,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


# ------------------------------------------------------------------------------ who am I
def me(session: Session, principal: Principal, storage: ObjectStorage | None = None) -> MeResponse:
    user = session.get(User, principal.user_id)
    if user is None:  # pragma: no cover - the principal was just built from this row
        raise UnauthorizedError()
    visible = principal.visible_clinic_ids() or frozenset()
    clinics = [
        ClinicAccess(
            clinic_id=cid,
            clinic_member_role=principal.clinic_roles.get(cid),
            is_digital_success_manager=cid in principal.dsm_clinic_ids,
            is_practitioner=cid in principal.practitioner_clinic_ids,
            permissions=sorted(principal.clinic_permissions(cid)),
        )
        for cid in sorted(visible, key=str)
    ]
    avatar_url = None
    if storage is not None and user.avatar_key:
        avatar_url = storage.presign_get(user.avatar_key, AVATAR_URL_TTL_SECONDS)
        # Every view link of a private file is audited (CLAUDE.md rule 11).
        audit.record(
            session,
            actor_user_id=user.id,
            action="user.avatar_viewed",
            resource_type="user",
            resource_id=user.id,
            clinic_id=None,
        )
        session.commit()
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        platform_role=user.platform_role,
        permissions=sorted(principal.global_permissions()),
        clinics=clinics,
        all_clinics=principal.is_platform_administrator,
        practitioner_id=principal.practitioner_id,
        avatar_url=avatar_url,
        last_login_at=user.last_login_at,
    )


def update_me(session: Session, principal: Principal, body: MeUpdate) -> None:
    user = _get(session, principal.user_id)
    changes = body.model_dump(exclude_unset=True)
    for name, value in changes.items():
        setattr(user, name, value)
    if changes:
        audit.record(
            session,
            actor_user_id=principal.user_id,
            action="user.updated",
            resource_type="user",
            resource_id=user.id,
            clinic_id=None,
            details={"fields": sorted(changes)},
        )
    session.commit()


# ------------------------------------------------------------------------------ my photo
def request_avatar_upload(
    principal: Principal, body: AvatarUploadRequest, storage: ObjectStorage
) -> UploadTicket:
    ext = AVATAR_FILES.check(body.content_type, body.size_bytes)
    key = f"users/{principal.user_id}/avatar/{uuid.uuid4()}.{ext}"
    return uploads.ticket(storage, key, body.content_type, body.size_bytes)


def confirm_avatar(
    session: Session, principal: Principal, body: AvatarConfirm, storage: ObjectStorage
) -> None:
    if not body.key.startswith(f"users/{principal.user_id}/avatar/"):
        raise InvalidRequestError(
            "This is not your upload.", fields={"key": "Use the key from the upload step."}
        )
    AVATAR_FILES.check(body.content_type, body.size_bytes)
    uploads.check_uploaded(storage, body.key, body.size_bytes, body.content_type)
    user = _get(session, principal.user_id)
    user.avatar_key = body.key
    audit.record(
        session,
        actor_user_id=principal.user_id,
        action="user.avatar_changed",
        resource_type="user",
        resource_id=user.id,
        clinic_id=None,
    )
    session.commit()


def remove_avatar(session: Session, principal: Principal) -> None:
    user = _get(session, principal.user_id)
    if user.avatar_key is not None:
        user.avatar_key = None
        audit.record(
            session,
            actor_user_id=principal.user_id,
            action="user.avatar_removed",
            resource_type="user",
            resource_id=user.id,
            clinic_id=None,
        )
    session.commit()


# ------------------------------------------------------------------- my notification switches
def my_notification_preferences(session: Session, principal: Principal) -> list[NotificationPreferenceRead]:
    """Every category and channel. No row = on."""
    stored = {
        (p.category, p.channel): p.is_enabled
        for p in session.scalars(
            select(NotificationPreference).where(NotificationPreference.user_id == principal.user_id)
        )
    }
    return [
        NotificationPreferenceRead(category=cat, channel=ch, is_enabled=stored.get((cat, ch), True))
        for cat in NotificationCategory
        for ch in NotificationChannel
    ]


def update_my_notification_preferences(
    session: Session, principal: Principal, body: NotificationPreferencesUpdate
) -> list[NotificationPreferenceRead]:
    for item in body.items:
        row = session.get(NotificationPreference, (principal.user_id, item.category, item.channel))
        if row is None:
            session.add(
                NotificationPreference(
                    user_id=principal.user_id,
                    category=item.category,
                    channel=item.channel,
                    is_enabled=item.is_enabled,
                )
            )
        else:
            row.is_enabled = item.is_enabled
    audit.record(
        session,
        actor_user_id=principal.user_id,
        action="notification_preference.updated",
        resource_type="user",
        resource_id=principal.user_id,
        clinic_id=None,
        details={"changes": [i.model_dump(mode="json") for i in body.items]},
    )
    session.commit()
    return my_notification_preferences(session, principal)


# ------------------------------------------------------------------- users (Platform Administrator)
def list_users(
    session: Session,
    *,
    q: str | None,
    platform_role: PlatformRole | None,
    is_active: bool | None,
    limit: int,
    offset: int,
) -> Page[UserRead]:
    query = select(User)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(User.email.ilike(like), User.full_name.ilike(like)))
    if platform_role is not None:
        query = query.where(User.platform_role == platform_role)
    if is_active is not None:
        query = query.where(User.is_active.is_(is_active))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(User.email).limit(limit).offset(offset))
    return Page(items=[to_read(u) for u in rows], total=total, limit=limit, offset=offset)


def get_user(session: Session, user_id: UUID) -> UserRead:
    return to_read(_get(session, user_id))


def create_invited(
    session: Session,
    *,
    actor_user_id: UUID,
    email: str,
    full_name: str | None,
    platform_role: PlatformRole,
    directory: IdentityDirectory,
    phone: str | None = None,
    clinic_id: UUID | None = None,
) -> User:
    """Add an invited person and create their Cognito account. Does NOT commit (the caller adds
    links in the same transaction). The database decides who may invite which role."""
    user = User(email=email, full_name=full_name, phone=phone, platform_role=platform_role)
    session.add(user)
    session.flush()  # an existing email fails here: 409
    audit.record(
        session,
        actor_user_id=actor_user_id,
        action="user.invited",
        resource_type="user",
        resource_id=user.id,
        clinic_id=clinic_id,
        details={"platform_role": platform_role.value},
    )
    try:
        directory.invite(email, full_name)
    except Exception as exc:  # Cognito refused or is unreachable: nothing is saved (rollback)
        logger.warning("invite failed", extra={"exc_class": exc.__class__.__name__})
        raise UpstreamError("The sign-in account could not be created. Please try again.") from exc
    return user


def invite_user(
    session: Session, principal: Principal, body: UserCreate, directory: IdentityDirectory
) -> UserRead:
    user = create_invited(
        session,
        actor_user_id=principal.user_id,
        email=body.email,
        full_name=body.full_name,
        phone=body.phone,
        platform_role=body.platform_role,
        directory=directory,
    )
    session.commit()
    return to_read(user)


def update_user(
    session: Session, principal: Principal, user_id: UUID, body: UserUpdate, directory: IdentityDirectory
) -> UserRead:
    user = _get(session, user_id)
    changes = body.model_dump(exclude_unset=True)
    if user.id == principal.user_id and (changes.get("is_active") is False or "platform_role" in changes):
        raise ConflictError("You cannot switch off or change the role of your own account.")
    was_active = user.is_active
    for name, value in changes.items():
        setattr(user, name, value)
    session.flush()  # a role change while the person still has links fails here: 409
    if changes:
        audit.record(
            session,
            actor_user_id=principal.user_id,
            action="user.updated",
            resource_type="user",
            resource_id=user.id,
            clinic_id=None,
            details={"fields": sorted(changes)},
        )
    try:
        if was_active and not user.is_active:
            directory.disable(user.email)
        elif not was_active and user.is_active:
            directory.enable(user.email)
    except Exception as exc:
        logger.warning("sign-in change failed", extra={"exc_class": exc.__class__.__name__})
        raise UpstreamError("The sign-in account could not be changed. Please try again.") from exc
    session.commit()
    return to_read(user)


def resend_invite(
    session: Session, principal: Principal, user_id: UUID, directory: IdentityDirectory
) -> None:
    user = _get(session, user_id)
    if user.cognito_sub is not None:
        raise ConflictError("This person has already signed in.")
    try:
        directory.resend_invite(user.email, user.full_name)
    except AlreadySignedUpError as exc:
        raise ConflictError("This person has already chosen a password.") from exc
    except Exception as exc:
        logger.warning("resend invite failed", extra={"exc_class": exc.__class__.__name__})
        raise UpstreamError("The invite could not be sent. Please try again.") from exc
    audit.record(
        session,
        actor_user_id=principal.user_id,
        action="user.invite_resent",
        resource_type="user",
        resource_id=user.id,
        clinic_id=None,
    )
    session.commit()


def _get(session: Session, user_id: UUID) -> User:
    user = session.get(User, user_id)  # row-level security hides people the caller can't see
    if user is None:
        raise NotFoundError("User not found")
    return user
