"""Photos and voice samples (db/schema-v15.sql section 10). Only S3 keys are stored; files live in
a private bucket. Uploads use presigned URLs; views are short-lived links, each one audited."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PhotoAngle, PhotoAttire, PhotoCategory, PhotoReviewState, ProcessingStatus
from app.db.base import Base, Timestamps, str_enum, uuid_pk


class Photo(Timestamps, Base):
    """A practitioner photo (practitioner + attire + outfit + angle) or a clinic photo (category).

    The Clinic Administrator (or the practitioner, for his own) uploads; staff review and sort.
    """

    __tablename__ = "photos"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "practitioner_id"],
            ["clinic_practitioners.clinic_id", "clinic_practitioners.practitioner_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    practitioner_id: Mapped[uuid.UUID | None]
    attire: Mapped[PhotoAttire | None] = mapped_column(str_enum(PhotoAttire, 16))
    outfit_no: Mapped[int | None] = mapped_column(SmallInteger)
    angle: Mapped[PhotoAngle | None] = mapped_column(str_enum(PhotoAngle, 16))
    #: clinic photos only; empty = "uploaded, not yet sorted"
    category: Mapped[PhotoCategory | None] = mapped_column(str_enum(PhotoCategory))
    original_key: Mapped[str] = mapped_column(String(512))
    #: {"thumb": key, "medium": key}
    variants: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
    mime_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        str_enum(ProcessingStatus, 16), server_default=text("'uploading'")
    )
    review_state: Mapped[PhotoReviewState] = mapped_column(
        str_enum(PhotoReviewState, 16), server_default=text("'pending'")
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None]
    check_results: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))


class VoiceSample(Timestamps, Base):
    """A practitioner's voice recording at one clinic. No review step. Titles are unique per
    clinic + practitioner (case-insensitive)."""

    __tablename__ = "voice_samples"
    __table_args__ = (
        ForeignKeyConstraint(
            ["clinic_id", "practitioner_id"],
            ["clinic_practitioners.clinic_id", "clinic_practitioners.practitioner_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    clinic_id: Mapped[uuid.UUID]
    practitioner_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String(120))
    original_key: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    processing_status: Mapped[ProcessingStatus] = mapped_column(
        str_enum(ProcessingStatus, 16), server_default=text("'uploading'")
    )
    reviewed_at: Mapped[datetime | None]
    check_results: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
