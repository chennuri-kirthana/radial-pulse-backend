"""Database-level tenant isolation (PostgreSQL row-level security), tested as the REAL app role.

These tests bypass the application layer on purpose: they prove that even a query that
"forgets" `WHERE clinic_id = …` cannot see or write another clinic's rows.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.core.enums import ClinicRole, ClinicStage, PlatformRole
from app.db.tenant import set_tenant_scope
from app.models import AuditEvent, ClinicAssignment, ClinicPractitioner, ClinicStageHistory, Practitioner
from tests.conftest import API_ROOT, TEST_DATABASE_URL
from tests.factories import add_member, assign, make_clinic, make_practitioner, make_user

pytestmark = pytest.mark.integration


def test_every_table_has_row_level_security(engines) -> None:  # type: ignore[no-untyped-def]
    """Since 0007 EVERY application table is locked in the database, the people tables included."""
    owner, _ = engines
    insp = inspect(owner)
    with owner.connect() as conn:
        enabled = {r[0] for r in conn.execute(text("SELECT relname FROM pg_class WHERE relrowsecurity"))}
    missing = sorted(set(insp.get_table_names()) - enabled - {"alembic_version"})
    assert missing == [], f"no row-level security on {missing} — add it in a migration"


def test_no_scope_means_no_rows(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    clinic = make_clinic(db, "A")
    make_practitioner(db, clinic)
    with session_factory() as s:
        assert s.query(Practitioner).count() == 0  # fail closed


def test_scope_hides_other_clinics_even_without_where(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    a, b = make_clinic(db, "A"), make_clinic(db, "B")
    make_practitioner(db, a, "Dr A")
    make_practitioner(db, b, "Dr B")
    with session_factory() as s:
        set_tenant_scope(s, [a.id])
        names = {d.full_name for d in s.query(Practitioner).all()}  # no clinic filter on purpose
    assert names == {"Dr A"}


def test_cannot_write_into_another_clinic(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    a, b = make_clinic(db, "A"), make_clinic(db, "B")
    doctor_of_b = make_practitioner(db, b, "Dr B")
    with session_factory() as s:
        set_tenant_scope(s, [a.id])
        s.add(ClinicPractitioner(clinic_id=b.id, practitioner_id=doctor_of_b.id))
        with pytest.raises(DBAPIError, match="row-level security"):
            s.commit()
    with session_factory() as s:
        set_tenant_scope(s, [a.id])
        # ...and a practitioner cannot be created in a business you have no clinic in.
        s.add(Practitioner(organization_id=b.organization_id, full_name="Intruder"))
        with pytest.raises(DBAPIError, match="row-level security"):
            s.commit()


def test_cannot_move_a_row_to_another_clinic(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    a, b = make_clinic(db, "A"), make_clinic(db, "B")
    practitioner = make_practitioner(db, a)
    with session_factory() as s:
        set_tenant_scope(s, [a.id])
        with pytest.raises(DBAPIError, match="row-level security"):
            s.execute(
                text("UPDATE clinic_practitioners SET clinic_id = :b WHERE practitioner_id = :d"),
                {"b": b.id, "d": practitioner.id},
            )


def test_scope_is_transaction_local_on_pooled_connections(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    a = make_clinic(db, "A")
    make_practitioner(db, a)
    with session_factory() as s:
        set_tenant_scope(s, [a.id])
        assert s.query(Practitioner).count() == 1
    with session_factory() as s2:  # likely the same pooled connection
        assert s2.query(Practitioner).count() == 0


def test_app_role_cannot_edit_or_delete_audit_events(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    a = make_clinic(db, "A")
    db.add(AuditEvent(action="t.e", resource_type="t", clinic_id=a.id, details={}))
    db.commit()
    with session_factory() as s:
        set_tenant_scope(s, [a.id])
        with pytest.raises(DBAPIError, match="permission denied"):
            s.execute(text("UPDATE audit_events SET action = 'tampered'"))
        s.rollback()
        set_tenant_scope(s, [a.id])
        with pytest.raises(DBAPIError, match="permission denied"):
            s.execute(text("DELETE FROM audit_events"))


def test_app_role_cannot_touch_migration_bookkeeping(session_factory) -> None:  # type: ignore[no-untyped-def]
    with session_factory() as s, pytest.raises(DBAPIError, match="permission denied"):
        s.execute(text("SELECT * FROM alembic_version"))


def test_api_request_runs_under_the_clinic_scope(client, db, auth) -> None:  # type: ignore[no-untyped-def]
    """End to end: a clinic user reading practitioners through the API only ever gets their clinic's rows."""
    a, b = make_clinic(db, "A"), make_clinic(db, "B")
    make_practitioner(db, a, "Dr A")
    make_practitioner(db, b, "Dr B")
    user = make_user(db, PlatformRole.CLINIC_USER)
    add_member(db, a, user, ClinicRole.CLINIC_ADMINISTRATOR)
    r = client.get(f"/api/v1/clinics/{a.id}/practitioners", headers=auth(user))
    assert [d["full_name"] for d in r.json()["items"]] == ["Dr A"]


