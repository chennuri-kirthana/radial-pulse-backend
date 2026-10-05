"""Digital Presence Assessment — requesting, reading, and storing engine results.

User-facing: ONE assessment per run with an overall score and fixed components.
Clinic Administrators only ever see PUBLISHED assessments (reviewed by a DSM first).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.assessments.engines import ComponentResult, DiscoveredProfile
from app.assessments.scoring import overall_score
from app.core.config import Settings
from app.core.enums import (
    AssessmentComponentKey,
    AssessmentStatus,
    ComponentStatus,
    JobType,
    PresenceVerification,
    PublicationState,
)
from app.core.errors import ConflictError, NotFoundError
from app.core.rbac import ClinicContext, Permission, Principal
from app.db.base import utcnow
from app.jobs.queue import JobQueue
from app.models import Assessment, AssessmentComponent, AssessmentFinding, PresenceProfile
from app.repositories.assessments import AssessmentRepository
from app.repositories.presence import PresenceRepository
from app.repositories.tenancy import ClinicRepository
from app.schemas.assessments import (
    AssessmentDetail,
    AssessmentListItem,
    AssessmentRead,
    AssessmentRequest,
    ComponentDetail,
    FindingRead,
    evidence_list,
)
from app.services import audit, jobs

RESOURCE_TYPE = "assessment"


def _published_only(ctx: ClinicContext) -> bool:
    """People who cannot request assessments (clinic users) only see PUBLISHED ones."""
    return not ctx.can(Permission.ASSESSMENTS_REQUEST)


# --------------------------------------------------------------------- request
def request_assessment(
    session: Session, ctx: ClinicContext, data: AssessmentRequest, queue: JobQueue, settings: Settings
) -> Assessment:
    repo = AssessmentRepository(session)
    if repo.in_progress(ctx.clinic_id) is not None:
        raise ConflictError("An assessment for this clinic is already in progress")
    sequence = repo.next_sequence(ctx.clinic_id)
    assessment = Assessment(
        clinic_id=ctx.clinic_id,
        sequence=sequence,
        status=AssessmentStatus.QUEUED,
        methodology_version=settings.assessment_methodology_version,
        requested_by_user_id=ctx.user_id,
    )
    session.add(assessment)
    try:
        session.flush()
    except IntegrityError as exc:
        # Two requests at the same moment both passed the check above. The database keeps only one
        # (uq_assessments_one_in_progress / the (clinic_id, sequence) key); the other gets 409.
        session.rollback()
        raise ConflictError("An assessment for this clinic is already in progress") from exc
    for key in AssessmentComponentKey:
        session.add(AssessmentComponent(assessment_id=assessment.id, clinic_id=ctx.clinic_id, key=key))
    job = jobs.create_job(
        session,
        clinic_id=ctx.clinic_id,
        job_type=JobType.ASSESSMENT_RUN,
        resource_type=RESOURCE_TYPE,
        resource_id=assessment.id,
        requested_by_user_id=ctx.user_id,
    )
    audit.record(
        session,
        actor=ctx.principal,
        action="assessment.requested",
        resource_type=RESOURCE_TYPE,
        resource_id=assessment.id,
        clinic_id=ctx.clinic_id,
        details={"sequence": sequence, "job_id": str(job.id), "has_note": data.note is not None},
    )
    session.commit()
    jobs.dispatch(session, job, queue)
    return assessment


# ------------------------------------------------------------------------ read
def list_assessments(session: Session, ctx: ClinicContext, limit: int, offset: int) -> tuple[list[Any], int]:
    return AssessmentRepository(session).list_for_clinic(
        ctx.clinic_id, published_only=_published_only(ctx), limit=limit, offset=offset
    )


def list_across_clinics(
    session: Session,
    principal: Principal,
    *,
    status: AssessmentStatus | None,
    publication_state: PublicationState | None,
    clinic_id: UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[AssessmentListItem], int]:
    """The Audit Reports list: assessments of every clinic the caller may see.

    Same scope as ``GET /clinics`` (Admin: all · DSM: assigned · clinic people: their clinics,
    PUBLISHED only). A ``clinic_id`` outside that scope simply matches nothing.
    """
    rows, total = AssessmentRepository(session).list_accessible(
        principal.accessible_clinic_ids(), published_only=not principal.is_internal, status=status,
        publication_state=publication_state, clinic_id=clinic_id, limit=limit, offset=offset,
    )  # fmt: skip
    names = ClinicRepository(session).primary_practitioner_names([a.clinic_id for a, _ in rows])
    items = [
        AssessmentListItem.model_validate(
            {
                **AssessmentRead.model_validate(assessment).model_dump(),
                "clinic_name": clinic_name,
                "primary_practitioner_name": names.get(assessment.clinic_id),
            }
        )
        for assessment, clinic_name in rows
    ]
    return items, total


def get_assessment(session: Session, ctx: ClinicContext, assessment_id: UUID) -> AssessmentDetail:
    repo = AssessmentRepository(session)
    assessment = repo.get_in_clinic(ctx.clinic_id, assessment_id)
    if assessment is None or (
        _published_only(ctx) and assessment.publication_state is not PublicationState.PUBLISHED
    ):
        raise NotFoundError("Assessment not found")
    if _published_only(ctx):
        # Every time a clinic person opens their report, it goes in the audit log.
        audit.record(
            session, actor=ctx.principal, action="assessment.viewed", resource_type=RESOURCE_TYPE,
            resource_id=assessment.id, clinic_id=ctx.clinic_id, details={"sequence": assessment.sequence},
        )  # fmt: skip
        session.commit()
    components = repo.components(ctx.clinic_id, assessment.id)
    findings = repo.findings(ctx.clinic_id, assessment.id)
    order = list(AssessmentComponentKey)
    by_component: dict[UUID, list[FindingRead]] = {}
    for f in findings:
        by_component.setdefault(f.component_id, []).append(
            FindingRead(
                id=f.id,
                code=f.code,
                title=f.title,
                priority=f.priority,
                description=f.description,
                recommendation=f.recommendation,
                evidence=evidence_list(f.evidence),
                created_at=f.created_at,
            )
        )
    details = [
        ComponentDetail.model_validate(
            {**_component_fields(c), "findings": by_component.get(c.id, [])},
        )
        for c in sorted(components, key=lambda c: order.index(c.key))
    ]
    base = {k: getattr(assessment, k) for k in AssessmentDetail.model_fields if k != "components"}
    return AssessmentDetail.model_validate({**base, "components": details})


def _component_fields(c: AssessmentComponent) -> dict[str, Any]:
    return {
        "key": c.key,
        "status": c.status,
        "score": float(c.score) if c.score is not None else None,
        "summary": c.summary,
        "status_reason": c.status_reason,
        "engine_name": c.engine_name,
        "engine_version": c.engine_version,
        "computed_at": c.computed_at,
    }


# ---------------------------------------------------- worker-side result writing
def mark_running(session: Session, ctx: ClinicContext, assessment: Assessment) -> None:
    assessment.status = AssessmentStatus.RUNNING
    assessment.started_at = assessment.started_at or utcnow()


def record_component(
    session: Session,
    ctx: ClinicContext,
    assessment: Assessment,
    key: AssessmentComponentKey,
    result: ComponentResult,
    *,
    engine_name: str | None,
    engine_version: str | None,
) -> None:
    """Store ONE engine's (already validated) result. Idempotent: re-running replaces it."""
    if not ctx.can(Permission.ASSESSMENTS_WRITE_RESULTS):
        raise PermissionError("assessments:write_results required")
    repo = AssessmentRepository(session)
    component = repo.component(ctx.clinic_id, assessment.id, key)
    if component is None:
        raise NotFoundError("component missing")
    # Replace previous findings of this component (a retry must not duplicate them).
    repo.delete_findings_of_component(ctx.clinic_id, component.id)
    component.status = result.status
    component.score = result.score
    component.summary = result.summary
    component.status_reason = result.status_reason
    component.engine_name = engine_name
    component.engine_version = engine_version
    component.computed_at = utcnow()
    for f in result.findings:
        session.add(
            AssessmentFinding(
                assessment_id=assessment.id,
                component_id=component.id,
                clinic_id=ctx.clinic_id,
                code=f.code,
                title=f.title,
                priority=f.priority,
                description=f.description,
                recommendation=f.recommendation,
                evidence={"items": [e.model_dump(mode="json") for e in f.evidence]},
            )
        )
    for d in result.discovered_profiles:
        _upsert_discovered_profile(session, ctx, d, engine_name or "unknown-engine")


