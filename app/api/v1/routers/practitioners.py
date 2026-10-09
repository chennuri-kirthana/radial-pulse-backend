"""The SHARED practitioner record (one per person, across all businesses)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.rbac import Principal
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.schemas.practitioners import PractitionerRead, PractitionerUpdate
from app.services import practitioners

router = APIRouter(prefix="/practitioners", tags=["practitioners"], responses=ERRORS)


@router.get("/{practitioner_id}", response_model=PractitionerRead)
def get_practitioner(
    practitioner_id: UUID, principal: Principal = Depends(get_principal), db: Session = Depends(get_db)
) -> PractitionerRead:
    """Visible to the admin, the practitioner himself, and people of a clinic he is linked to."""
    return practitioners.get_practitioner(db, principal, practitioner_id)


@router.patch("/{practitioner_id}", response_model=PractitionerRead)
def update_practitioner(
    practitioner_id: UUID,
    body: PractitionerUpdate,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> PractitionerRead:
    """Bio, qualifications, specialty, practice start year, services, patients, highlights: the
    practitioner himself, the DSM of a linked clinic, or the admin. Name, registration number and
    login (``user_id``): DSM or admin only. Changes go live at once (no approval)."""
    return practitioners.update_practitioner(db, principal, practitioner_id, body)
