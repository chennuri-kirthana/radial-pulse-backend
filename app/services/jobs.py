"""Creating and tracking background jobs (the API side). The worker side is app/worker/."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import JobStatus, JobType
from app.core.errors import ServiceUnavailableError
from app.db.base import utcnow
from app.jobs.queue import JobMessage, JobQueue
from app.models import BackgroundJob

logger = logging.getLogger(__name__)


def create_job(
    session: Session,
    *,
    clinic_id: UUID,
    job_type: JobType,
    resource_type: str,
    resource_id: UUID,
    requested_by_user_id: UUID | None,
    payload: dict[str, Any] | None = None,
) -> BackgroundJob:
    """Add a queued job row to the CURRENT transaction (committed together with the resource)."""
    job = BackgroundJob(
        clinic_id=clinic_id,
        job_type=job_type,
        resource_type=resource_type,
        resource_id=resource_id,
        requested_by_user_id=requested_by_user_id,
        payload=payload or {},
        status=JobStatus.QUEUED,
    )
    session.add(job)
    session.flush()
    return job


def dispatch(session: Session, job: BackgroundJob, queue: JobQueue) -> None:
    """Send the queue message AFTER the job row is committed.

    If sending fails the job is marked failed (visible, retryable by requesting again) — we
    never leave a `queued` row that no worker will ever see.
    """
    try:
        queue.enqueue(JobMessage(job_id=job.id, clinic_id=job.clinic_id, job_type=job.job_type))
    except Exception as exc:
        logger.error("job enqueue failed", extra={"job_id": str(job.id), "exc_class": exc.__class__.__name__})
        job.status = JobStatus.FAILED
        job.last_error = "enqueue failed"
        job.finished_at = utcnow()
        session.commit()
        raise ServiceUnavailableError("Could not start the background job. Please try again.") from exc
