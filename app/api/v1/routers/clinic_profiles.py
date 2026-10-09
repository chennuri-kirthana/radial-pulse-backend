"""Clinic profile (1 : 1 with the clinic) and clinic online profiles."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.rbac import ClinicContext, Permission
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.schemas.clinic_profiles import (
    ClinicOnlineProfileCreate,
    ClinicOnlineProfileRead,
    ClinicOnlineProfileUpdate,
    ClinicProfileRead,
    ClinicProfileUpdate,
)
from app.services import clinic_profiles

router = APIRouter(prefix="/clinics/{clinic_id}", tags=["clinic profile"], responses=ERRORS)


@router.get("/clinic-profile", response_model=ClinicProfileRead)
def get_profile(
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINIC_PROFILE_READ)), db: Session = Depends(get_db)
) -> ClinicProfileRead:
    """Brand, audience, services, schedule. ``version`` 0 = nothing saved yet."""
    return clinic_profiles.get_profile(db, ctx)


@router.put("/clinic-profile", response_model=ClinicProfileRead)
def update_profile(
    body: ClinicProfileUpdate,
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINIC_PROFILE_WRITE)),
    db: Session = Depends(get_db),
) -> ClinicProfileRead:
    """Admin, DSM, Clinic Administrator. Send the ``version`` you read; a newer one exists → 409."""
    return clinic_profiles.update_profile(db, ctx, body)


@router.get("/clinic-online-profiles", response_model=list[ClinicOnlineProfileRead])
def list_online_profiles(
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINIC_ONLINE_PROFILES_READ)),
    db: Session = Depends(get_db),
) -> list[ClinicOnlineProfileRead]:
    return clinic_profiles.list_online_profiles(db, ctx)


@router.post(
    "/clinic-online-profiles", response_model=ClinicOnlineProfileRead, status_code=status.HTTP_201_CREATED
)
def add_online_profile(
    body: ClinicOnlineProfileCreate,
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINIC_ONLINE_PROFILES_ADD)),
    db: Session = Depends(get_db),
) -> ClinicOnlineProfileRead:
    """Admin, DSM, Clinic Administrator. It starts ``unverified``; staff confirm it."""
    return clinic_profiles.add_online_profile(db, ctx, body)


@router.patch("/clinic-online-profiles/{profile_id}", response_model=ClinicOnlineProfileRead)
def update_online_profile(
    profile_id: UUID,
    body: ClinicOnlineProfileUpdate,
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINIC_ONLINE_PROFILES_REVIEW)),
    db: Session = Depends(get_db),
) -> ClinicOnlineProfileRead:
    """Confirm / reject / fix (DSM or Platform Administrator)."""
    return clinic_profiles.update_online_profile(db, ctx, profile_id, body)


@router.delete("/clinic-online-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_online_profile(
    profile_id: UUID,
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINIC_ONLINE_PROFILES_REVIEW)),
    db: Session = Depends(get_db),
) -> None:
    clinic_profiles.remove_online_profile(db, ctx, profile_id)
