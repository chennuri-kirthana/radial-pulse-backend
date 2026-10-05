"""Where a clinic can be found online — ONE generic table for every platform.

Written by finder engines (worker, as a service) and by people (DSMs, Clinic Administrators).
Metrics for these profiles live in `metric_snapshots` (source = the platform).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PresencePlatform, PresenceVerification
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum


class PresenceProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "presence_profiles"
    __table_args__ = (
        UniqueConstraint("clinic_id", "platform", "url"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
    )

    #: No separate index: the unique key (clinic_id, platform, url) starts with clinic_id.
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    platform: Mapped[PresencePlatform] = mapped_column(str_enum(PresencePlatform, length=40))
    url: Mapped[str] = mapped_column(String(1000))
    #: Platform id when known (GBP place id, Instagram handle, …).
    external_id: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    verification: Mapped[PresenceVerification] = mapped_column(
        str_enum(PresenceVerification), default=PresenceVerification.UNVERIFIED
    )
    #: 0-1 confidence from a finder engine; null when added by a person.
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    #: "user:<id>" or "service:<name>" — who found it.
    discovered_by: Mapped[str] = mapped_column(String(128))
    #: Why we think it is this clinic: [{"source_url", "excerpt", "provider", "observed_at"}].
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict)
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
