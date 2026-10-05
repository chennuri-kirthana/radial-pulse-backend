"""Centralized asset metadata. The bytes live in S3; this row is the source of truth for them.

Upload flow (docs/architecture/platform-contracts.md, section 4):
  1. POST .../assets/uploads        → row created (pending_upload) + presigned PUT URL
  2. client PUTs bytes straight to S3 (never through the API)
  3. POST .../assets/{id}/confirm   → API HEADs the object, checks size/type → uploaded
  Every step writes an audit event.

Clinic media (hospital/clinic photos, doctor photos, voice samples) also carry labels from
``media_taxonomy`` and, for doctor photos, the practitioner they show.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ApprovalState, AssetKind, AssetStatus
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum


class Asset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_clinic_kind", "clinic_id", "kind"),
        #: Target for same-clinic composite foreign keys (cover photo, chat files, reports, versions).
        UniqueConstraint("id", "clinic_id"),
        #: The previous version is a file of the SAME clinic.
        ForeignKeyConstraint(["previous_version_id", "clinic_id"], ["assets.id", "assets.clinic_id"]),
        Index(
            "ix_assets_previous_version_id",
            "previous_version_id",
            postgresql_where=text("previous_version_id IS NOT NULL"),
        ),
        #: A doctor photo shows a practitioner who works at THIS clinic (migration 0013).
        ForeignKeyConstraint(
            ["clinic_id", "practitioner_id"],
            ["clinic_practitioners.clinic_id", "clinic_practitioners.practitioner_id"],
            name="fk_assets_clinic_practitioner",
        ),
        Index(
            "ix_assets_clinic_practitioner",
            "clinic_id",
            "practitioner_id",
            postgresql_where=text("practitioner_id IS NOT NULL"),
        ),
        Index("ix_assets_category_id", "category_id", postgresql_where=text("category_id IS NOT NULL")),
        Index("ix_assets_apron_id", "apron_id", postgresql_where=text("apron_id IS NOT NULL")),
        Index("ix_assets_angle_id", "angle_id", postgresql_where=text("angle_id IS NOT NULL")),
        Index("ix_assets_outfit_id", "outfit_id", postgresql_where=text("outfit_id IS NOT NULL")),
        CheckConstraint("size_bytes >= 0", name="size_not_negative"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("previous_version_id <> id", name="not_own_previous"),
        CheckConstraint(
            "practitioner_id IS NULL OR kind = 'practitioner_photo'",
            name="practitioner_only_on_doctor_photos",
        ),
        CheckConstraint(
            "(apron_id IS NULL AND angle_id IS NULL AND outfit_id IS NULL) OR kind = 'practitioner_photo'",
            name="doctor_labels_only_on_doctor_photos",
        ),
        CheckConstraint(
            "category_id IS NULL OR kind IN ('clinic_photo', 'audio')",
            name="category_only_on_clinic_photos_and_voice",
        ),
    )

    #: No separate index: ix_assets_clinic_kind (clinic_id, kind) starts with clinic_id.
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[AssetKind] = mapped_column(str_enum(AssetKind))
    mime_type: Mapped[str] = mapped_column(String(127))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    #: S3 object key. Always prefixed ``clinics/{clinic_id}/`` so IAM/S3 policies can scope by tenant.
    storage_key: Mapped[str] = mapped_column(String(512), unique=True)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(default=1)
    #: Previous version of the same logical asset, if any (e.g. the photo a retake replaces).
    previous_version_id: Mapped[uuid.UUID | None]
    #: Where it came from: {"source": "upload"} or {"source": "generated", "producer": "video-team/v1", ...}
    provenance: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[AssetStatus] = mapped_column(str_enum(AssetStatus), default=AssetStatus.PENDING_UPLOAD)
    approval_state: Mapped[ApprovalState] = mapped_column(
        str_enum(ApprovalState), default=ApprovalState.DRAFT
    )
    #: Doctor photos only: the practitioner in the photo (must work at this clinic).
    practitioner_id: Mapped[uuid.UUID | None]
    #: Hospital/Clinic photo category, or voice-sample type (media_taxonomy).
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media_taxonomy.id"))
    #: Doctor photos only (media_taxonomy).
    apron_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media_taxonomy.id"))
    angle_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media_taxonomy.id"))
    outfit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media_taxonomy.id"))
