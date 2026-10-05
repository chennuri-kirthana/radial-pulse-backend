"""Background jobs: the platform's record of long-running work (crawls, assessments, …).

The row is the source of truth for status and idempotency; the queue message (SQS in AWS)
only says "job X is ready". See docs/architecture/background-jobs.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import JobStatus, JobType
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum


class BackgroundJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_status", "status", "created_at"),
        CheckConstraint("attempts >= 0", name="attempts_not_negative"),
        CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        CheckConstraint("finished_at >= started_at", name="finished_after_start"),
    )

    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    job_type: Mapped[JobType] = mapped_column(str_enum(JobType, length=40))
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus), default=JobStatus.QUEUED)
    #: What the job works on, e.g. ("assessment", <id>).
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[uuid.UUID]
    #: Small, non-sensitive parameters. Never secrets or tokens.
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    attempts: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=5)
    last_error: Mapped[str | None] = mapped_column(Text)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
