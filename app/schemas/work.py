from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from app.core.enums import WorkArea, WorkItemPriority, WorkItemStatus
from app.schemas.common import ApiModel, PatchModel, ShortText


class WorkItemCreate(ApiModel):
    """Create an Improvement Work Item.

    "Fix Now" on a finding: send ``source_finding_id`` only (plus optional owner/due date) —
    title, description, area and finding_code are copied from the finding.
    """

    kind: str = Field(default="improvement", min_length=1, max_length=64)
    title: ShortText | None = None
    description: str | None = Field(default=None, max_length=5000)
    area: WorkArea | None = None
    finding_code: str | None = Field(default=None, max_length=96)
    source_finding_id: UUID | None = None
    priority: WorkItemPriority = WorkItemPriority.NORMAL
    owner_user_id: UUID | None = None
    due_at: datetime | None = None
    source_team: str | None = Field(default=None, max_length=32)
    approval_id: UUID | None = None

    @model_validator(mode="after")
    def _title_or_finding(self) -> Self:
        if self.title is None and self.source_finding_id is None:
            raise ValueError("give a title, or a source_finding_id to copy it from")
        return self


class WorkItemUpdate(PatchModel):
    not_null_fields = ("title", "status", "priority", "area")

    title: ShortText | None = None
    description: str | None = Field(default=None, max_length=5000)
    status: WorkItemStatus | None = None
    priority: WorkItemPriority | None = None
    area: WorkArea | None = None
    owner_user_id: UUID | None = None
    due_at: datetime | None = None


class WorkItemRead(ApiModel):
    id: UUID
    clinic_id: UUID
    kind: str
    title: str
    description: str | None
    area: WorkArea
    finding_code: str | None
    source_finding_id: UUID | None
    status: WorkItemStatus
    priority: WorkItemPriority
    owner_user_id: UUID | None
    created_by_user_id: UUID | None
    due_at: datetime | None
    completed_at: datetime | None
    approval_id: UUID | None
    source_team: str | None
    created_at: datetime
    updated_at: datetime


class WorkItemListItem(WorkItemRead):
    """A row of the cross-clinic work queue (``GET /work-items``)."""

    clinic_name: str


class NotificationRead(ApiModel):
    id: UUID
    clinic_id: UUID | None
    kind: str
    title: str
    body: str | None
    link: str | None
    created_at: datetime
    read_at: datetime | None
