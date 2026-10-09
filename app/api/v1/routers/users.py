"""People (Platform Administrator). Clinic-level invites are under clinic members / clinic practitioners."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.enums import PlatformRole
from app.core.rbac import Permission, Principal
from app.dependencies.adapters import get_identity_directory
from app.dependencies.db import get_db
from app.dependencies.tenancy import platform_permission
from app.integrations.identity_directory import IdentityDirectory
from app.schemas.common import Page
from app.schemas.users import UserCreate, UserRead, UserUpdate
from app.services import users

router = APIRouter(prefix="/users", tags=["users"], responses=ERRORS)
_admin = platform_permission(Permission.USERS_MANAGE)


@router.get("", response_model=Page[UserRead], summary="All people (Platform Administrator)")
def list_users(
    q: str | None = Query(default=None, max_length=200, description="Search email or name"),
    platform_role: PlatformRole | None = None,
    is_active: bool | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
    _: Principal = Depends(_admin),
    db: Session = Depends(get_db),
) -> Page[UserRead]:
    return users.list_users(
        db, q=q, platform_role=platform_role, is_active=is_active, limit=limit, offset=offset
    )


@router.post(
    "", response_model=UserRead, status_code=status.HTTP_201_CREATED, summary="Invite a person (any role)"
)
def invite_user(
    body: UserCreate,
    principal: Principal = Depends(_admin),
    db: Session = Depends(get_db),
    directory: IdentityDirectory = Depends(get_identity_directory),
) -> UserRead:
    return users.invite_user(db, principal, body, directory)


@router.get("/{user_id}", response_model=UserRead)
def get_user(user_id: UUID, _: Principal = Depends(_admin), db: Session = Depends(get_db)) -> UserRead:
    return users.get_user(db, user_id)


@router.patch("/{user_id}", response_model=UserRead, summary="Change name, phone, role or active flag")
def update_user(
    user_id: UUID,
    body: UserUpdate,
    principal: Principal = Depends(_admin),
    db: Session = Depends(get_db),
    directory: IdentityDirectory = Depends(get_identity_directory),
) -> UserRead:
    """Switching a person off also blocks their Cognito sign-in. A role can't change while the person
    is still a clinic member, has a portfolio allocation or a practitioner record (409)."""
    return users.update_user(db, principal, user_id, body, directory)


@router.post("/{user_id}/resend-invite", status_code=status.HTTP_204_NO_CONTENT)
def resend_invite(
    user_id: UUID,
    principal: Principal = Depends(_admin),
    db: Session = Depends(get_db),
    directory: IdentityDirectory = Depends(get_identity_directory),
) -> None:
    users.resend_invite(db, principal, user_id, directory)
