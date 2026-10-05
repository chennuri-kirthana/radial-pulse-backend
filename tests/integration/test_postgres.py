"""Checks that only make sense on real PostgreSQL (CI integration job)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models import AuditEvent

pytestmark = pytest.mark.integration


def test_migrations_match_models(engine) -> None:  # type: ignore[no-untyped-def]
    """The schema built by Alembic must equal the SQLAlchemy models (no missing migration)."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db.base import Base

    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], f"Models and migrations differ — run `make migration NAME=...`: {diff}"


def test_audit_events_are_append_only(db) -> None:  # type: ignore[no-untyped-def]
    db.add(AuditEvent(action="test.event", resource_type="test", details={}))
    db.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("UPDATE audit_events SET action = 'tampered'"))
    db.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("DELETE FROM audit_events"))
    db.rollback()


def test_enum_check_constraints_exist(db) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(DBAPIError):
        db.execute(
            text(
                "INSERT INTO users (id, email, platform_role, is_active) "
                "VALUES (gen_random_uuid(), 'x@example.test', 'superuser', true)"
            )
        )
    db.rollback()
