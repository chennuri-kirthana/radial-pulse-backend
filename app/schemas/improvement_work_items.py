from __future__ import annotations

from datetime import datetime
from typing import ClassVar, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.core.enums import WorkItemPriority, WorkItemStatus
from app.schemas.common import ApiModel, PatchModel


class ImprovementWorkItemRead(ApiModel):
    id: UUID
    clinic_id: UUID
    title: str
    description: str | None
    status: WorkItemStatus
    priority: WorkItemPriority
    source_assessment_id: UUID | None
    opportunity_code: str | None
    assignee_user_id: UUID | None
    due_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ImprovementWorkItemCreate(ApiModel):
    """A task. A "Fix Now" item comes from a report: ``source_assessment_id`` AND ``opportunity_code``."""

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    status: WorkItemStatus = WorkItemStatus.TODO
    priority: WorkItemPriority = WorkItemPriority.NORMAL
    source_assessment_id: UUID | None = None
    opportunity_code: str | None = Field(default=None, min_length=1, max_length=96)
    assignee_user_id: UUID | None = None
    due_at: datetime | None = None

    @model_validator(mode="after")
    def _fix_now_needs_a_code(self) -> Self:
        if self.source_assessment_id is not None and self.opportunity_code is None:
            raise ValueError("a Fix Now item (source_assessment_id) needs opportunity_code")
        return self


class ImprovementWorkItemUpdate(PatchModel):
    not_null_fields: ClassVar[tuple[str, ...]] = ("title", "status", "priority")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)
    status: WorkItemStatus | None = None
    priority: WorkItemPriority | None = None
    assignee_user_id: UUID | None = None
    due_at: datetime | None = None
