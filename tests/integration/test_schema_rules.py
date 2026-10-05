"""Data rules from the schema review (migration 0012), enforced by PostgreSQL itself."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.enums import AssessmentStatus
from app.models import Assessment
from tests.factories import make_clinic

pytestmark = pytest.mark.integration


def test_only_one_queued_or_running_assessment_per_clinic(db) -> None:  # type: ignore[no-untyped-def]
    clinic = make_clinic(db, "A")
    db.add(
        Assessment(clinic_id=clinic.id, sequence=1, status=AssessmentStatus.QUEUED, methodology_version="t")
    )
    db.commit()
    db.add(
        Assessment(clinic_id=clinic.id, sequence=2, status=AssessmentStatus.RUNNING, methodology_version="t")
    )
    with pytest.raises(DBAPIError, match="uq_assessments_one_in_progress"):
        db.commit()
    db.rollback()
    # Once the first one is finished, the next one may start.
    db.execute(text("UPDATE assessments SET status = 'completed' WHERE clinic_id = :c"), {"c": clinic.id})
    db.add(
        Assessment(clinic_id=clinic.id, sequence=2, status=AssessmentStatus.QUEUED, methodology_version="t")
    )
    db.commit()


@pytest.mark.parametrize(
    ("sql", "rule"),
    [
        ("UPDATE clinics SET country = 'in'", "ck_clinics_country_code"),
        ("UPDATE clinics SET latitude = 95, longitude = 10", "ck_clinics_latitude_range"),
        ("UPDATE assessments SET overall_score = 101", "ck_assessments_score_range"),
        ("UPDATE assessments SET sequence = 0", "ck_assessments_sequence_positive"),
    ],
)
def test_impossible_values_are_refused(db, sql, rule) -> None:  # type: ignore[no-untyped-def]
    clinic = make_clinic(db, "A")
    db.add(
        Assessment(
            clinic_id=clinic.id, sequence=1, status=AssessmentStatus.COMPLETED, methodology_version="t"
        )
    )
    db.commit()
    with pytest.raises(DBAPIError, match=rule):
        db.execute(text(sql))
    db.rollback()


def test_emails_must_be_stored_lower_case(db) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(DBAPIError, match="ck_users_email_lowercase"):
        db.execute(
            text(
                "INSERT INTO users (id, email, platform_role, is_active) "
                "VALUES (gen_random_uuid(), 'Priya@Example.test', 'clinic_user', true)"
            )
        )
    db.rollback()
