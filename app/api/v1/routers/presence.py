"""Presence profiles: where the clinic is online — one generic list for every platform."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.errors import ProblemDetails
from app.core.rbac import ClinicContext, Permission
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.schemas.common import Page
from app.schemas.presence import PresenceProfileCreate, PresenceProfileRead, PresenceProfileUpdate
from app.services import presence as service

router = APIRouter(
    prefix="/clinics/{clinic_id}/presence-profiles", tags=["digital-presence"], responses=ERRORS
)


@router.get("", response_model=Page[PresenceProfileRead])
def list_profiles(
    limit: Limit = 100,
    offset: Offset = 0,
    ctx: ClinicContext = Depends(clinic_access(Permission.PRESENCE_READ)),
    db: Session = Depends(get_db),
) -> Page[PresenceProfileRead]:
    items, total = service.list_profiles(db, ctx, limit, offset)
    return Page[PresenceProfileRead](items=items, total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=PresenceProfileRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ProblemDetails, "description": "Already recorded"}},
)
def add_profile(
    body: PresenceProfileCreate,
    ctx: ClinicContext = Depends(clinic_access(Permission.PRESENCE_WRITE)),
    db: Session = Depends(get_db),
) -> PresenceProfileRead:
    return service.add_profile(db, ctx, body)


@router.patch("/{profile_id}", response_model=PresenceProfileRead, summary="Confirm/reject a found profile")
def update_profile(
    profile_id: UUID,
    body: PresenceProfileUpdate,
    ctx: ClinicContext = Depends(clinic_access(Permission.PRESENCE_WRITE)),
    db: Session = Depends(get_db),
) -> PresenceProfileRead:
    return service.update_profile(db, ctx, profile_id, body)
