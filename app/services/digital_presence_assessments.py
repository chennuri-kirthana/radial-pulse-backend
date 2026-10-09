"""Digital Presence Assessments: the reports (docs/01-decisions.md section 8).

* Staff (admin, the clinic's DSM) see every report and create / review / publish them.
* Clinic people and practitioners see PUBLISHED reports only (the database hides the rest too).
* Published only if approved. One queued / running report per clinic. Newest first.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import PublicationState, ReviewState
from app.core.errors import ConflictError, NotFoundError
from app.core.rbac import ClinicContext
from app.db.base import utcnow
from app.models import DigitalPresenceAssessment
from app.schemas.digital_presence_assessments import (
    DigitalPresenceAssessmentCreate,
    DigitalPresenceAssessmentRead,
    DigitalPresenceAssessmentReview,
    DigitalPresenceAssessmentUpdate,
)
from app.services import audit

Read = DigitalPresenceAssessmentRead


def list_assessments(session: Session, ctx: ClinicContext) -> list[Read]:
    query = select(DigitalPresenceAssessment).where(DigitalPresenceAssessment.clinic_id == ctx.clinic_id)
    if not ctx.is_staff:  # also enforced by the database
        query = query.where(DigitalPresenceAssessment.publication_state == PublicationState.PUBLISHED)
    rows = session.scalars(
        query.order_by(DigitalPresenceAssessment.created_at.desc(), DigitalPresenceAssessment.id)
    )
    return [Read.model_validate(r) for r in rows]


def get_assessment(session: Session, ctx: ClinicContext, assessment_id: UUID) -> Read:
    return Read.model_validate(_get(session, ctx, assessment_id))


def create_assessment(session: Session, ctx: ClinicContext, body: DigitalPresenceAssessmentCreate) -> Read:
    row = DigitalPresenceAssessment(clinic_id=ctx.clinic_id, **body.model_dump(exclude_unset=True))
    session.add(row)
    session.flush()  # a second queued / running report, or a known digital_growth_report_id: 409
    _audit(session, ctx, row, "digital_presence_assessment.created", {})
    session.commit()
    return _fresh(session, row)


def update_assessment(
    session: Session, ctx: ClinicContext, assessment_id: UUID, body: DigitalPresenceAssessmentUpdate
) -> Read:
    row = _get(session, ctx, assessment_id)
    changes = body.model_dump(exclude_unset=True)
    for name, value in changes.items():
        setattr(row, name, value)
    session.flush()
    if changes:
        _audit(session, ctx, row, "digital_presence_assessment.updated", {"fields": sorted(changes)})
    session.commit()
    return _fresh(session, row)


def review_assessment(
    session: Session, ctx: ClinicContext, assessment_id: UUID, body: DigitalPresenceAssessmentReview
) -> Read:
    row = _get(session, ctx, assessment_id)
    if row.publication_state == PublicationState.PUBLISHED and body.review_state != ReviewState.APPROVED:
        raise ConflictError("Retract the published report before changing its review.")
    row.review_state = body.review_state
    row.review_note = body.review_note
    row.reviewed_at = None if body.review_state == ReviewState.SUBMITTED else utcnow()
    session.flush()
    _audit(session, ctx, row, f"digital_presence_assessment.{body.review_state.value}", {})
    session.commit()
    return _fresh(session, row)


def publish_assessment(session: Session, ctx: ClinicContext, assessment_id: UUID) -> Read:
    row = _get(session, ctx, assessment_id)
    if row.review_state != ReviewState.APPROVED:
        raise ConflictError("Only an approved report can be published.")
    if row.publication_state == PublicationState.PUBLISHED:
        raise ConflictError("This report is already published.")
    row.publication_state = PublicationState.PUBLISHED
    row.published_at = utcnow()
    session.flush()
    _audit(session, ctx, row, "digital_presence_assessment.published", {})
    session.commit()
    return _fresh(session, row)


def retract_assessment(session: Session, ctx: ClinicContext, assessment_id: UUID) -> Read:
    row = _get(session, ctx, assessment_id)
    if row.publication_state != PublicationState.PUBLISHED:
        raise ConflictError("Only a published report can be retracted.")
    row.publication_state = PublicationState.RETRACTED
    session.flush()
    _audit(session, ctx, row, "digital_presence_assessment.retracted", {})
    session.commit()
    return _fresh(session, row)


def _audit(
    session: Session,
    ctx: ClinicContext,
    row: DigitalPresenceAssessment,
    action: str,
    details: dict[str, object],
) -> None:
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action=action,
        resource_type="digital_presence_assessment",
        resource_id=row.id,
        clinic_id=ctx.clinic_id,
        details=details,
    )


def _fresh(session: Session, row: DigitalPresenceAssessment) -> Read:
    session.refresh(row)
    return Read.model_validate(row)


def _get(session: Session, ctx: ClinicContext, assessment_id: UUID) -> DigitalPresenceAssessment:
    row = session.get(DigitalPresenceAssessment, assessment_id)
    hidden = row is None or row.clinic_id != ctx.clinic_id
    if row is None or hidden or (not ctx.is_staff and row.publication_state != PublicationState.PUBLISHED):
        raise NotFoundError("Digital Presence Assessment not found")
    return row
