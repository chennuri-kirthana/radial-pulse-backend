from __future__ import annotations

from uuid import UUID

from sqlalchemy import update

from app.core.enums import JobStatus
from app.db.base import utcnow
from app.models import BackgroundJob
from app.repositories.base import Repository


class JobRepository(Repository):
    def get_in_clinic(self, clinic_id: UUID, job_id: UUID) -> BackgroundJob | None:
        job = self.session.get(BackgroundJob, job_id)
        return job if job is not None and job.clinic_id == clinic_id else None

    def claim(self, clinic_id: UUID, job_id: UUID) -> tuple[int, int] | None:
        """Atomically mark a queued/running job as running and count the attempt.

        Returns (attempts, max_attempts), or None if the job is finished or unknown.
        """
        row = self.session.execute(
            update(BackgroundJob)
            .where(
                BackgroundJob.id == job_id,
                BackgroundJob.clinic_id == clinic_id,
                BackgroundJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
            .values(status=JobStatus.RUNNING, attempts=BackgroundJob.attempts + 1, started_at=utcnow())
            .returning(BackgroundJob.attempts, BackgroundJob.max_attempts)
        ).first()
        return (int(row[0]), int(row[1])) if row is not None else None
