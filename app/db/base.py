"""Declarative base and shared column helpers for the v15 models.

The database is built ONLY by db/schema-v15.sql (the baseline migration). These models describe
it; they never create it. ``tests/schema_v15/test_07_models_match_database.py`` fails if a model
and the real table ever differ.

* ``id``: the database fills it (``gen_random_uuid()``); the app also sets it, so it knows the id
  before the INSERT (needed for S3 keys like ``clinics/<id>/photos/<photo id>``).
* ``created_at`` / ``updated_at``: the database fills them; ``updated_at`` is set by a trigger on
  every UPDATE (CLAUDE.md rule 9), so the app never writes it and reads it back after changes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, FetchedValue, MetaData, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: Same names as db/schema-v15.sql uses (only matters for messages; the models create nothing).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

TextArray = ARRAY(Text)


def utcnow() -> datetime:
    return datetime.now(UTC)


def str_enum(enum_cls: type[StrEnum], length: int = 32) -> Enum:
    """A VARCHAR column that only takes the enum's values (checked in Python; the database
    has the same list as a CHECK rule)."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
        create_constraint=False,  # the database already has the CHECK
    )


class Base(DeclarativeBase):
    """Every model inherits ``eager_defaults = False``: never ``INSERT … RETURNING``.

    PostgreSQL also applies the table's SELECT rule to returned rows, and many valid inserts make
    rows the writer can't read (an audit row a team member wrote, a notification for someone
    else, an invited user not yet linked to a clinic). Values the database fills are loaded on
    first access instead.
    """

    __mapper_args__ = {"eager_defaults": False}
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        dict[str, Any]: JSONB(),
        uuid.UUID: Uuid(as_uuid=True),
        datetime: DateTime(timezone=True),
    }


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))


class CreatedAt:
    """``created_at timestamptz NOT NULL DEFAULT now()`` (filled by the database)."""

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Timestamps(CreatedAt):
    """+ ``updated_at``: set by the trigger rp_set_updated_at (loaded again on next access)."""

    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), server_onupdate=FetchedValue())
