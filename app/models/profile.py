"""Governed client profile: the ONE place clinic brand/audience/services/schedule live.

Other teams read it through ``GET /clinics/{id}/profile`` — they must not copy it
into their own stores. Sections are JSON so the shape can evolve per team need
without migrations; each section is validated by a Pydantic schema on write.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ClinicProfile(TimestampMixin, Base):
    __tablename__ = "clinic_profiles"
    __table_args__ = (CheckConstraint("version >= 1", name="version_positive"),)

    clinic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clinics.id", ondelete="CASCADE"), primary_key=True
    )
    brand: Mapped[dict[str, Any]] = mapped_column(default=dict)
    audience: Mapped[dict[str, Any]] = mapped_column(default=dict)
    services: Mapped[dict[str, Any]] = mapped_column(default=dict)
    schedule: Mapped[dict[str, Any]] = mapped_column(default=dict)
    #: Optimistic concurrency: clients send the version they edited; mismatches get 409.
    version: Mapped[int] = mapped_column(default=1)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ConsentRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What the clinic has agreed to (e.g. read access to Search Console, use of photos in content)."""

    __tablename__ = "consent_records"
    __table_args__ = (CheckConstraint("revoked_at >= granted_at", name="revoked_after_granted"),)

    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"), index=True)
    consent_type: Mapped[str] = mapped_column(String(64))
    granted: Mapped[bool]
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
