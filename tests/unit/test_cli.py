from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app import cli
from app.core.enums import PlatformRole
from app.models import AuditEvent, User


def test_create_platform_admin_is_idempotent(monkeypatch, session_factory: sessionmaker, db) -> None:  # type: ignore[no-untyped-def,type-arg]
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: session_factory)
    assert "Created" in cli.create_platform_admin("Admin@Example.test", "Ada")
    assert "already" in cli.create_platform_admin("admin@example.test", None)
    # Assert through the owner session: platform-level audit rows are not readable by the
    # app role without the all-clinics scope (row-level security).
    user = db.query(User).filter_by(email="admin@example.test").one()
    assert user.platform_role is PlatformRole.PLATFORM_ADMINISTRATOR
    assert db.query(AuditEvent).filter_by(action="user.create").count() == 1


def test_refuses_to_change_existing_non_admin(monkeypatch, session_factory: sessionmaker, db) -> None:  # type: ignore[no-untyped-def,type-arg]
    db.add(User(email="client@example.test", platform_role=PlatformRole.CLINIC_USER))
    db.commit()
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: session_factory)
    with pytest.raises(SystemExit):
        cli.create_platform_admin("client@example.test", None)


def test_seed_demo_adds_sample_data_once(db) -> None:  # type: ignore[no-untyped-def]
    from app.core.enums import ClinicStage
    from app.models import Clinic, ClinicAssignment, ClinicStageHistory, WorkItem
    from app.seed import seed_demo

    assert "6 clinics" in seed_demo(db)
    assert db.query(Clinic).count() == 6
    # One active DSM per clinic at most, and a full stage diary for the Customer clinic.
    assert db.query(ClinicAssignment).filter_by(is_active=True).count() == 5
    elite = db.query(Clinic).filter_by(name="Elite Dental Clinic").one()
    assert elite.stage is ClinicStage.ACTIVE_CLIENT
    assert db.query(ClinicStageHistory).filter_by(clinic_id=elite.id).count() == 5
    assert db.query(WorkItem).count() == 6
    assert "already exists" in seed_demo(db)
    assert db.query(Clinic).count() == 6
