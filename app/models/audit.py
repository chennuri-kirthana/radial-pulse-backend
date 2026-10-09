"""``audit_events``: insert-only (db/schema-v15.sql section 6). One row per change, in the SAME
transaction as the change (CLAUDE.md rule 8). No foreign keys on purpose: the trail outlives
the rows it talks about."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, uuid_pk


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    clinic_id: Mapped[uuid.UUID | None]
    actor_user_id: Mapped[uuid.UUID | None]
    #: user / service / system
    actor_type: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
