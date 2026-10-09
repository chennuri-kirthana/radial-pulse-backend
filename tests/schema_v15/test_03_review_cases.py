"""db/tests/03-review-cases.sql (R1-R8, M7, L2): a fresh v15 database + the Family Dental seed,
as the table owner."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.schema_v15.helpers import (
    CHECK,
    FOREIGN_KEY,
    MEHUL,
    POOJA,
    PRIVILEGE,
    RAVI,
    UNIQUE,
    Db,
    fresh_database,
)

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db() -> Iterator[Db]:
    with fresh_database("t03", seed=True) as d:
        yield d


def test_r1_work_item_assignee_from_another_clinic_refused(db: Db) -> None:
    db.ok(
        "INSERT INTO users(id,email,platform_role) VALUES ('00000000-0000-0000-0000-00000000ab01','stranger@other.in','clinic_member')"
    )
    db.error(
        "UPDATE improvement_work_items SET assignee_user_id='00000000-0000-0000-0000-00000000ab01'",
        CHECK,
        "does not belong to clinic",
    )


def test_r1b_assignee_clinic_administrator_or_practitioner_allowed(db: Db) -> None:
    assert db.ok(f"UPDATE improvement_work_items SET assignee_user_id='{MEHUL}'") == 1
    assert db.ok(f"UPDATE improvement_work_items SET assignee_user_id='{POOJA}'") == 1


def test_r2_audit_events_cannot_be_changed_deleted_or_truncated(db: Db) -> None:
    db.error("UPDATE audit_events SET action='edited'", PRIVILEGE, "append-only")
    db.error("DELETE FROM audit_events", PRIVILEGE, "append-only")
    db.error("TRUNCATE audit_events", PRIVILEGE, "append-only")


def test_r3_updated_at_changes_by_itself(db: Db) -> None:
    before = db.one("SELECT updated_at FROM clinics LIMIT 1")
    db.ok("UPDATE clinics SET name=name||''")
    assert db.one("SELECT updated_at FROM clinics LIMIT 1") > before


def test_r4_stage_history_with_unknown_stage_refused(db: Db) -> None:
    db.error(
        "INSERT INTO clinic_stage_changes(clinic_id,from_stage,to_stage) SELECT id,'foo','bar' FROM clinics LIMIT 1",
        CHECK,
    )


def test_r5_stage_history_written_automatically_and_matches_the_clinic(db: Db) -> None:
    history = db.rows(
        "SELECT from_stage, to_stage, note, changed_by_user_id IS NOT NULL FROM clinic_stage_changes ORDER BY changed_at"
    )
    assert history == [
        (None, "prospective_client", "lead added", True),
        ("prospective_client", "presence_discovered", None, True),
        ("presence_discovered", "active_client", "signed", True),
    ]
    assert (
        db.one(
            "SELECT c.stage = (SELECT to_stage FROM clinic_stage_changes s WHERE s.clinic_id=c.id ORDER BY changed_at DESC LIMIT 1) FROM clinics c"
        )
        is True
    )


def test_r6_dsm_cannot_be_deleted_only_deactivated(db: Db) -> None:
    db.error(f"DELETE FROM users WHERE id='{RAVI}'", FOREIGN_KEY)
    assert db.ok(f"UPDATE users SET is_active=false WHERE id='{RAVI}'") == 1


def test_r7_last_clinic_administrator_cannot_be_removed(db: Db) -> None:
    db.error(
        "DELETE FROM clinic_members WHERE role='clinic_administrator'",
        CHECK,
        "must keep at least one active Clinic Administrator",
    )
    assert db.one("SELECT count(*) FROM clinic_members") == 1


def test_r8_same_profile_with_trailing_slash_is_a_duplicate(db: Db) -> None:
    db.error(
        "INSERT INTO clinic_online_profiles(clinic_id,platform,url,discovered_by) SELECT id,'instagram','https://instagram.com/familydental_amd/','x' FROM clinics LIMIT 1",
        UNIQUE,
        "uq_clinic_online_profiles_clinic_platform_url",
    )


def test_m7_approving_a_photo_needs_reviewed_at(db: Db) -> None:
    db.error(
        "UPDATE photos SET review_state='approved' WHERE review_state='pending'",
        CHECK,
        "ck_photos_reviewed_has_date",
    )


def test_l2_restore_must_clear_the_archive_reason(db: Db) -> None:
    with db.conn.transaction(force_rollback=True):
        db.ok("UPDATE clinics SET is_active=false, archived_reason='not interested'")
        db.error("UPDATE clinics SET is_active=true", CHECK, "ck_clinics_archive_reason")
    with db.conn.transaction(force_rollback=True):
        db.ok("UPDATE clinics SET is_active=false, archived_reason='not interested'")
        assert db.ok("UPDATE clinics SET is_active=true, archived_reason=NULL") == 1
