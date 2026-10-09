"""Digital Presence Assessments (reports): clinic people see published ones; staff manage them."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.rbac import ClinicContext, Permission
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.schemas.digital_presence_assessments import (
    DigitalPresenceAssessmentCreate,
    DigitalPresenceAssessmentRead,
    DigitalPresenceAssessmentReview,
    DigitalPresenceAssessmentUpdate,
)
from app.services import digital_presence_assessments as service

router = APIRouter(
    prefix="/clinics/{clinic_id}/digital-presence-assessments",
    tags=["digital presence assessments"],
    responses=ERRORS,
)
_read = clinic_access(Permission.DIGITAL_PRESENCE_ASSESSMENTS_READ)
_manage = clinic_access(Permission.DIGITAL_PRESENCE_ASSESSMENTS_MANAGE)


@router.get("", response_model=list[DigitalPresenceAssessmentRead], summary="Reports, newest first")
def list_assessments(
    ctx: ClinicContext = Depends(_read), db: Session = Depends(get_db)
) -> list[DigitalPresenceAssessmentRead]:
    """Staff: every report. Clinic people and practitioners: published reports only."""
    return service.list_assessments(db, ctx)


@router.post("", response_model=DigitalPresenceAssessmentRead, status_code=status.HTTP_201_CREATED)
def create_assessment(
    body: DigitalPresenceAssessmentCreate,
    ctx: ClinicContext = Depends(_manage),
    db: Session = Depends(get_db),
) -> DigitalPresenceAssessmentRead:
    return service.create_assessment(db, ctx, body)


@router.get("/{assessment_id}", response_model=DigitalPresenceAssessmentRead)
def get_assessment(
    assessment_id: UUID, ctx: ClinicContext = Depends(_read), db: Session = Depends(get_db)
) -> DigitalPresenceAssessmentRead:
    return service.get_assessment(db, ctx, assessment_id)


@router.patch("/{assessment_id}", response_model=DigitalPresenceAssessmentRead, summary="Update results")
def update_assessment(
    assessment_id: UUID,
    body: DigitalPresenceAssessmentUpdate,
    ctx: ClinicContext = Depends(_manage),
    db: Session = Depends(get_db),
) -> DigitalPresenceAssessmentRead:
    return service.update_assessment(db, ctx, assessment_id, body)


@router.post("/{assessment_id}/review", response_model=DigitalPresenceAssessmentRead)
def review_assessment(
    assessment_id: UUID,
    body: DigitalPresenceAssessmentReview,
    ctx: ClinicContext = Depends(_manage),
    db: Session = Depends(get_db),
) -> DigitalPresenceAssessmentRead:
    """submitted / approved / rejected / redo_requested (DSM or Platform Administrator)."""
    return service.review_assessment(db, ctx, assessment_id, body)


@router.post("/{assessment_id}/publish", response_model=DigitalPresenceAssessmentRead)
def publish_assessment(
    assessment_id: UUID, ctx: ClinicContext = Depends(_manage), db: Session = Depends(get_db)
) -> DigitalPresenceAssessmentRead:
    """Only an approved report (409 otherwise). Clinic people see it from now on."""
    return service.publish_assessment(db, ctx, assessment_id)


@router.post("/{assessment_id}/retract", response_model=DigitalPresenceAssessmentRead)
def retract_assessment(
    assessment_id: UUID, ctx: ClinicContext = Depends(_manage), db: Session = Depends(get_db)
) -> DigitalPresenceAssessmentRead:
    return service.retract_assessment(db, ctx, assessment_id)
