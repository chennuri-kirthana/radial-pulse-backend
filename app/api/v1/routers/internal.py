"""/api/v1/internal: READ-ONLY data for other teams' backends (AWS IAM roles only, CLAUDE.md source 5).

Every request runs as the database role ``radial_service``. No person, no writes.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.rbac import ServiceScope
from app.dependencies.db import get_db
from app.dependencies.service_auth import ServiceCaller, service_access
from app.schemas.clinic_profiles import ClinicOnlineProfileRead, ClinicProfileRead
from app.schemas.common import Page
from app.schemas.connected_accounts import ConnectedAccountRead, ConnectedAccountResourceRead
from app.schemas.internal import InternalActiveClinic, InternalClinicNap, InternalClinicRead
from app.schemas.photos import PhotoRead
from app.schemas.practitioners import ClinicPractitionerRead
from app.services import internal

router = APIRouter(prefix="/internal", tags=["internal (backend services)"], responses=ERRORS)
_clinics = service_access(ServiceScope.CLINICS_READ)
_accounts = service_access(ServiceScope.CONNECTED_ACCOUNTS_READ)


@router.get("/clinics", response_model=Page[InternalClinicRead])
def list_clinics(
    limit: Limit = 50, offset: Offset = 0, _: ServiceCaller = Depends(_clinics), db: Session = Depends(get_db)
) -> Page[InternalClinicRead]:
    return internal.list_clinics(db, limit=limit, offset=offset)


@router.get("/clinics/{clinic_id}", response_model=InternalClinicRead)
def get_clinic(
    clinic_id: UUID, _: ServiceCaller = Depends(_clinics), db: Session = Depends(get_db)
) -> InternalClinicRead:
    return internal.get_clinic(db, clinic_id)


@router.get(
    "/active-clinics",
    response_model=Page[InternalActiveClinic],
    summary="How many active client clinics there are, with their ids and names",
)
def list_active_clinics(
    limit: Limit = 50, offset: Offset = 0, _: ServiceCaller = Depends(_clinics), db: Session = Depends(get_db)
) -> Page[InternalActiveClinic]:
    return internal.list_active_clinics(db, limit=limit, offset=offset)


@router.get(
    "/clinic-nap/{clinic_id}",
    response_model=InternalClinicNap,
    summary="Name, address, phone and website of one active client clinic",
)
def clinic_nap(
    clinic_id: UUID, _: ServiceCaller = Depends(_clinics), db: Session = Depends(get_db)
) -> InternalClinicNap:
    return internal.clinic_nap(db, clinic_id)


@router.get("/clinics/{clinic_id}/clinic-profile", response_model=ClinicProfileRead)
def clinic_profile(
    clinic_id: UUID, _: ServiceCaller = Depends(_clinics), db: Session = Depends(get_db)
) -> ClinicProfileRead:
    return internal.clinic_profile(db, clinic_id)


@router.get("/clinics/{clinic_id}/clinic-practitioners", response_model=list[ClinicPractitionerRead])
def clinic_practitioners(
    clinic_id: UUID, _: ServiceCaller = Depends(_clinics), db: Session = Depends(get_db)
) -> list[ClinicPractitionerRead]:
    return internal.clinic_practitioners(db, clinic_id)


@router.get("/clinics/{clinic_id}/clinic-online-profiles", response_model=list[ClinicOnlineProfileRead])
def online_profiles(
    clinic_id: UUID, _: ServiceCaller = Depends(_clinics), db: Session = Depends(get_db)
) -> list[ClinicOnlineProfileRead]:
    return internal.online_profiles(db, clinic_id)


@router.get(
    "/clinics/{clinic_id}/photos", response_model=list[PhotoRead], summary="Approved photos (details only)"
)
def approved_photos(
    clinic_id: UUID, _: ServiceCaller = Depends(_clinics), db: Session = Depends(get_db)
) -> list[PhotoRead]:
    return internal.approved_photos(db, clinic_id)


@router.get("/clinics/{clinic_id}/connected-accounts", response_model=list[ConnectedAccountRead])
def connected_accounts(
    clinic_id: UUID, _: ServiceCaller = Depends(_accounts), db: Session = Depends(get_db)
) -> list[ConnectedAccountRead]:
    return internal.connected_accounts(db, clinic_id)


@router.get(
    "/clinics/{clinic_id}/connected-account-resources", response_model=list[ConnectedAccountResourceRead]
)
def connected_account_resources(
    clinic_id: UUID, _: ServiceCaller = Depends(_accounts), db: Session = Depends(get_db)
) -> list[ConnectedAccountResourceRead]:
    return internal.connected_account_resources(db, clinic_id)