def test_stage_history_is_tenant_scoped_and_append_only(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    a, b = make_clinic(db, "A"), make_clinic(db, "B")
    db.add_all(
        [
            ClinicStageHistory(clinic_id=a.id, to_stage=ClinicStage.PROSPECTIVE_CLIENT),
            ClinicStageHistory(clinic_id=b.id, to_stage=ClinicStage.PROSPECTIVE_CLIENT),
        ]
    )
    db.commit()
    with session_factory() as s:
        set_tenant_scope(s, [a.id])
        assert s.query(ClinicStageHistory).count() == 1
        with pytest.raises(DBAPIError, match="permission denied"):
            s.execute(text("UPDATE clinic_stage_history SET note = 'edited'"))
        s.rollback()
        set_tenant_scope(s, [a.id])
        with pytest.raises(DBAPIError, match="permission denied"):
            s.execute(text("DELETE FROM clinic_stage_history"))
        s.rollback()
        set_tenant_scope(s, [a.id])
        s.add(ClinicStageHistory(clinic_id=b.id, to_stage=ClinicStage.ACTIVE_CLIENT))
        with pytest.raises(DBAPIError, match="row-level security"):
            s.commit()


def test_database_allows_only_one_active_dsm_per_clinic(db) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy.exc import IntegrityError

    clinic = make_clinic(db, "A")
    first = make_user(db, PlatformRole.DIGITAL_SUCCESS_MANAGER)
    second = make_user(db, PlatformRole.DIGITAL_SUCCESS_MANAGER)
    assign(db, clinic, first)
    db.add(ClinicAssignment(clinic_id=clinic.id, user_id=second.id))
    with pytest.raises(IntegrityError, match="uq_clinic_assignments_one_active"):
        db.commit()
    db.rollback()
    db.add(ClinicAssignment(clinic_id=clinic.id, user_id=second.id, is_active=False))
    db.commit()  # an ENDED row is fine (history)


def test_archiving_without_a_reason_is_refused_by_the_database(db) -> None:  # type: ignore[no-untyped-def]
    clinic = make_clinic(db, "A")
    with pytest.raises(DBAPIError, match="ck_clinics_archive_reason"):
        db.execute(text("UPDATE clinics SET is_active = false WHERE id = :id"), {"id": clinic.id})
    db.rollback()


def test_milestone1_migrations_keep_and_backfill_existing_data() -> None:
    """0005-0009 on a scratch database that already has data at 0004, then back down again."""
    from alembic import command
    from alembic.config import Config

    assert TEST_DATABASE_URL is not None
    base = make_url(TEST_DATABASE_URL)
    scratch = f"rp_m1_migration_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{scratch}"'))
    engine = create_engine(base.set(database=scratch))
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))

    def migrate(target: str, down: bool = False) -> None:
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            (command.downgrade if down else command.upgrade)(cfg, target)

    try:
        migrate("0004")
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO organizations (id, name) VALUES ('00000000-0000-0000-0000-00000000000a', 'O');
                    INSERT INTO clinics (id, organization_id, name, country, is_active) VALUES
                      ('00000000-0000-0000-0000-00000000000c', '00000000-0000-0000-0000-00000000000a',
                       'C', 'IN', true),
                      ('00000000-0000-0000-0000-00000000000d', '00000000-0000-0000-0000-00000000000a',
                       'D', 'IN', false);
                    INSERT INTO users (id, email, platform_role, is_active) VALUES
                      ('00000000-0000-0000-0000-000000000001', 'a@x.test', 'digital_success_manager', true),
                      ('00000000-0000-0000-0000-000000000002', 'b@x.test', 'digital_success_manager', true);
                    INSERT INTO clinic_assignments (id, clinic_id, user_id, is_active, created_at) VALUES
                      (gen_random_uuid(), '00000000-0000-0000-0000-00000000000c',
                       '00000000-0000-0000-0000-000000000001', true, now() - interval '2 days'),
                      (gen_random_uuid(), '00000000-0000-0000-0000-00000000000c',
                       '00000000-0000-0000-0000-000000000002', true, now());
                    INSERT INTO doctors (id, clinic_id, full_name, is_active, created_at) VALUES
                      (gen_random_uuid(), '00000000-0000-0000-0000-00000000000c', 'Dr First', true,
                       now() - interval '1 day'),
                      (gen_random_uuid(), '00000000-0000-0000-0000-00000000000c', 'Dr Second', true, now());
                    INSERT INTO assets (id, clinic_id, kind, mime_type, size_bytes, storage_key, version,
                                        provenance, status, approval_state)
                      VALUES (gen_random_uuid(), '00000000-0000-0000-0000-00000000000c', 'doctor_photo',
                              'image/png', 1, 'clinics/c/doctor_photo/x.png', 1, '{}', 'uploaded', 'draft');
                    """
                )
            )
        migrate("0006")
        with engine.connect() as conn:
            q = lambda sql: conn.execute(text(sql)).all()  # noqa: E731
            assert q("SELECT full_name FROM practitioners WHERE is_primary") == [("Dr First",)]
            assert q("SELECT u.email FROM clinic_assignments a JOIN users u ON u.id = a.user_id "
                     "WHERE a.is_active") == [("a@x.test",)]  # fmt: skip
            assert q("SELECT count(*) FROM clinic_assignments") == [(2,)]  # the ended row is kept
            assert sorted(q("SELECT name, stage FROM clinics")) == [
                ("C", "prospective_client"),
                ("D", "prospective_client"),
            ]
            assert q("SELECT count(*) FROM clinic_stage_history") == [(2,)]
            assert q("SELECT archived_reason IS NOT NULL FROM clinics WHERE name = 'D'") == [(True,)]
            assert q("SELECT kind FROM assets") == [("practitioner_photo",)]
            assert q("SELECT indexname FROM pg_indexes WHERE indexname = 'ix_practitioners_clinic_id'")
        migrate("head")  # 0007-0009: every doctor keeps its business and gets one clinic link
        with engine.connect() as conn:
            q = lambda sql: conn.execute(text(sql)).all()  # noqa: E731
            assert q("SELECT count(*) FROM practitioners WHERE organization_id IS NULL") == [(0,)]
            assert q("SELECT count(*) FROM clinic_practitioners") == [(2,)]
            assert q("SELECT p.full_name FROM clinic_practitioners cp JOIN practitioners p "
                     "ON p.id = cp.practitioner_id WHERE cp.is_primary") == [("Dr First",)]  # fmt: skip
        migrate("0004", down=True)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM doctors")).scalar() == 2
            assert conn.execute(text("SELECT kind FROM assets")).scalar() == "doctor_photo"
        migrate("head")  # and up again
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}"'))
        admin.dispose()


def test_role_migration_maps_legacy_rows() -> None:
    """Migration 0002 on a scratch database: legacy roles are mapped, not dropped."""
    from alembic import command
    from alembic.config import Config

    assert TEST_DATABASE_URL is not None
    base = make_url(TEST_DATABASE_URL)
    scratch = f"rp_migration_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{scratch}"'))
    engine = create_engine(base.set(database=scratch))
    try:
        cfg = Config(str(API_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "0001")
            conn.execute(
                text(
                    """
                    INSERT INTO organizations (id, name) VALUES ('00000000-0000-0000-0000-00000000000a', 'O');
                    INSERT INTO clinics (id, organization_id, name, country, is_active)
                      VALUES ('00000000-0000-0000-0000-00000000000c', '00000000-0000-0000-0000-00000000000a',
                              'C', 'IN', true);
                    INSERT INTO users (id, email, platform_role, is_active) VALUES
                      ('00000000-0000-0000-0000-000000000001', 'm@x.test', 'internal_manager', true),
                      ('00000000-0000-0000-0000-000000000002', 'o@x.test', 'client', true),
                      ('00000000-0000-0000-0000-000000000003', 'd@x.test', 'client', true),
                      ('00000000-0000-0000-0000-000000000004', 'p@x.test', 'platform_admin', true);
                    INSERT INTO clinic_assignments (id, clinic_id, user_id, role, is_active) VALUES
                      (gen_random_uuid(), '00000000-0000-0000-0000-00000000000c',
                       '00000000-0000-0000-0000-000000000001', 'account_manager', true),
                      (gen_random_uuid(), '00000000-0000-0000-0000-00000000000c',
                       '00000000-0000-0000-0000-000000000001', 'analyst', true);
                    INSERT INTO clinic_memberships (id, clinic_id, user_id, role, is_active) VALUES
                      (gen_random_uuid(), '00000000-0000-0000-0000-00000000000c',
                       '00000000-0000-0000-0000-000000000002', 'owner', true),
                      (gen_random_uuid(), '00000000-0000-0000-0000-00000000000c',
                       '00000000-0000-0000-0000-000000000003', 'doctor', true);
                    """
                )
            )
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "0002")
        with engine.connect() as conn:
            roles = dict(conn.execute(text("SELECT email, platform_role FROM users")).all())
            memberships = sorted(r[0] for r in conn.execute(text("SELECT role FROM clinic_memberships")))
            assignments = conn.execute(text("SELECT count(*) FROM clinic_assignments")).scalar()
        assert roles == {
            "m@x.test": "digital_success_manager",
            "o@x.test": "clinic_user",
            "d@x.test": "clinic_user",
            "p@x.test": "platform_administrator",
        }
        assert memberships == ["clinic_administrator", "clinic_team_member"]
        assert assignments == 1
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}"'))
        admin.dispose()


# ------------------------------------------------------------------ people tables (0007)
def test_people_tables_follow_the_signed_in_person(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    """users / memberships / assignments / organizations / notifications are locked too."""
    from app.db.tenant import set_current_user
    from app.models import ClinicMembership, Notification, Organization, User
    from app.repositories.users import UserRepository

    a, b = make_clinic(db, "A"), make_clinic(db, "B")
    admin = make_user(db, PlatformRole.PLATFORM_ADMINISTRATOR, email="admin@x.test")
    priya = make_user(db, PlatformRole.DIGITAL_SUCCESS_MANAGER, email="priya@x.test")
    rahul = make_user(db, PlatformRole.CLINIC_USER, email="rahul@x.test")
    bose = make_user(db, PlatformRole.CLINIC_USER, email="bose@x.test")
    assign(db, a, priya)
    add_member(db, a, rahul, ClinicRole.CLINIC_ADMINISTRATOR)
    add_member(db, b, bose, ClinicRole.CLINIC_ADMINISTRATOR)
    db.add_all([Notification(user_id=priya.id, kind="k", title="for priya"),
                Notification(user_id=rahul.id, kind="k", title="for rahul")])  # fmt: skip
    db.commit()

    def emails(s):  # type: ignore[no-untyped-def]
        return {u.email for u in s.query(User).all()}  # no filter on purpose

    with session_factory() as s:
        assert emails(s) == set()  # nothing known → nothing visible (fail closed)
        # ...but sign-in / add-team-member lookups still work:
        assert UserRepository(s).find_id_by_sub(bose.cognito_sub) == bose.id
        match = UserRepository(s).find_by_email("BOSE@x.test")
        assert match is not None and match.platform_role is PlatformRole.CLINIC_USER

    with session_factory() as s:  # Dr Rahul, clinic A
        set_current_user(s, rahul.id)
        set_tenant_scope(s, [a.id])
        assert emails(s) == {"rahul@x.test", "priya@x.test"}  # himself + his clinic's DSM
        assert s.query(ClinicMembership).count() == 1
        assert {o.name for o in s.query(Organization).all()} == {"A Org"}
        assert [n.title for n in s.query(Notification).all()] == ["for rahul"]

    with session_factory() as s:  # DSM Priya: staff see staff, plus people of her clinics
        set_current_user(s, priya.id, is_staff=True)
        set_tenant_scope(s, [a.id])
        assert emails(s) == {"admin@x.test", "priya@x.test", "rahul@x.test"}

    with session_factory() as s:  # a clinic user may never create a staff account
        set_current_user(s, rahul.id)
        set_tenant_scope(s, [a.id])
        s.add(User(email="evil@x.test", platform_role=PlatformRole.PLATFORM_ADMINISTRATOR))
        with pytest.raises(DBAPIError, match="row-level security"):
            s.commit()

    with session_factory() as s:  # the Platform Administrator sees everyone
        set_current_user(s, admin.id, is_staff=True)
        set_tenant_scope(s, None)
        assert len(emails(s)) == 4


def test_practitioner_of_another_business_is_invisible(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    a, b = make_clinic(db, "A"), make_clinic(db, "B")  # two different businesses
    make_practitioner(db, a, "Dr A")
    make_practitioner(db, b, "Dr B")
    branch = make_clinic(db, "A branch", organization=a.organization)
    with session_factory() as s:
        set_tenant_scope(s, [branch.id])
        # Same business: Dr A is visible from the sibling branch (so they can be linked there).
        assert {p.full_name for p in s.query(Practitioner).all()} == {"Dr A"}


# --------------------------------------------------------- status copy in step (0009)
def test_report_status_cannot_drift_from_its_approval(db) -> None:  # type: ignore[no-untyped-def]
    """The approvals row owns the review status; the copy on the assessment must match at commit."""
    from app.core.enums import ApprovalState, AssessmentStatus, PublicationState
    from app.models import Approval, Assessment

    clinic = make_clinic(db, "A")
    assessment = Assessment(
        clinic_id=clinic.id, sequence=1, status=AssessmentStatus.COMPLETED, methodology_version="t"
    )
    db.add(assessment)
    db.flush()
    db.add(Approval(clinic_id=clinic.id, resource_type="assessment", resource_id=assessment.id,
                    state=ApprovalState.SUBMITTED))  # fmt: skip
    assessment.approval_state = ApprovalState.SUBMITTED
    db.commit()  # in step: fine

    assessment.publication_state = PublicationState.PUBLISHED  # sneaking past the approval flow
    with pytest.raises(DBAPIError, match=r"out of step|must change through approvals"):
        db.commit()
    db.rollback()


def test_approval_created_as_draft_then_submitted_commits(db) -> None:  # type: ignore[no-untyped-def]
    """The real app flow: the approval row starts as draft and moves on in the same transaction.

    The status checks run at COMMIT but must look at the rows as they are THEN, not as they were
    when the approval was first inserted (draft), or every first submit would fail.
    """
    from app.core.enums import ApprovalState, AssessmentStatus, PublicationState
    from app.models import Approval, Assessment

    clinic = make_clinic(db, "A")
    assessment = Assessment(
        clinic_id=clinic.id, sequence=1, status=AssessmentStatus.COMPLETED, methodology_version="t"
    )
    db.add(assessment)
    db.flush()
    approval = Approval(clinic_id=clinic.id, resource_type="assessment", resource_id=assessment.id,
                        state=ApprovalState.DRAFT)  # fmt: skip
    db.add(approval)
    db.flush()  # INSERT as draft
    approval.state = ApprovalState.SUBMITTED
    assessment.approval_state = ApprovalState.SUBMITTED
    db.commit()  # must succeed

    approval.state = ApprovalState.APPROVED
    approval.publication_state = PublicationState.PUBLISHED
    assessment.approval_state = ApprovalState.APPROVED
    assessment.publication_state = PublicationState.PUBLISHED
    db.commit()
    db.refresh(assessment)
    assert assessment.publication_state == PublicationState.PUBLISHED


def test_app_role_cannot_delete_audit_rows_even_with_the_archive_flag(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    a = make_clinic(db, "A")
    db.add(AuditEvent(action="t.e", resource_type="t", clinic_id=a.id, details={}))
    db.commit()
    with session_factory() as s:
        set_tenant_scope(s, [a.id])
        s.execute(text("SELECT set_config('app.archiving', 'on', true)"))
        with pytest.raises(DBAPIError, match="permission denied"):
            s.execute(text("DELETE FROM audit_events"))


# ------------------------------------------------------------------ 0010: chat, connections, settings
def test_chat_is_locked_per_clinic_and_never_changed(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    from app.core.enums import ChatSide
    from app.db.tenant import set_current_user
    from app.models import ChatMessage, ChatReadState

    a, b = make_clinic(db, "A"), make_clinic(db, "B")
    rahul = make_user(db, PlatformRole.CLINIC_USER)
    bose = make_user(db, PlatformRole.CLINIC_USER)
    db.add_all(
        [
            ChatMessage(clinic_id=a.id, sender_name="Priya", sender_side=ChatSide.RADIAL_PULSE, body="to A"),
            ChatMessage(clinic_id=b.id, sender_name="Priya", sender_side=ChatSide.RADIAL_PULSE, body="to B"),
            ChatReadState(clinic_id=a.id, user_id=bose.id),  # someone else's reading position in A
        ]
    )
    db.commit()

    with session_factory() as s:
        set_current_user(s, rahul.id)
        set_tenant_scope(s, [a.id])
        assert [m.body for m in s.query(ChatMessage).all()] == ["to A"]  # no filter on purpose
        assert s.query(ChatReadState).count() == 0  # only your own reading position
        s.add(ChatMessage(clinic_id=b.id, sender_name="x", sender_side=ChatSide.CLINIC, body="sneak"))
        with pytest.raises(DBAPIError, match="row-level security"):
            s.commit()

    with session_factory() as s:  # messages cannot be edited or deleted by the app login
        set_current_user(s, rahul.id)
        set_tenant_scope(s, [a.id])
        with pytest.raises(DBAPIError, match="permission denied"):
            s.execute(text("UPDATE chat_messages SET body = 'edited'"))
    with session_factory() as s:
        set_tenant_scope(s, [a.id])
        with pytest.raises(DBAPIError, match="permission denied"):
            s.execute(text("DELETE FROM chat_messages"))


def test_connections_follow_the_clinic_rule(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    from app.core.enums import ConnectionPlatform, ConnectionStatus
    from app.models import PlatformConnection

    a, b = make_clinic(db, "A"), make_clinic(db, "B")
    for clinic in (a, b):
        db.add(
            PlatformConnection(
                clinic_id=clinic.id, platform=ConnectionPlatform.INSTAGRAM, status=ConnectionStatus.CONNECTED
            )
        )
    db.commit()
    with session_factory() as s:
        set_tenant_scope(s, [a.id])
        assert [c.clinic_id for c in s.query(PlatformConnection).all()] == [a.id]
        with pytest.raises(DBAPIError, match="permission denied"):
            s.execute(text("DELETE FROM platform_connections"))


def test_platform_settings_readable_by_all_changed_only_with_all_clinics(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    from app.models import PlatformSettings

    a = make_clinic(db, "A")
    with session_factory() as s:  # a clinic scope can read …
        set_tenant_scope(s, [a.id])
        assert s.get(PlatformSettings, 1) is not None
        # … but an UPDATE silently matches no row (the policy hides it from writes).
        changed = s.execute(text("UPDATE platform_settings SET organization_name = 'hacked'")).rowcount
        s.commit()
        assert changed == 0
    with session_factory() as s:  # Platform Administrator scope
        set_tenant_scope(s, None)
        assert s.execute(text("UPDATE platform_settings SET support_phone = '123'")).rowcount == 1
        s.commit()


def test_notification_switches_are_private_but_senders_can_check_them(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    from app.core.enums import NotificationCategory, NotificationChannel
    from app.db.tenant import set_current_user
    from app.models import NotificationPreference
    from app.repositories.settings import SettingsRepository

    a = make_clinic(db, "A")
    priya = make_user(db, PlatformRole.DIGITAL_SUCCESS_MANAGER)
    rahul = make_user(db, PlatformRole.CLINIC_USER)
    db.add(
        NotificationPreference(
            user_id=priya.id,
            category=NotificationCategory.WORK_ITEM_ASSIGNED,
            channel=NotificationChannel.IN_APP,
            enabled=False,
        )
    )
    db.commit()
    with session_factory() as s:  # Dr Rahul cannot read Priya's switches …
        set_current_user(s, rahul.id)
        set_tenant_scope(s, [a.id])
        assert s.query(NotificationPreference).count() == 0
        # … but sending her a notification can still ask "is it on?" (true/false only).
        repo = SettingsRepository(s)
        cat, ch = NotificationCategory.WORK_ITEM_ASSIGNED, NotificationChannel.IN_APP
        assert repo.notification_enabled(priya.id, cat, ch) is False
        assert repo.notification_enabled(rahul.id, cat, ch) is True  # default: on


def test_even_the_all_clinics_scope_sees_only_its_own_switches(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    from app.core.enums import NotificationCategory, NotificationChannel
    from app.db.tenant import set_current_user
    from app.models import NotificationPreference

    admin = make_user(db, PlatformRole.PLATFORM_ADMINISTRATOR)
    priya = make_user(db, PlatformRole.DIGITAL_SUCCESS_MANAGER)
    db.add(
        NotificationPreference(
            user_id=priya.id,
            category=NotificationCategory.CLINIC_ASSIGNED,
            channel=NotificationChannel.EMAIL,
            enabled=False,
        )
    )
    db.commit()
    with session_factory() as s:
        set_current_user(s, admin.id, is_staff=True)
        set_tenant_scope(s, None)  # Platform Administrator: every clinic
        assert s.query(NotificationPreference).count() == 0


# ------------------------------------------------------------------ 0011: composite keys
def test_links_across_clinics_are_refused_by_the_database(db) -> None:  # type: ignore[no-untyped-def]
    """Even the OWNER (no row-level security) cannot link a row to another clinic's parent."""
    from app.core.enums import AssessmentComponentKey, AssessmentStatus, AssetKind, ComponentStatus
    from app.models import Assessment, AssessmentComponent, Asset

    a, b = make_clinic(db, "A"), make_clinic(db, "B")
    photo_a = Asset(
        clinic_id=a.id,
        kind=AssetKind.CLINIC_PHOTO,
        mime_type="image/png",
        size_bytes=1,
        storage_key=f"clinics/{a.id}/p.png",
    )
    assessment_a = Assessment(
        clinic_id=a.id, sequence=1, status=AssessmentStatus.COMPLETED, methodology_version="t"
    )
    db.add_all([photo_a, assessment_a])
    db.commit()

    b.cover_asset_id = photo_a.id  # clinic B using clinic A's photo
    with pytest.raises(DBAPIError, match="fk_clinics_cover_asset_id_assets"):
        db.commit()
    db.rollback()

    db.add(
        AssessmentComponent(
            assessment_id=assessment_a.id,
            clinic_id=b.id,
            key=AssessmentComponentKey.WEBSITE,
            status=ComponentStatus.COMPLETED,
        )
    )
    with pytest.raises(DBAPIError, match="fk_assessment_components_assessment_id_assessments"):
        db.commit()
    db.rollback()


