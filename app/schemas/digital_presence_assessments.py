from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.core.enums import AssessmentStatus, PublicationState, ReviewState
from app.schemas.common import ApiModel, PatchModel


class DigitalPresenceAssessmentRead(ApiModel):
    id: UUID
    clinic_id: UUID
    digital_growth_report_id: str | None
    status: AssessmentStatus
    overall_score: Decimal | None
    summary: str | None
    attempts: int
    last_error: str | None
    started_at: datetime | None
    completed_at: datetime | None
    review_state: ReviewState
    review_note: str | None
    reviewed_at: datetime | None
    publication_state: PublicationState
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class _ResultFields(PatchModel):
    """Results from the Digital Growth Team (how they arrive is open question Q2)."""

    digital_growth_report_id: str | None = Field(default=None, max_length=128)
    status: AssessmentStatus | None = None
    overall_score: Decimal | None = Field(default=None, ge=0, le=100, max_digits=5, decimal_places=2)
    summary: str | None = Field(default=None, max_length=20_000)
    last_error: str | None = Field(default=None, max_length=2000)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class DigitalPresenceAssessmentCreate(_ResultFields):
    """Staff add a report (e.g. imported from the Digital Growth Team). Starts as draft, unpublished.
    Only one queued / running report per clinic (409)."""


class DigitalPresenceAssessmentUpdate(_ResultFields):
    pass


class DigitalPresenceAssessmentReview(ApiModel):
    """The DSM's review. ``rejected`` and ``redo_requested`` should say why in ``review_note``."""

    review_state: Literal[
        ReviewState.SUBMITTED, ReviewState.APPROVED, ReviewState.REJECTED, ReviewState.REDO_REQUESTED
    ]
    review_note: str | None = Field(default=None, max_length=2000)
