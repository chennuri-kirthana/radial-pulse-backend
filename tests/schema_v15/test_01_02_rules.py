"""db/tests/01-rules-tests.sql (T1-T24) then 02-rules-tests-more.sql (T30-T38), on ONE empty
v15 database, as the table owner. The tests run in file order and build on each other."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.schema_v15.helpers import CHECK, FOREIGN_KEY, NO_COLUMN, NOT_NULL, UNIQUE, Db, fresh_database

pytestmark = pytest.mark.integration

C = "'00000000-0000-0000-0000-0000000000c1'"
KEY = "clinics/00000000-0000-0000-0000-0000000000c1"


@pytest.fixture(scope="module")
def db() -> Iterator[Db]:
    with fresh_database("t01", seed=False) as d:
        d.ok(
            """INSERT INTO users(id,email,platform_role) VALUES
             ('00000000-0000-0000-0000-0000000000a1','owner@x.in','clinic_member'),
             ('00000000-0000-0000-0000-0000000000a2','doc@x.in','practitioner'),
             ('00000000-0000-0000-0000-0000000000a3','admin2@x.in','clinic_member'),
             ('00000000-0000-0000-0000-0000000000a4','dsm@x.in','digital_success_manager')"""
        )
        d.ok(
            "INSERT INTO client_organizations(id,name) VALUES ('00000000-0000-0000-0000-0000000000b1','Org')"
        )
        d.ok(
            f"INSERT INTO clinics(id,client_organization_id,name) VALUES ({C},'00000000-0000-0000-0000-0000000000b1','Family Dental')"
        )
        yield d


# ------------------------------------------------------------------------ 01-rules-tests.sql
def test_t01_practitioner_with_practitioner_login(db: Db) -> None:
    assert (
        db.ok(
            "INSERT INTO practitioners(id,full_name,user_id) VALUES ('00000000-0000-0000-0000-0000000000d1','Dr Pooja','00000000-0000-0000-0000-0000000000a2')"
        )
        == 1
    )


def test_t02_practitioner_linked_to_clinic_member_login_refused(db: Db) -> None:
    db.error(
        "INSERT INTO practitioners(id,full_name,user_id) VALUES ('00000000-0000-0000-0000-0000000000d2','Dr Two','00000000-0000-0000-0000-0000000000a1')",
        CHECK,
        "needs a user with platform_role practitioner",
    )
    assert (
        db.ok(
            "INSERT INTO practitioners(id,full_name) VALUES ('00000000-0000-0000-0000-0000000000d2','Dr Two')"
        )
        == 1
    )
    assert (
        db.ok(
            f"INSERT INTO clinic_practitioners(clinic_id,practitioner_id,is_primary) VALUES ({C},'00000000-0000-0000-0000-0000000000d1',true)"
        )
        == 1
    )


def test_t03_clinic_administrator(db: Db) -> None:
    assert (
        db.ok(
            f"INSERT INTO clinic_members(clinic_id,user_id,role) VALUES ({C},'00000000-0000-0000-0000-0000000000a1','clinic_administrator')"
        )
        == 1
    )


def test_t04_second_clinic_administrator(db: Db) -> None:
    assert (
        db.ok(
            f"INSERT INTO clinic_members(clinic_id,user_id,role) VALUES ({C},'00000000-0000-0000-0000-0000000000a3','clinic_administrator')"
        )
        == 1
    )


def test_t05_same_member_twice_refused(db: Db) -> None:
    db.error(
        f"INSERT INTO clinic_members(clinic_id,user_id,role) VALUES ({C},'00000000-0000-0000-0000-0000000000a1','clinic_team_member')",
        UNIQUE,
    )


def test_t06_practitioner_login_as_clinic_member_refused(db: Db) -> None:
    db.error(
        f"INSERT INTO clinic_members(clinic_id,user_id,role) VALUES ({C},'00000000-0000-0000-0000-0000000000a2','clinic_administrator')",
        CHECK,
        "needs a user with platform_role clinic_member",
    )


def test_t07_unknown_member_role_refused(db: Db) -> None:
    db.error(
        "UPDATE clinic_members SET role='owner' WHERE user_id='00000000-0000-0000-0000-0000000000a1'",
        CHECK,
        "ck_clinic_members_role",
    )


def test_t08_second_practitioner_at_clinic(db: Db) -> None:
    assert (
        db.ok(
            f"INSERT INTO clinic_practitioners(clinic_id,practitioner_id) VALUES ({C},'00000000-0000-0000-0000-0000000000d2')"
        )
        == 1
    )


def test_t09_portfolio_allocation_needs_a_dsm(db: Db) -> None:
    assert (
        db.ok(
            "INSERT INTO portfolio_allocations(client_organization_id,user_id) VALUES ('00000000-0000-0000-0000-0000000000b1','00000000-0000-0000-0000-0000000000a4')"
        )
        == 1
    )
    db.error(
        "INSERT INTO portfolio_allocations(client_organization_id,user_id) VALUES ('00000000-0000-0000-0000-0000000000b1','00000000-0000-0000-0000-0000000000a3')",
        CHECK,
        "needs a user with platform_role digital_success_manager",
    )


def test_t10_archive_without_reason_refused(db: Db) -> None:
    db.error(f"UPDATE clinics SET is_active=false WHERE id={C}", CHECK, "ck_clinics_archive_reason")


def test_t11_publish_a_draft_report_refused(db: Db) -> None:
    db.error(
        f"INSERT INTO digital_presence_assessments(id,clinic_id,status,publication_state,published_at) VALUES ('00000000-0000-0000-0000-000000000e01',{C},'completed','published',now())",
        CHECK,
        "published_only_if_approved",
    )


def test_t12_approve_then_publish(db: Db) -> None:
    assert (
        db.ok(
            f"INSERT INTO digital_presence_assessments(id,clinic_id,status) VALUES ('00000000-0000-0000-0000-000000000e01',{C},'completed')"
        )
        == 1
    )
    assert (
        db.ok(
            "UPDATE digital_presence_assessments SET review_state='approved', reviewed_at=now(), publication_state='published', published_at=now() WHERE id='00000000-0000-0000-0000-000000000e01'"
        )
        == 1
    )


def test_t13_unapprove_a_published_report_refused(db: Db) -> None:
    db.error(
        "UPDATE digital_presence_assessments SET review_state='redo_requested' WHERE id='00000000-0000-0000-0000-000000000e01'",
        CHECK,
        "published_only_if_approved",
    )


def test_t14_fix_now_work_item_from_same_clinic_report(db: Db) -> None:
    assert (
        db.ok(
            f"INSERT INTO improvement_work_items(clinic_id,title,source_assessment_id,opportunity_code) VALUES ({C},'Fix title','00000000-0000-0000-0000-000000000e01','title_missing')"
        )
        == 1
    )


def test_t15_practitioner_photo_one_live_one_waiting(db: Db) -> None:
    cols = "clinic_id,practitioner_id,attire,outfit_no,angle,original_key,mime_type,size_bytes"
    vals = f"{C},'00000000-0000-0000-0000-0000000000d1','with_apron',1,'front'"
    assert (
        db.ok(
            f"INSERT INTO photos({cols},review_state,reviewed_at) VALUES ({vals},'{KEY}/photos/1.jpg','image/jpeg',100,'approved',now())"
        )
        == 1
    )
    db.error(
        f"INSERT INTO photos({cols},review_state,reviewed_at) VALUES ({vals},'{KEY}/photos/2.jpg','image/jpeg',100,'approved',now())",
        UNIQUE,
        "uq_photos_practitioner_one_live",
    )
    assert db.ok(f"INSERT INTO photos({cols}) VALUES ({vals},'{KEY}/photos/3.jpg','image/jpeg',100)") == 1


def test_t16_practitioner_photo_missing_angle_refused(db: Db) -> None:
    db.error(
        f"INSERT INTO photos(clinic_id,practitioner_id,attire,outfit_no,original_key,mime_type,size_bytes) VALUES ({C},'00000000-0000-0000-0000-0000000000d1','with_apron',1,'{KEY}/photos/4.jpg','image/jpeg',100)",
        CHECK,
        "ck_photos_kind_fields",
    )


def test_t17_unsorted_clinic_photo_needs_category_before_approval(db: Db) -> None:
    assert (
        db.ok(
            f"INSERT INTO photos(id,clinic_id,original_key,mime_type,size_bytes) VALUES ('00000000-0000-0000-0000-0000000000f1',{C},'{KEY}/photos/6.jpg','image/jpeg',100)"
        )
        == 1
    )
    db.error(
        "UPDATE photos SET review_state='approved', reviewed_at=now() WHERE id='00000000-0000-0000-0000-0000000000f1'",
        CHECK,
        "ck_photos_kind_fields",
    )
    assert (
        db.ok(
            "UPDATE photos SET category='reception_waiting', review_state='approved', reviewed_at=now() WHERE id='00000000-0000-0000-0000-0000000000f1'"
        )
        == 1
    )


def test_t18_one_live_cover(db: Db) -> None:
    sql = f"INSERT INTO photos(clinic_id,category,original_key,mime_type,size_bytes,review_state,reviewed_at) VALUES ({C},'cover','{KEY}/photos/%s.jpg','image/jpeg',100,'approved',now())"
    assert db.ok(sql % "c1") == 1
    db.error(sql % "c2", UNIQUE, "uq_photos_logo_cover_one_live")


def test_t19_reject_photo_without_note_refused(db: Db) -> None:
    db.error(
        "UPDATE photos SET review_state='rejected' WHERE id='00000000-0000-0000-0000-0000000000f1'",
        CHECK,
        "ck_photos_rejected_has_note",
    )


def test_t20_voice_samples(db: Db) -> None:
    sql = f"INSERT INTO voice_samples(clinic_id,practitioner_id,title,original_key,mime_type,size_bytes) VALUES ({C},'%s','%s','{KEY}/voice/%s.m4a','audio/mp4',100)"
    db.error(
        sql % ("00000000-0000-0000-0000-0000000000e9", "X", "0"),
        FOREIGN_KEY,
        "fk_voice_samples_clinic_practitioner",
    )
    assert db.ok(sql % ("00000000-0000-0000-0000-0000000000d1", "Reading sample 2", "1")) == 1
    db.error(
        sql % ("00000000-0000-0000-0000-0000000000d1", "reading sample 2", "2"),
        UNIQUE,
        "uq_voice_samples_one_per_title",
    )


def test_t21_audit_row_survives_deleting_the_user(db: Db) -> None:
    db.ok(
        f"INSERT INTO audit_events(clinic_id,actor_user_id,actor_type,action,resource_type,resource_id) VALUES ({C},'00000000-0000-0000-0000-0000000000a3','user','photo.uploaded','photo','x')"
    )
    assert db.ok("DELETE FROM clinic_members WHERE user_id='00000000-0000-0000-0000-0000000000a3'") == 1
    assert db.ok("DELETE FROM users WHERE id='00000000-0000-0000-0000-0000000000a3'") == 1
    assert db.one("SELECT actor_user_id IS NOT NULL FROM audit_events WHERE action='photo.uploaded'") is True


def test_t22_oauth_ticket_without_user_refused(db: Db) -> None:
    db.error(
        f"INSERT INTO oauth_states(clinic_id,provider,state_hash,redirect_uri,expires_at) VALUES ({C},'google','h','https://x',now()+interval '10 min')",
        NOT_NULL,
        "started_by_user_id",
    )


def test_t23_notification_preference_twice_refused(db: Db) -> None:
    sql = "INSERT INTO notification_preferences(user_id,category,channel) VALUES ('00000000-0000-0000-0000-0000000000a1','portfolio_allocated','email')"
    assert db.ok(sql) == 1
    db.error(sql, UNIQUE)


def test_t24_removing_practitioner_from_clinic_deletes_his_photos_and_voice(db: Db) -> None:
    db.ok("DELETE FROM improvement_work_items")
    assert (
        db.ok("DELETE FROM clinic_practitioners WHERE practitioner_id='00000000-0000-0000-0000-0000000000d1'")
        == 1
    )
    assert db.one(
        "SELECT (SELECT count(*) FROM photos WHERE practitioner_id='00000000-0000-0000-0000-0000000000d1'), (SELECT count(*) FROM voice_samples)"
    ) == (0, 0)


# ------------------------------------------------------------------- 02-rules-tests-more.sql
def test_t30_role_change_of_a_clinic_member_refused(db: Db) -> None:
    db.error(
        "UPDATE users SET platform_role='practitioner' WHERE id='00000000-0000-0000-0000-0000000000a1'",
        CHECK,
        "cannot change platform_role",
    )


def test_t31_role_change_of_dsm_and_practitioner_refused(db: Db) -> None:
    db.error(
        "UPDATE users SET platform_role='platform_administrator' WHERE id='00000000-0000-0000-0000-0000000000a4'",
        CHECK,
        "cannot change platform_role",
    )
    db.error(
        "UPDATE users SET platform_role='clinic_member' WHERE id='00000000-0000-0000-0000-0000000000a2'",
        CHECK,
        "cannot change platform_role",
    )


def test_t32_role_change_without_links_allowed(db: Db) -> None:
    db.ok(
        "INSERT INTO users(id,email,platform_role) VALUES ('00000000-0000-0000-0000-0000000000a9','new@x.in','clinic_member')"
    )
    assert (
        db.ok("UPDATE users SET platform_role='practitioner' WHERE id='00000000-0000-0000-0000-0000000000a9'")
        == 1
    )
    assert (
        db.ok(
            "UPDATE users SET platform_role='clinic_member', full_name='Owner' WHERE id='00000000-0000-0000-0000-0000000000a1'"
        )
        == 1
    )


def test_t33_deleting_a_practitioner_removes_his_clinic_links(db: Db) -> None:
    assert db.ok("DELETE FROM practitioners WHERE id='00000000-0000-0000-0000-0000000000d2'") == 1
    assert (
        db.one(
            "SELECT count(*) FROM clinic_practitioners WHERE practitioner_id='00000000-0000-0000-0000-0000000000d2'"
        )
        == 0
    )


def test_t38_voice_has_no_review_columns(db: Db) -> None:
    db.error(
        f"INSERT INTO voice_samples(clinic_id,practitioner_id,title,original_key,mime_type,size_bytes,review_state) VALUES ({C},'00000000-0000-0000-0000-0000000000d1','New','{KEY}/voice/9.m4a','audio/mp4',100,'pending')",
        NO_COLUMN,
    )