def test_one_finding_per_code_per_section_and_rerun_still_works(db) -> None:  # type: ignore[no-untyped-def]
    from app.core.enums import AssessmentComponentKey, AssessmentStatus, ComponentStatus, FindingPriority
    from app.models import Assessment, AssessmentComponent, AssessmentFinding
    from app.repositories.assessments import AssessmentRepository

    a = make_clinic(db, "A")
    assessment = Assessment(
        clinic_id=a.id, sequence=1, status=AssessmentStatus.COMPLETED, methodology_version="t"
    )
    db.add(assessment)
    db.flush()
    section = AssessmentComponent(
        assessment_id=assessment.id,
        clinic_id=a.id,
        key=AssessmentComponentKey.WEBSITE,
        status=ComponentStatus.COMPLETED,
    )
    db.add(section)
    db.flush()

    def finding(title: str) -> AssessmentFinding:
        return AssessmentFinding(
            assessment_id=assessment.id,
            component_id=section.id,
            clinic_id=a.id,
            code="website.slow",
            title=title,
            priority=FindingPriority.LOW,
            evidence={"items": []},
        )

    db.add(finding("first"))
    db.commit()
    db.add(finding("duplicate"))
    with pytest.raises(DBAPIError, match="uq_assessment_findings_component_id_code"):
        db.commit()
    db.rollback()
    # The worker's re-run: delete the section's findings, add the new ones, one transaction.
    AssessmentRepository(db).delete_findings_of_component(a.id, section.id)
    db.add(finding("re-run"))
    db.commit()
    assert [f.title for f in db.query(AssessmentFinding).all()] == ["re-run"]
