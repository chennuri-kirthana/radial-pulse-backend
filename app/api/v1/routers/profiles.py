from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.errors import ProblemDetails
from app.core.rbac import ClinicContext, Permission
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.schemas.profiles import ClinicProfileRead, ClinicProfileUpdate
from app.services import profiles as service

router = APIRouter(prefix="/clinics/{clinic_id}/profile", tags=["profiles"], responses=ERRORS)


@router.get("", response_model=ClinicProfileRead, summary="Client context: brand, audience, services, ...")
def get_profile(
    ctx: ClinicContext = Depends(clinic_access(Permission.PROFILE_READ)), db: Session = Depends(get_db)
) -> ClinicProfileRead:
    """The tenant-scoped client context every team builds on. Read it here; do not copy it."""
    return service.get_profile(db, ctx)


@router.put(
    "",
    response_model=ClinicProfileRead,
    responses={409: {"model": ProblemDetails, "description": "Version conflict — reload and retry"}},
)
def update_profile(
    body: ClinicProfileUpdate,
    ctx: ClinicContext = Depends(clinic_access(Permission.PROFILE_WRITE)),
    db: Session = Depends(get_db),
) -> ClinicProfileRead:
    return service.update_profile(db, ctx, body)
