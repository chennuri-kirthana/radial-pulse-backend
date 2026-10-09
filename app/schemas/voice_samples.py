from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field

from app.core.enums import ProcessingStatus
from app.schemas.common import ApiModel, UploadTicket


class VoiceSampleRead(ApiModel):
    id: UUID
    clinic_id: UUID
    practitioner_id: UUID
    title: str
    mime_type: str
    size_bytes: int
    duration_seconds: Decimal | None
    processing_status: ProcessingStatus
    created_at: datetime
    updated_at: datetime


class VoiceSampleUploadRequest(ApiModel):
    practitioner_id: UUID
    #: unique per clinic + practitioner, case-insensitive
    title: str = Field(min_length=1, max_length=120)
    content_type: str
    size_bytes: int


class VoiceSampleUploadResponse(ApiModel):
    voice_sample: VoiceSampleRead
    upload: UploadTicket


class VoiceSampleRename(ApiModel):
    title: str = Field(min_length=1, max_length=120)
