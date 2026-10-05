"""Processes one job message at a time: claim → run → record → ack.

Idempotency and retries
-----------------------
* The `background_jobs` row decides. A message for a job that already SUCCEEDED or FAILED is
  acknowledged and ignored (duplicates from at-least-once delivery are harmless).
* Claim = conditional UPDATE (`status IN ('queued','running')`) that also increments `attempts`.
  `running` is claimable because a crashed worker's message comes back after the visibility
  timeout.
* Failure below `max_attempts` → job back to `queued`, message NOT acknowledged → SQS redelivers.
  At `max_attempts` → job `failed`, message acknowledged. (SQS `maxReceiveCount` sends anything
  that keeps crashing the process to the DLQ as a backstop.)
* Engine results are written with replace-semantics, so a retry never duplicates findings.

Isolation
---------
Each job runs with a `ServicePrincipal` scoped to the job's clinic, and the DB session's
row-level-security scope is set to that ONE clinic before anything is read.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Callable
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.assessments.engines import ComponentResult, EngineInput, EngineRegistry, PresenceHint
from app.core.enums import AssessmentComponentKey, ComponentStatus, JobStatus, JobType, PresenceVerification
from app.core.logging import request_id_ctx
from app.core.rbac import ClinicContext, ServicePrincipal
from app.db.base import utcnow
from app.db.tenant import set_tenant_scope
from app.jobs.queue import JobConsumer, JobMessage
from app.models import BackgroundJob, Clinic, ClinicProfile
from app.repositories.assessments import AssessmentRepository
from app.repositories.jobs import JobRepository
from app.repositories.presence import PresenceRepository
from app.services import assessments as assessment_service
from app.services import audit

logger = logging.getLogger("app.worker")

SERVICE_NAME = "assessment-worker"
MAX_ERROR_CHARS = 1000


class Outcome(enum.StrEnum):
    DONE = "done"  # succeeded or permanently failed → ack
    RETRY = "retry"  # leave the message for redelivery
    SKIP = "skip"  # nothing to do (duplicate / unknown) → ack


def process_message(
    session_factory: Callable[[], Session], message: JobMessage, engines: EngineRegistry
) -> Outcome:
    request_id_ctx.set(f"job-{message.job_id}")
    service = ServicePrincipal(name=SERVICE_NAME, clinic_id=message.clinic_id)
    ctx = ClinicContext.for_service(service)

    with session_factory() as session:
        set_tenant_scope(session, [message.clinic_id])
        jobs = JobRepository(session)
        claimed = jobs.claim(message.clinic_id, message.job_id)
        session.commit()
        if claimed is None:
            logger.info("job skipped (already finished or unknown)", extra={"job_id": str(message.job_id)})
            return Outcome.SKIP
        attempts, max_attempts = claimed

        job = jobs.get_in_clinic(message.clinic_id, message.job_id)
        if job is None:  # claimed a moment ago; cannot vanish under row-level security
            return Outcome.SKIP
        try:
            _HANDLERS[message.job_type](session, ctx, job, engines)
            job.status = JobStatus.SUCCEEDED
            job.finished_at = utcnow()
            job.last_error = None
            session.commit()
            logger.info("job succeeded", extra={"job_id": str(job.id), "attempts": attempts})
            return Outcome.DONE
        except Exception as exc:
            session.rollback()
            final = attempts >= max_attempts
            job = jobs.get_in_clinic(message.clinic_id, message.job_id)
            if job is None:
                return Outcome.SKIP
            job.status = JobStatus.FAILED if final else JobStatus.QUEUED
            job.last_error = f"{exc.__class__.__name__}: {exc}"[:MAX_ERROR_CHARS]
            if final:
                job.finished_at = utcnow()
                _on_final_failure(session, ctx, job)
            session.commit()
            logger.warning(
                "job failed",
                extra={
                    "job_id": str(job.id),
                    "attempts": attempts,
                    "final": final,
                    "exc_class": exc.__class__.__name__,
                },
            )
            return Outcome.DONE if final else Outcome.RETRY


def run_forever(
    consumer: JobConsumer,
    session_factory: Callable[[], Session],
    engines: EngineRegistry,
    *,
    stop: Callable[[], bool] = lambda: False,
    idle_sleep: Callable[[], None] = lambda: None,
) -> None:
    while not stop():
        received = consumer.receive()
        if not received:
            idle_sleep()
            continue
        for item in received:
            outcome = process_message(session_factory, item.message, engines)
            if outcome is not Outcome.RETRY:
                consumer.ack(item)


# ------------------------------------------------------------------ handlers
def _run_assessment(
    session: Session, ctx: ClinicContext, job: BackgroundJob, engines: EngineRegistry
) -> None:
    assessment = AssessmentRepository(session).get_in_clinic(ctx.clinic_id, job.resource_id)
    if assessment is None:
        raise LookupError("assessment not found for job")
    assessment_service.mark_running(session, ctx, assessment)
    data = _engine_input(session, ctx.clinic_id)

    for key in AssessmentComponentKey:
        engine = engines.get(key)
        if engine is None:
            result = ComponentResult(status=ComponentStatus.NOT_AVAILABLE, status_reason="no_engine_deployed")
            name = version = None
        else:
            name, version = engine.name, engine.version
            try:
                result = ComponentResult.model_validate(engine.assess(data).model_dump())
            except ValidationError as exc:
                # A misbehaving engine fails ITS component, not the whole assessment.
                logger.warning("engine output rejected", extra={"engine": name, "errors": exc.error_count()})
                result = ComponentResult(status=ComponentStatus.FAILED, status_reason="invalid_engine_output")
        assessment_service.record_component(
            session, ctx, assessment, key, result, engine_name=name, engine_version=version
        )
    assessment_service.finish(session, ctx, assessment)


def _engine_input(session: Session, clinic_id: UUID) -> EngineInput:
    clinic = session.get(Clinic, clinic_id)
    if clinic is None:
        raise LookupError("clinic not found")
    profile = session.get(ClinicProfile, clinic_id)
    services = [i.get("name", "") for i in (profile.services or {}).get("items", [])] if profile else []
    presence = PresenceRepository(session).usable_for_clinic(clinic_id)
    return EngineInput(
        clinic_id=clinic.id,
        clinic_name=clinic.name,
        city=clinic.city,
        state=clinic.state,
        country=clinic.country,
        website_url=clinic.website_url,
        services=[s for s in services if s],
        presence=[
            PresenceHint(
                platform=p.platform, url=p.url, verified=p.verification is PresenceVerification.CONFIRMED
            )
            for p in presence
        ],
    )


def _on_final_failure(session: Session, ctx: ClinicContext, job: BackgroundJob) -> None:
    if job.job_type is JobType.ASSESSMENT_RUN:
        assessment = AssessmentRepository(session).get_in_clinic(ctx.clinic_id, job.resource_id)
        if assessment is not None:
            assessment_service.fail(session, ctx, assessment)
    audit.record(
        session,
        actor=ctx.principal,
        action="job.failed",
        resource_type="background_job",
        resource_id=job.id,
        clinic_id=ctx.clinic_id,
        details={"job_type": job.job_type.value, "attempts": job.attempts},
    )


_HANDLERS: dict[JobType, Callable[[Session, ClinicContext, BackgroundJob, EngineRegistry], None]] = {
    JobType.ASSESSMENT_RUN: _run_assessment,
}
