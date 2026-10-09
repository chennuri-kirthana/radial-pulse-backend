"""Digital Presence Assessments and Improvement Work Items (db/schema-v15.sql sections 5 and 6)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AssessmentStatus, PublicationState, ReviewState, WorkItemPriority, WorkItemStatus
from app.db.base import Base, Timestamps, str_enum, uuid_pk


class DigitalPresenceAssessment(Timestamps, Base):
    """A report. Clinic people see it only once ``publication_state = 'published'``."""

    __tablename__ = "digital_presence_assessments"

    id: Mapped[uuid.UUID] = uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    #: the Digital Growth Team's id for the same report
    digital_growth_report_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[AssessmentStatus] = mapped_column(
        str_enum(AssessmentStatus), server_default=text("'queued'")
    )
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    summary: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    review_state: Mapped[ReviewState] = mapped_column(str_enum(ReviewState), server_default=text("'draft'"))
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None]
    publication_state: Mapped[PublicationState] = mapped_column(
        str_enum(PublicationState), server_default=text("'unpublished'")
    )
    published_at: Mapped[datetime | None]


class ImprovementWorkItem(Timestamps, Base):
    """A task to fix an Improvement Opportunity (``opportunity_code``) or added by hand."""

    __tablename__ = "improvement_work_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_assessment_id", "clinic_id"],
            ["digital_presence_assessments.id", "digital_presence_assessments.clinic_id"],
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[WorkItemStatus] = mapped_column(str_enum(WorkItemStatus), server_default=text("'todo'"))
    priority: Mapped[WorkItemPriority] = mapped_column(
        str_enum(WorkItemPriority), server_default=text("'normal'")
    )
    #: filled = a "Fix Now" item from this assessment (then opportunity_code is required)
    source_assessment_id: Mapped[uuid.UUID | None]
    opportunity_code: Mapped[str | None] = mapped_column(String(96))
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    due_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
