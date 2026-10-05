from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from app.core.enums import ApprovalState, DataSource, PublicationState, SnapshotStatus
from app.schemas.common import ApiModel, ShortText


class MetricSnapshotCreate(ApiModel):
    source: DataSource
    metric_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
    value: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = Field(default=1, ge=1)
    fetched_at: datetime
    status: SnapshotStatus
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2000)
    retry_count: int = Field(default=0, ge=0)
    next_retry_at: datetime | None = None


class MetricSnapshotBatch(ApiModel):
    snapshots: list[MetricSnapshotCreate] = Field(min_length=1, max_length=500)


class MetricSnapshotRead(ApiModel):
    id: UUID
    clinic_id: UUID
    source: DataSource
    metric_key: str
    value: dict[str, Any]
    #: The plain number, when the value is one (for charts).
    value_number: float | None
    schema_version: int
    fetched_at: datetime
    status: SnapshotStatus
    error_code: str | None
    error_message: str | None
    retry_count: int
    next_retry_at: datetime | None
    created_at: datetime


class ReportArtifactCreate(ApiModel):
    report_type: str = Field(min_length=1, max_length=64)
    report_key: str = Field(min_length=1, max_length=128)
    title: ShortText
    provenance: dict[str, Any] = Field(default_factory=dict)
    #: The rendered file, uploaded first through the assets flow.
    asset_id: UUID | None = None


class ReportArtifactRead(ApiModel):
    id: UUID
    clinic_id: UUID
    report_type: str
    report_key: str
    version: int
    title: str
    provenance: dict[str, Any]
    owner_user_id: UUID | None
    asset_id: UUID | None
    approval_state: ApprovalState
    publication_state: PublicationState
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
