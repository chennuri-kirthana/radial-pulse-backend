"""Declarative base, naming conventions and shared column types.

* Constraint names are deterministic (Alembic autogenerate depends on this).
* Types are portable: PostgreSQL in every real environment; the fast unit-test
  path may use SQLite. JSON becomes JSONB on PostgreSQL.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Index, MetaData, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

JSONType = JSON().with_variant(JSONB(), "postgresql")


def trigram_index(name: str, column: str) -> Index:
    """A PostgreSQL trigram index (pg_trgm) so ``ILIKE '%text%'`` searches stay fast on big tables.

    On SQLite (fast tests) it is just a plain index.
    """
    return Index(name, column, postgresql_using="gin", postgresql_ops={column: "gin_trgm_ops"})


def utcnow() -> datetime:
    return datetime.now(UTC)


def str_enum(enum_cls: type[StrEnum], length: int = 32, name: str | None = None) -> Enum:
    """Store a StrEnum as VARCHAR + CHECK constraint (no native PG enum → no ALTER TYPE pain).

    ``name`` names the CHECK constraint; pass it when one table has two columns of the same enum.
    """
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
        create_constraint=True,
        name=name or enum_cls.__name__.lower(),
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        dict[str, Any]: JSONType,
        uuid.UUID: Uuid(as_uuid=True),
        datetime: DateTime(timezone=True),
    }


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now(), onupdate=utcnow)
