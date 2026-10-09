from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.core.enums import ClinicStage
from app.schemas.common import ApiModel, Email, PatchModel
from app.schemas.practitioners import TimeZone


class PlatformSettingsRead(ApiModel):
    support_email: str | None
    support_phone: str | None
    timezone: str
    date_format: str
    #: None = the settings row has not been created yet (defaults shown)
    updated_at: datetime | None


class PlatformSettingsUpdate(PatchModel):
    support_email: Email | None = None
    support_phone: str | None = Field(default=None, max_length=32)
    timezone: TimeZone | None = None
    date_format: str | None = Field(default=None, min_length=1, max_length=16)


class AuditEventRead(ApiModel):
    id: UUID
    occurred_at: datetime
    clinic_id: UUID | None
    actor_user_id: UUID | None
    actor_type: str
    action: str
    resource_type: str
    resource_id: str | None
    request_id: str | None
    details: dict[str, Any]


class DashboardSummary(ApiModel):
    """Counts over what the caller can see (row-level security decides)."""

    clinics_by_stage: dict[ClinicStage, int]
    archived_clinics: int
    open_improvement_work_items: int
    #: staff only (0 for others): photos waiting for review, reports waiting for review
    photos_waiting_for_review: int
    digital_presence_assessments_to_review: int
