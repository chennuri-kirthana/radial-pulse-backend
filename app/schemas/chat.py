from __future__ import annotations

from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from app.core.enums import ChatSide
from app.schemas.common import ApiModel


class ChatMessageCreate(ApiModel):
    """Send a message. Text, an attachment, or both.

    Attachment: first upload the file with ``POST …/assets/uploads`` (kind ``chat_attachment``)
    and ``…/confirm``, then send its id here.
    """

    body: str | None = Field(default=None, max_length=4000)
    attachment_asset_id: UUID | None = None

    @model_validator(mode="after")
    def _something_to_send(self) -> Self:
        if self.body is not None and not self.body.strip():
            self.body = None
        if self.body is None and self.attachment_asset_id is None:
            raise ValueError("send a message text, an attachment, or both")
        return self


class ChatMessageRead(ApiModel):
    id: UUID
    clinic_id: UUID
    sender_user_id: UUID | None
    #: Name to show on the bubble (copied when the message was sent).
    sender_name: str
    #: radial_pulse = our team (DSM / Admin), clinic = the clinic's people. Use it to pick the side.
    sender_side: ChatSide
    body: str | None
    attachment_asset_id: UUID | None
    created_at: datetime


class ChatMessagePage(ApiModel):
    """Messages OLDEST FIRST (ready to show top to bottom)."""

    items: list[ChatMessageRead]
    #: Without ``after``: older messages exist (load them with ``before=<items[0].id>``).
    #: With ``after``: more new messages exist (call again with ``after=<items[-1].id>``).
    has_more: bool
    #: How many messages from others I have not read yet in this clinic.
    unread_count: int


class ChatMarkRead(ApiModel):
    """Mark the chat read up to this message (default: everything up to now)."""

    up_to_message_id: UUID | None = None


class ChatThread(ApiModel):
    clinic_id: UUID
    clinic_name: str
    last_message: ChatMessageRead
    unread_count: int


class ChatInbox(ApiModel):
    """The chats I am part of, newest activity first (DSM "Unread Chats" tile and chat list)."""

    items: list[ChatThread]
    #: Number of clinics with at least one unread message (the "Unread Chats (3)" tile).
    unread_threads: int
    #: Total unread messages across all of them.
    unread_messages: int