def _upsert_discovered_profile(
    session: Session, ctx: ClinicContext, d: DiscoveredProfile, engine: str
) -> None:
    existing = PresenceRepository(session).find(ctx.clinic_id, d.platform, d.url)
    evidence = {"items": [e.model_dump(mode="json") for e in d.evidence]}
    if existing is None:
        session.add(
            PresenceProfile(
                clinic_id=ctx.clinic_id,
                platform=d.platform,
                url=d.url,
                external_id=d.external_id,
                display_name=d.display_name,
                confidence=d.confidence,
                verification=PresenceVerification.UNVERIFIED,
                discovered_by=f"service:{engine}",
                evidence=evidence,
            )
        )
    elif existing.verification is PresenceVerification.UNVERIFIED:
        # Never overwrite a person's decision (confirmed/rejected).
        existing.confidence = d.confidence
        existing.evidence = evidence


def finish(session: Session, ctx: ClinicContext, assessment: Assessment) -> None:
    components = AssessmentRepository(session).components(ctx.clinic_id, assessment.id)
    completed = [c for c in components if c.status is ComponentStatus.COMPLETED]
    assessment.overall_score = overall_score(c.score for c in completed)
    if completed and len(completed) == len(components):
        assessment.status = AssessmentStatus.COMPLETED
    elif completed:
        assessment.status = AssessmentStatus.PARTIAL
    else:
        assessment.status = AssessmentStatus.FAILED
    assessment.completed_at = utcnow()
    audit.record(
        session,
        actor=ctx.principal,
        action="assessment.generated",
        resource_type=RESOURCE_TYPE,
        resource_id=assessment.id,
        clinic_id=ctx.clinic_id,
        details={
            "status": assessment.status.value,
            "completed_components": [c.key.value for c in completed],
            "methodology_version": assessment.methodology_version,
        },
    )


def fail(session: Session, ctx: ClinicContext, assessment: Assessment) -> None:
    """The job gave up after all retries."""
    assessment.status = AssessmentStatus.FAILED
    assessment.completed_at = utcnow()
