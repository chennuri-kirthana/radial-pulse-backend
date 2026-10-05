from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.config import Settings
from app.core.enums import PlatformRole
from app.core.errors import ProblemDetails
from app.core.rbac import Permission, Principal
from app.dependencies.adapters import get_invite_sender, settings_dependency
from app.dependencies.db import get_db
from app.dependencies.tenancy import platform_permission
from app.integrations.invites import InviteSender
from app.schemas.common import Page
from app.schemas.users import UserCreate, UserListItem, UserRead, UserUpdate
from app.services import users as service

router = APIRouter(prefix="/users", tags=["users"], responses=ERRORS)


@router.get("", response_model=Page[UserListItem], summary="Users screen (status + assigned clinic count)")
def list_users(
    platform_role: PlatformRole | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100, description="Search name or email"),
    limit: Limit = 50,
    offset: Offset = 0,
    _: Principal = Depends(platform_permission(Permission.USERS_READ)),
    db: Session = Depends(get_db),
) -> Page[UserListItem]:
    items, total = service.list_users(
        db, limit, offset, platform_role=platform_role, is_active=is_active, search=q
    )
    return Page[UserListItem](items=items, total=total, limit=limit, offset=offset)


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    principal: Principal = Depends(platform_permission(Permission.USERS_MANAGE)),
    db: Session = Depends(get_db),
    invites: InviteSender = Depends(get_invite_sender),
    settings: Settings = Depends(settings_dependency),
) -> UserRead:
    """Pre-provision a Radial Pulse staff user (Platform Administrator or Digital Success Manager).

    An invite email is sent; they then sign in with Google using this email.
    """
    return service.to_read(service.create_user(db, principal, body, invites, settings.app_sign_in_url))


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    responses={409: {"model": ProblemDetails, "description": "e.g. deactivating yourself"}},
    summary="Edit or deactivate a user",
)
def update_user(
    user_id: UUID,
    body: UserUpdate,
    principal: Principal = Depends(platform_permission(Permission.USERS_MANAGE)),
    db: Session = Depends(get_db),
) -> UserRead:
    return service.to_read(service.update_user(db, principal, user_id, body))


@router.post(
    "/{user_id}/resend-invite",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={409: {"model": ProblemDetails, "description": "Already signed in"}},
)
def resend_invite(
    user_id: UUID,
    principal: Principal = Depends(platform_permission(Permission.USERS_MANAGE)),
    db: Session = Depends(get_db),
    invites: InviteSender = Depends(get_invite_sender),
    settings: Settings = Depends(settings_dependency),
) -> Response:
    service.resend_invite(db, principal, user_id, invites, settings.app_sign_in_url)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
