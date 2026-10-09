from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from app.core.enums import SenderSide
from app.schemas.common import ApiModel


class NotificationRead(ApiModel):
    id: UUID
    clinic_id: UUID | None
    category: str
    title: str
    body: str | None
    link: str | None
    read_at: datetime | None
    created_at: datetime


class CollaborationMessageRead(ApiModel):
    id: UUID
    clinic_id: UUID
    sender_user_id: UUID | None
    sender_name: str
    sender_side: SenderSide
    body: str | None
    attachment_name: str | None
    has_attachment: bool
    parent_message_id: UUID | None
    #: counted from the replies (not stored); 0 for replies themselves
    reply_count: int
    last_reply_at: datetime | None
    created_at: datetime


class CollaborationAttachmentUploadRequest(ApiModel):
    content_type: str
    size_bytes: int


class CollaborationMessageCreate(ApiModel):
    """Text and/or ONE attachment (upload it first). Reply to the FIRST message of a thread only."""

    body: str | None = Field(default=None, min_length=1, max_length=10_000)
    parent_message_id: UUID | None = None
    attachment_key: str | None = Field(default=None, max_length=512)
    attachment_name: str | None = Field(default=None, min_length=1, max_length=255)
    attachment_content_type: str | None = None
    attachment_size_bytes: int | None = None

    @model_validator(mode="after")
    def _text_or_file(self) -> Self:
        if self.body is None and self.attachment_key is None:
            raise ValueError("write a message or attach a file")
        file_fields = (
            self.attachment_key,
            self.attachment_name,
            self.attachment_content_type,
            self.attachment_size_bytes,
        )
        if any(f is not None for f in file_fields) and any(f is None for f in file_fields):
            raise ValueError("an attachment needs attachment_key, attachment_name, content type and size")
        return self
