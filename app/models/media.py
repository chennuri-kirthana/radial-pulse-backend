"""Media labels: photo categories, doctor-photo apron / angle / outfit, voice-sample types.

The labels are DATA, not code: one row per value, grouped by ``dimension``. Adding a new outfit
or voice sample is a new row (a small data migration), never a new CHECK value or enum.
Values are never deleted (assets point at them); retire one with ``is_active = false``.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import MediaTaxonomyDimension
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum


class MediaTaxonomyValue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "media_taxonomy"
    __table_args__ = (
        UniqueConstraint("dimension", "code"),
        CheckConstraint("code ~ '^[a-z0-9_]+$'", name="code_format").ddl_if(dialect="postgresql"),
        CheckConstraint("sort_order >= 0", name="sort_order_not_negative"),
    )

    dimension: Mapped[MediaTaxonomyDimension] = mapped_column(str_enum(MediaTaxonomyDimension, length=40))
    #: Stable code the API and screens use, e.g. "exterior_signage", "45_left", "outfit_1".
    code: Mapped[str] = mapped_column(String(64))
    #: Display text, e.g. "Exterior & signage", "45° L".
    label: Mapped[str] = mapped_column(String(100))
    #: Display order inside the dimension (the order of the approved reference UI).
    sort_order: Mapped[int] = mapped_column(default=0)
    #: false = retired: kept for existing files, not offered for new uploads.
    is_active: Mapped[bool] = mapped_column(default=True)
