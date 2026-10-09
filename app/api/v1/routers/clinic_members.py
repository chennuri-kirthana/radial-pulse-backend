"""Clinic members: Clinic Administrators and Clinic Team Members of one clinic."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.rbac import ClinicContext, Permission
from app.dependencies.adapters import get_identity_directory
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.integrations.identity_directory import IdentityDirectory
from app.schemas.clinic_members import ClinicMemberCreate, ClinicMemberRead, ClinicMemberUpdate
from app.services import clinic_members

router = APIRouter(prefix="/clinics/{clinic_id}/clinic-members", tags=["clinic members"], responses=ERRORS)
_read = clinic_access(Permission.CLINIC_MEMBERS_READ)
_manage = clinic_access(Permission.CLINIC_MEMBERS_MANAGE)


@router.get("", response_model=list[ClinicMemberRead], summary="The clinic's people")
def list_members(
    ctx: ClinicContext = Depends(_read), db: Session = Depends(get_db)
) -> list[ClinicMemberRead]:
    """Practitioners don't see the team list."""
    return clinic_members.list_members(db, ctx)


@router.post("", response_model=ClinicMemberRead, status_code=status.HTTP_201_CREATED, summary="Add a person")
def add_member(
    body: ClinicMemberCreate,
    ctx: ClinicContext = Depends(_manage),
    db: Session = Depends(get_db),
    directory: IdentityDirectory = Depends(get_identity_directory),
) -> ClinicMemberRead:
    """Platform Administrator, the DSM or a Clinic Administrator. A new email gets an invite."""
    return clinic_members.add_member(db, ctx, body, directory)


@router.patch("/{user_id}", response_model=ClinicMemberRead, summary="Change role or switch off")
def update_member(
    user_id: UUID,
    body: ClinicMemberUpdate,
    ctx: ClinicContext = Depends(_manage),
    db: Session = Depends(get_db),
) -> ClinicMemberRead:
    """The clinic must keep at least one active Clinic Administrator (409)."""
    return clinic_members.update_member(db, ctx, user_id, body)


@router.post("/{user_id}/resend-invite", status_code=status.HTTP_204_NO_CONTENT)
def resend_invite(
    user_id: UUID,
    ctx: ClinicContext = Depends(_manage),
    db: Session = Depends(get_db),
    directory: IdentityDirectory = Depends(get_identity_directory),
) -> None:
    clinic_members.resend_invite(db, ctx, user_id, directory)
