"""db/tests/04-access-rules-tests.sql: row-level security, on a fresh v15 database + the
Family Dental seed. Visibility is checked as the app role (radial_app) for each person;
writes W1-W17, first sign-in, the read-only service role, L4, M5 and M4."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests.schema_v15.helpers import (
    ANIL,
    CHECK,
    KIRAN,
    MEHUL,
    POOJA,
    PRACTITIONER,
    PRIVILEGE,
    PRIYA,
    RAVI,
    SITA,
    UNIQUE,
    Db,
    fresh_database,
)

pytestmark = pytest.mark.integration

CC01 = "'00000000-0000-0000-0000-00000000cc01'"
KEY = "clinics/00000000-0000-0000-0000-00000000cc01"
SEEN_COLUMNS = (
    "clinics", "orgs", "users", "members", "pracs", "reports", "work", "msgs",
    "photos", "voice", "conn", "audit", "stage_hist", "alloc",
)  # fmt: skip
SEEN = """SELECT (SELECT count(*) FROM clinics),(SELECT count(*) FROM client_organizations),(SELECT count(*) FROM users),
 (SELECT count(*) FROM clinic_members),(SELECT count(*) FROM practitioners),(SELECT count(*) FROM digital_presence_assessments),
 (SELECT count(*) FROM improvement_work_items),(SELECT count(*) FROM collaboration_messages),(SELECT count(*) FROM photos),
 (SELECT count(*) FROM voice_samples),(SELECT count(*) FROM connected_accounts),(SELECT count(*) FROM audit_events),
 (SELECT count(*) FROM clinic_stage_changes),(SELECT count(*) FROM portfolio_allocations)"""


@pytest.fixture(scope="module")
def db() -> Iterator[Db]:
    with fresh_database("t04", seed=True) as d:
        # second business with its DSM and clinic admin; a team member at Family Dental; an unpublished report
        d.ok(
            f"""INSERT INTO users (id,email,full_name,platform_role) VALUES
             ('{PRIYA}','priya@radialpulse.in','Priya (other DSM)','digital_success_manager'),
             ('{KIRAN}','kiran@smilecare.example','Kiran (other clinic admin)','clinic_member'),
             ('{SITA}','sita@familydental.example','Sita (team member)','clinic_member')"""
        )
        d.ok(
            "INSERT INTO client_organizations (id,name) VALUES ('00000000-0000-0000-0000-00000000bb02','SmileCare LLP')"
        )
        d.ok(
            "INSERT INTO clinics (id,client_organization_id,name) VALUES ('00000000-0000-0000-0000-00000000cc02','00000000-0000-0000-0000-00000000bb02','SmileCare Satellite')"
        )
        d.ok(
            f"INSERT INTO portfolio_allocations (client_organization_id,user_id) VALUES ('00000000-0000-0000-0000-00000000bb02','{PRIYA}')"
        )
        d.ok(
            f"""INSERT INTO clinic_members (clinic_id,user_id,role) VALUES
             ('00000000-0000-0000-0000-00000000cc02','{KIRAN}','clinic_administrator'),
             ({CC01},'{SITA}','clinic_team_member')"""
        )
        d.ok(
            f"INSERT INTO collaboration_messages (clinic_id,sender_user_id,sender_name,sender_side,body) VALUES ('00000000-0000-0000-0000-00000000cc02','{KIRAN}','Kiran','clinic','SmileCare private message')"
        )
        d.ok(
            f"INSERT INTO digital_presence_assessments (id,clinic_id,status) VALUES ('00000000-0000-0000-0000-00000000ee02',{CC01},'completed')"
        )
        d.ok(
            "INSERT INTO client_organizations (id,name) VALUES ('00000000-0000-0000-0000-00000000bb03','New Lead Clinic Pvt')"
        )  # no DSM yet
        yield d


@pytest.fixture(autouse=True)
def back_to_owner(db: Db) -> Iterator[None]:
    yield
    db.as_owner()


# ---------------------------------------------------------------------------- VISIBILITY
@pytest.mark.parametrize(
    ("who", "user_id", "expected"),
    [
        #                                  clin org usr mem prac rep work msg pho voi con aud stg alloc
        ("admin Anil", ANIL,                 (2, 3, 7, 3, 1, 2, 1, 3, 3, 2, 1, 7, 4, 2)),
        ("DSM Ravi (Family Dental)", RAVI,   (1, 1, 4, 2, 1, 2, 1, 2, 3, 2, 1, 6, 3, 1)),
        ("DSM Priya (SmileCare)", PRIYA,     (1, 1, 2, 1, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1)),
        ("clinic admin Mehul", MEHUL,        (1, 1, 4, 2, 1, 1, 1, 2, 3, 2, 1, 6, 0, 1)),
        ("team member Sita", SITA,           (1, 1, 4, 2, 1, 1, 1, 2, 3, 0, 1, 0, 0, 1)),
        ("practitioner Pooja", POOJA,        (1, 1, 4, 0, 1, 1, 0, 2, 3, 2, 0, 0, 0, 0)),
        ("other clinic admin Kiran", KIRAN,  (1, 1, 2, 1, 0, 0, 0, 1, 0, 0, 0, 0, 0, 1)),
        ("nobody (no user set)", None,       (0,) * 14),
    ],
)  # fmt: skip
def test_visibility(db: Db, who: str, user_id: str | None, expected: tuple[int, ...]) -> None:
    db.as_user(user_id)
    seen = dict(zip(SEEN_COLUMNS, db.one(SEEN), strict=True))
    assert seen == dict(zip(SEEN_COLUMNS, expected, strict=True)), who


# -------------------------------------------------------------------------------- WRITES
def test_w01_other_clinic_admin_cannot_edit_the_clinic(db: Db) -> None:
    db.as_user(KIRAN)
    assert db.ok(f"UPDATE clinics SET name='hacked' WHERE id={CC01}") == 0


def test_w02_clinic_admin_edits_details_but_not_the_stage(db: Db) -> None:
    db.as_user(MEHUL)
    assert db.ok(f"UPDATE clinics SET phone='+91 79 4000 9999' WHERE id={CC01}") == 1
    db.error(
        f"UPDATE clinics SET stage='client_discussion' WHERE id={CC01}",
        PRIVILEGE,
        "only the DSM or a Platform Administrator",
    )


def test_w03_shared_practitioner_record(db: Db) -> None:
    db.as_user(MEHUL)
    assert db.ok(f"UPDATE practitioners SET bio='changed by clinic admin' WHERE id='{PRACTITIONER}'") == 0
    db.as_user(POOJA)
    assert db.ok(f"UPDATE practitioners SET bio='Updated by Dr Pooja' WHERE id='{PRACTITIONER}'") == 1
    db.error(
        f"UPDATE practitioners SET registration_number='X-1' WHERE id='{PRACTITIONER}'",
        PRIVILEGE,
        "name, registration number or login",
    )


def test_w04_dsm_edits_practitioner_name(db: Db) -> None:
    db.as_user(RAVI)
    assert db.ok(f"UPDATE practitioners SET full_name='Dr. Pooja Shah' WHERE id='{PRACTITIONER}'") == 1


def test_w05_only_staff_approve_photos(db: Db) -> None:
    db.as_user(MEHUL)
    db.error(
        "UPDATE photos SET review_state='approved', reviewed_at=now() WHERE review_state='pending'",
        PRIVILEGE,
        "review or sort photos",
    )
    db.as_user(RAVI)
    assert (
        db.ok("UPDATE photos SET review_state='approved', reviewed_at=now() WHERE review_state='pending'")
        == 1
    )


def test_w06_who_uploads_photos(db: Db) -> None:
    sql = (
        "INSERT INTO photos(clinic_id,practitioner_id,attire,outfit_no,angle,original_key,mime_type,size_bytes) "
        f"VALUES ({CC01},'{PRACTITIONER}','with_apron',1,'left_45','{KEY}/photos/%s.jpg','image/jpeg',10)"
    )
    db.as_user(RAVI)
    db.error(sql % "d1", PRIVILEGE, "row-level security")
    db.as_user(SITA)
    db.error(sql % "d2", PRIVILEGE, "row-level security")
    db.as_user(POOJA)
    assert db.ok(sql % "d3") == 1


def test_w07_who_sends_messages(db: Db) -> None:
    sql = "INSERT INTO collaboration_messages(clinic_id,sender_user_id,sender_name,sender_side,body) VALUES ({c},'{u}','{n}','{s}','{b}')"
    db.as_user(SITA)
    db.error(sql.format(c=CC01, u=SITA, n="Sita", s="clinic", b="hi"), PRIVILEGE, "row-level security")
    db.as_user(POOJA)
    assert db.ok(sql.format(c=CC01, u=POOJA, n="Dr Pooja", s="clinic", b="hello")) == 1
    db.error(
        sql.format(c=CC01, u=RAVI, n="Ravi", s="radial_pulse", b="fake"), PRIVILEGE, "row-level security"
    )


def test_w08_clinic_admin_cannot_make_himself_platform_administrator(db: Db) -> None:
    db.as_user(MEHUL)
    db.error(
        f"UPDATE users SET platform_role='platform_administrator' WHERE id='{MEHUL}'",
        PRIVILEGE,
        "only a Platform Administrator",
    )


def test_w09_dsm_cannot_allocate_himself(db: Db) -> None:
    db.as_user(RAVI)
    db.error(
        f"INSERT INTO portfolio_allocations(client_organization_id,user_id) VALUES ('00000000-0000-0000-0000-00000000bb02','{RAVI}')",
        PRIVILEGE,
        "row-level security",
    )


def test_w10_nobody_edits_the_audit_log(db: Db) -> None:
    db.as_user(RAVI)
    db.error("UPDATE audit_events SET action='x'", PRIVILEGE, "permission denied")


def test_w11_stage_history_only_by_trigger(db: Db) -> None:
    db.as_user(RAVI)
    db.error(
        f"INSERT INTO clinic_stage_changes(clinic_id,to_stage) VALUES ({CC01},'client_discussion')",
        PRIVILEGE,
        "permission denied",
    )
    assert db.ok(f"UPDATE clinics SET stage='client_discussion' WHERE id={CC01}") == 1
    assert db.one(
        f"SELECT to_stage, changed_by_user_id = '{RAVI}' FROM clinic_stage_changes ORDER BY changed_at DESC LIMIT 1"
    ) == ("client_discussion", True)


def test_w12_last_clinic_administrator_cannot_remove_himself(db: Db) -> None:
    db.as_user(MEHUL)
    db.error(
        f"DELETE FROM clinic_members WHERE user_id='{MEHUL}'",
        CHECK,
        "at least one active Clinic Administrator",
    )


def test_w13_cleaned_url_is_a_duplicate(db: Db) -> None:
    db.as_user(MEHUL)
    db.error(
        f"INSERT INTO clinic_online_profiles(clinic_id,platform,url,discovered_by) VALUES ({CC01},'instagram','http://WWW.Instagram.com/familydental_amd/','manual')",
        UNIQUE,
    )


def test_w14_work_item_assignee_from_other_clinic_refused(db: Db) -> None:
    db.as_user(RAVI)
    db.error(
        f"UPDATE improvement_work_items SET assignee_user_id='{KIRAN}'", CHECK, "does not belong to clinic"
    )


def test_w15_only_platform_administrator_creates_leads(db: Db) -> None:
    db.as_user(RAVI)
    db.error(
        "INSERT INTO client_organizations(id,name) VALUES ('00000000-0000-0000-0000-00000000bb04','Lead by Ravi')",
        PRIVILEGE,
        "row-level security",
    )
    db.as_user(ANIL)
    assert (
        db.one(
            "INSERT INTO client_organizations(id,name) VALUES ('00000000-0000-0000-0000-00000000bb04','Lead by Anil') RETURNING name"
        )
        == "Lead by Anil"
    )
    assert (
        db.one(
            "INSERT INTO clinics(id,client_organization_id,name) VALUES ('00000000-0000-0000-0000-00000000cc04','00000000-0000-0000-0000-00000000bb04','Lead clinic') RETURNING name"
        )
        == "Lead clinic"
    )


LEADS = """SELECT (SELECT count(*) FROM client_organizations WHERE id IN ('00000000-0000-0000-0000-00000000bb03','00000000-0000-0000-0000-00000000bb04')),
                  (SELECT count(*) FROM clinics WHERE id='00000000-0000-0000-0000-00000000cc04')"""


def test_w16_only_the_admin_sees_unallocated_leads(db: Db) -> None:
    db.as_user(ANIL)
    assert db.one(LEADS) == (2, 1)
    db.as_user(RAVI)
    assert db.one(LEADS) == (0, 0)
    db.as_user(PRIYA)
    assert db.one(LEADS) == (0, 0)


def test_w17_dsm_sees_the_lead_once_allocated(db: Db) -> None:
    db.as_user(ANIL)
    assert (
        db.ok(
            f"INSERT INTO portfolio_allocations(client_organization_id,user_id) VALUES ('00000000-0000-0000-0000-00000000bb04','{RAVI}')"
        )
        == 1
    )
    db.as_user(RAVI)
    assert db.one(
        "SELECT (SELECT count(*) FROM client_organizations WHERE id='00000000-0000-0000-0000-00000000bb04'), "
        "(SELECT count(*) FROM clinics WHERE id='00000000-0000-0000-0000-00000000cc04')"
    ) == (1, 1)


# ------------------------------------------------------------------- FIRST SIGN-IN
def test_first_sign_in_links_the_invited_user(db: Db) -> None:
    db.ok(
        "INSERT INTO users(id,email,platform_role) VALUES ('00000000-0000-0000-0000-00000000aa08','newadmin@familydental.example','clinic_member')"
    )
    db.as_user(None)
    expected = [("00000000-0000-0000-0000-00000000aa08", "clinic_member", True)]
    first = db.rows(
        "SELECT id::text, platform_role, is_active FROM rp_user_for_login('sub-new','NewAdmin@FamilyDental.example')"
    )
    assert first == expected
    second = db.rows("SELECT id::text, platform_role, is_active FROM rp_user_for_login('sub-new','anything')")
    assert second == expected
    assert db.one("SELECT count(*) FROM rp_user_for_login('sub-x','nobody@x.in')") == 0


# -------------------------------------------------------------- SERVICE (read only)
def test_service_role_reads_only_what_it_may(db: Db) -> None:
    db.ok("SET ROLE radial_service")
    # clinics: Family Dental, SmileCare, Lead clinic · photos: only approved ones · profiles: 2
    assert db.one(
        "SELECT (SELECT count(*) FROM clinics), (SELECT count(*) FROM photos), (SELECT count(*) FROM clinic_online_profiles)"
    ) == (3, 3, 2)
    db.error("SELECT secret_ref FROM connected_accounts", PRIVILEGE, "permission denied")
    db.error("SELECT count(*) FROM users", PRIVILEGE, "permission denied")
    db.error("UPDATE clinics SET name='x'", PRIVILEGE, "permission denied")


# ----------------------------------------------------------------------- L4, M5, M4
def test_l4_inactive_practitioner_link_takes_his_photos_offline(db: Db) -> None:
    by_state = f"SELECT review_state, review_note, count(*) FROM photos WHERE practitioner_id='{PRACTITIONER}' GROUP BY 1,2 ORDER BY 1"
    assert db.rows(by_state) == [("approved", None, 1), ("pending", None, 1)]
    assert (
        db.ok(f"UPDATE clinic_practitioners SET is_active=false WHERE practitioner_id='{PRACTITIONER}'") == 1
    )
    assert db.rows(by_state) == [("pending", None, 2)]


def test_m5_profile_urls_are_cleaned(db: Db) -> None:
    assert [r[0] for r in db.rows("SELECT url FROM clinic_online_profiles ORDER BY url")] == [
        "https://instagram.com/familydental_amd",
        "https://maps.google.com?cid=123456",
    ]


def test_m4_deleting_a_whole_clinic_still_works(db: Db) -> None:
    with db.conn.transaction(force_rollback=True):
        assert db.ok("DELETE FROM clinics WHERE id='00000000-0000-0000-0000-00000000cc02'") == 1
