"""API contract for the Digital Presence Assessment (the one user-facing report)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.core.enums import (
    ApprovalState,
    AssessmentComponentKey,
    AssessmentStatus,
    ComponentStatus,
    FindingPriority,
    PublicationState,
)
from app.schemas.common import ApiModel


class EvidenceRead(ApiModel):
    source_url: str | None = None
    excerpt: str | None = None
    provider: str
    observed_at: datetime


class FindingRead(ApiModel):
    id: UUID
    code: str
    title: str
    priority: FindingPriority
    description: str | None
    recommendation: str | None
    evidence: list[EvidenceRead]
    created_at: datetime


class ComponentRead(ApiModel):
    key: AssessmentComponentKey
    status: ComponentStatus
    score: float | None
    summary: str | None
    status_reason: str | None
    engine_name: str | None
    engine_version: str | None
    computed_at: datetime | None


class ComponentDetail(ComponentRead):
    findings: list[FindingRead]


class AssessmentRead(ApiModel):
    id: UUID
    clinic_id: UUID
    sequence: int
    status: AssessmentStatus
    methodology_version: str
    overall_score: float | None
    summary: str | None
    requested_by_user_id: UUID | None
    started_at: datetime | None
    completed_at: datetime | None
    approval_state: ApprovalState
    publication_state: PublicationState
    published_at: datetime | None
    created_at: datetime


class AssessmentDetail(AssessmentRead):
    """The full Digital Presence Assessment: overall score + one section per component."""

    components: list[ComponentDetail]


class AssessmentListItem(AssessmentRead):
    """A row of the cross-clinic Audit Reports list (``GET /assessments``)."""

    clinic_name: str
    primary_practitioner_name: str | None


class AssessmentRequest(ApiModel):
    """Start a new Digital Presence Assessment. Work runs in the background worker."""

    note: str | None = Field(default=None, max_length=500)


def evidence_list(raw: dict[str, Any] | list[Any] | None) -> list[EvidenceRead]:
    items = raw.get("items", []) if isinstance(raw, dict) else (raw or [])
    return [EvidenceRead.model_validate(i) for i in items]
