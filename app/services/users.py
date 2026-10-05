"""Platform user management (Platform Administrators) and "My Profile"."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import PlatformRole, UserStatus
from app.core.errors import ConflictError, DomainValidationError, InvalidStateError, NotFoundError
from app.core.rbac import Principal
from app.integrations.invites import InviteSender
from app.models import User
from app.repositories.tenancy import AssignmentRepository
from app.repositories.users import UserRepository
from app.schemas.users import MeUpdate, UserCreate, UserListItem, UserRead, UserUpdate
from app.services import audit
from app.services.invitations import send_invite


def user_status(user: User) -> UserStatus:
    if not user.is_active:
        return UserStatus.DEACTIVATED
    return UserStatus.INVITED if user.cognito_sub is None else UserStatus.ACTIVE


def to_read(user: User) -> UserRead:
    return UserRead.model_validate(
        {**{k: getattr(user, k) for k in UserRead.model_fields if k != "status"}, "status": user_status(user)}
    )


def list_users(
    session: Session,
    limit: int,
    offset: int,
    *,
    platform_role: PlatformRole | None = None,
    is_active: bool | None = None,
    search: str | None = None,
) -> tuple[list[UserListItem], int]:
    users, total = UserRepository(session).list(
        limit, offset, platform_role=platform_role, is_active=is_active, search=search
    )
    counts = AssignmentRepository(session).active_counts_by_user([u.id for u in users])
    items = [
        UserListItem.model_validate({**to_read(u).model_dump(), "assigned_clinic_count": counts.get(u.id, 0)})
        for u in users
    ]
    return items, total


def create_user(
    session: Session, principal: Principal, data: UserCreate, invites: InviteSender, sign_in_url: str
) -> User:
    """Pre-provision a Platform Administrator or Digital Success Manager and send the invite email.

    Clinic users are added through a clinic's team (POST /clinics/{clinic_id}/team).
    """
    if data.platform_role is PlatformRole.CLINIC_USER:
        raise DomainValidationError("Add clinic users through POST /clinics/{clinic_id}/team")
    repo = UserRepository(session)
    if repo.get_by_email(data.email) is not None:
        raise ConflictError("A user with this email already exists")
    user = User(
        email=data.email,
        full_name=data.full_name,
        phone=data.phone,
        platform_role=data.platform_role,
        created_by_user_id=principal.user_id,
    )
    repo.add(user)
    audit.record(
        session,
        actor=principal,
        action="user.create",
        resource_type="user",
        resource_id=user.id,
        clinic_id=None,
        details={"platform_role": data.platform_role.value},
    )
    session.commit()
    send_invite(
        session, actor=principal, user=user, role=data.platform_role, invites=invites, sign_in_url=sign_in_url
    )
    return user


def update_user(session: Session, principal: Principal, user_id: UUID, data: UserUpdate) -> User:
    user = UserRepository(session).get(user_id)
    if user is None:
        raise NotFoundError("User not found")
    changes = data.model_dump(exclude_unset=True)
    if changes.get("is_active") is False and user.id == principal.user_id:
        raise InvalidStateError("You cannot deactivate your own account")
    for field, value in changes.items():
        setattr(user, field, value)
    action = "user.update"
    if "is_active" in changes:
        action = "user.reactivate" if changes["is_active"] else "user.deactivate"
    audit.record(
        session,
        actor=principal,
        action=action,
        resource_type="user",
        resource_id=user.id,
        clinic_id=None,
        details={"fields": sorted(changes)},
    )
    session.commit()
    return user


def resend_invite(
    session: Session, principal: Principal, user_id: UUID, invites: InviteSender, sign_in_url: str
) -> bool:
    user = UserRepository(session).get(user_id)
    if user is None or not user.is_active:
        raise NotFoundError("User not found")
    if user.cognito_sub is not None:
        raise InvalidStateError("This person has already signed in")
    if user.platform_role is PlatformRole.CLINIC_USER:
        raise DomainValidationError("Resend a clinic person's invite from the clinic's team")
    return send_invite(
        session, actor=principal, user=user, role=user.platform_role, invites=invites, sign_in_url=sign_in_url
    )


def update_me(session: Session, principal: Principal, data: MeUpdate) -> User:
    user = UserRepository(session).get(principal.user_id)
    if user is None:  # pragma: no cover - the principal was just built from this row
        raise NotFoundError("User not found")
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    audit.record(
        session,
        actor=principal,
        action="user.update_self",
        resource_type="user",
        resource_id=user.id,
        clinic_id=None,
        details={"fields": sorted(changes)},
    )
    session.commit()
    return user
