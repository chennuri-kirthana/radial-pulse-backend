"""Database safety nets from migration 0013, tested as the REAL app role WITHOUT the API.

Each test acts like a buggy or bypassed application: plain SQL / ORM writes with only the
database scope set. PostgreSQL must still refuse what the API refuses.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.enums import (
    ApprovalState,
    AssessmentStatus,
    AssetKind,
    AssetStatus,
    ClinicRole,
    PlatformRole,
    PublicationState,
)
from app.db.tenant import set_current_user, set_tenant_scope
from app.models import (
    Approval,
    ApprovalNote,
    Assessment,
    Asset,
    ClinicMembership,
    MediaTaxonomyValue,
    ReportArtifact,
    User,
)
from tests.factories import add_member, assign, make_clinic, make_user

pytestmark = pytest.mark.integration


def _asset(db, clinic, kind=AssetKind.CLINIC_PHOTO, status=AssetStatus.UPLOADED) -> Asset:  # type: ignore[no-untyped-def]
    asset = Asset(
        clinic_id=clinic.id, kind=kind, mime_type="image/png", size_bytes=1,
        storage_key=f"clinics/{clinic.id}/{kind.value}/{uuid.uuid4()}.png", status=status,
    )  # fmt: skip
    db.add(asset)
    db.commit()
    return asset


def _submitted(db, asset) -> Approval:  # type: ignore[no-untyped-def]
    approval = Approval(
        clinic_id=asset.clinic_id, resource_type="asset", resource_id=asset.id, state=ApprovalState.SUBMITTED
    )
    db.add(approval)
    asset.approval_state = ApprovalState.SUBMITTED
    db.commit()
    return approval


@pytest.fixture
def people(db):  # type: ignore[no-untyped-def]
    clinic = make_clinic(db, "A")
    clinic_admin = make_user(db, PlatformRole.CLINIC_USER)
    dsm = make_user(db, PlatformRole.DIGITAL_SUCCESS_MANAGER)
    admin = make_user(db, PlatformRole.PLATFORM_ADMINISTRATOR)
    add_member(db, clinic, clinic_admin, ClinicRole.CLINIC_ADMINISTRATOR)
    assign(db, clinic, dsm)
    return clinic, clinic_admin, dsm, admin


def _as_clinic_user(s, clinic, user) -> None:  # type: ignore[no-untyped-def]
    set_current_user(s, user.id, is_staff=False)
    set_tenant_scope(s, [clinic.id])


def _as_dsm(s, clinic, user) -> None:  # type: ignore[no-untyped-def]
    set_current_user(s, user.id, is_staff=True)
    set_tenant_scope(s, [clinic.id])


# ------------------------------------------------------------------ media review
def test_clinic_people_cannot_decide_on_clinic_media_in_the_database(db, session_factory, people) -> None:  # type: ignore[no-untyped-def]
    clinic, clinic_admin, dsm, _ = people
    asset = _asset(db, clinic)
    approval = _submitted(db, asset)

    for state in ("approved", "rejected", "redo_requested"):
        with session_factory() as s:
            _as_clinic_user(s, clinic, clinic_admin)
            with pytest.raises(DBAPIError, match="only Radial Pulse staff review"):
                s.execute(
                    text("UPDATE approvals SET state = :st WHERE id = :id"), {"st": state, "id": approval.id}
                )
    with session_factory() as s:  # nor sneak a decider or a message onto the row
        _as_clinic_user(s, clinic, clinic_admin)
        with pytest.raises(DBAPIError, match="only Radial Pulse staff review"):
            s.execute(
                text("UPDATE approvals SET decided_by_user_id = :u WHERE id = :id"),
                {"u": clinic_admin.id, "id": approval.id},
            )
    with session_factory() as s:  # nor INSERT an already-approved review for a new file
        _as_clinic_user(s, clinic, clinic_admin)
        other = s.get(Asset, _asset(db, clinic).id)
        assert other is not None
        s.add(Approval(clinic_id=clinic.id, resource_type="asset", resource_id=other.id,
                       state=ApprovalState.APPROVED))  # fmt: skip
        with pytest.raises(DBAPIError, match="only Radial Pulse staff review"):
            s.flush()

    with session_factory() as s:  # the DSM may (and the copy on the asset follows)
        _as_dsm(s, clinic, dsm)
        s.execute(text("UPDATE approvals SET state = 'approved' WHERE id = :id"), {"id": approval.id})
        s.execute(text("UPDATE assets SET approval_state = 'approved' WHERE id = :id"), {"id": asset.id})
        s.commit()


def test_nothing_is_reviewed_before_the_upload_is_confirmed_in_the_database(
    db, session_factory, people
) -> None:  # type: ignore[no-untyped-def]
    clinic, clinic_admin, dsm, _ = people
    pending = _asset(db, clinic, status=AssetStatus.PENDING_UPLOAD)
    for setup, user in ((_as_clinic_user, clinic_admin), (_as_dsm, dsm)):
        with session_factory() as s:
            setup(s, clinic, user)
            s.add(Approval(clinic_id=clinic.id, resource_type="asset", resource_id=pending.id,
                           state=ApprovalState.SUBMITTED))  # fmt: skip
            with pytest.raises(DBAPIError, match="before its upload is confirmed"):
                s.flush()
    with session_factory() as s:  # once uploaded, the clinic may submit it
        _as_clinic_user(s, clinic, clinic_admin)
        s.execute(text("UPDATE assets SET status = 'uploaded' WHERE id = :id"), {"id": pending.id})
        s.add(Approval(clinic_id=clinic.id, resource_type="asset", resource_id=pending.id,
                       state=ApprovalState.SUBMITTED))  # fmt: skip
        s.execute(text("UPDATE assets SET approval_state = 'submitted' WHERE id = :id"), {"id": pending.id})
        s.commit()


# ------------------------------------------------------------------ notes + staff-only reviews
def test_internal_notes_are_staff_only_in_the_database(db, session_factory, people) -> None:  # type: ignore[no-untyped-def]
    clinic, clinic_admin, dsm, _ = people
    approval = _submitted(db, _asset(db, clinic))
    db.add(ApprovalNote(clinic_id=clinic.id, approval_id=approval.id, author_user_id=dsm.id, body="internal"))
    db.commit()

    with session_factory() as s:
        _as_clinic_user(s, clinic, clinic_admin)
        assert s.query(ApprovalNote).count() == 0  # no filter on purpose
        s.add(ApprovalNote(clinic_id=clinic.id, approval_id=approval.id, body="fake"))
        with pytest.raises(DBAPIError, match="row-level security"):
            s.flush()
    with session_factory() as s:
        _as_dsm(s, clinic, dsm)
        assert [n.body for n in s.query(ApprovalNote).all()] == ["internal"]
        with pytest.raises(DBAPIError, match="permission denied"):
            s.execute(text("UPDATE approval_notes SET body = 'edited'"))


def test_assessment_reviews_are_invisible_to_clinic_people(db, session_factory, people) -> None:  # type: ignore[no-untyped-def]
    clinic, clinic_admin, dsm, _ = people
    assessment = Assessment(
        clinic_id=clinic.id, sequence=1, status=AssessmentStatus.COMPLETED, methodology_version="t"
    )
    db.add(assessment)
    db.flush()
    db.add(Approval(clinic_id=clinic.id, resource_type="assessment", resource_id=assessment.id))
    db.commit()
    with session_factory() as s:
        _as_clinic_user(s, clinic, clinic_admin)
        assert s.query(Approval).count() == 0
        s.add(Approval(clinic_id=clinic.id, resource_type="assessment", resource_id=uuid.uuid4()))
        with pytest.raises(DBAPIError, match=r"row-level security|only Radial Pulse staff review"):
            s.flush()
    with session_factory() as s:
        _as_dsm(s, clinic, dsm)
        assert s.query(Approval).count() == 1


# ------------------------------------------------------------------ report files
def test_unpublished_report_files_are_invisible_to_clinic_people(db, session_factory, people) -> None:  # type: ignore[no-untyped-def]
    clinic, clinic_admin, dsm, _ = people
    report_file = _asset(db, clinic, kind=AssetKind.REPORT)
    stray = _asset(db, clinic, kind=AssetKind.REPORT)
    photo = _asset(db, clinic)
    report = ReportArtifact(
        clinic_id=clinic.id, report_type="t", report_key="k", title="T", asset_id=report_file.id
    )
    db.add(report)
    db.commit()

    def visible(setup, user):  # type: ignore[no-untyped-def]
        with session_factory() as s:
            setup(s, clinic, user)
            return {a.id for a in s.query(Asset).all()}  # no filter on purpose

    assert visible(_as_clinic_user, clinic_admin) == {photo.id}
    assert visible(_as_dsm, dsm) == {report_file.id, stray.id, photo.id}
    report.publication_state = PublicationState.PUBLISHED  # no approval row: the owner may set it
    db.commit()
    assert visible(_as_clinic_user, clinic_admin) == {photo.id, report_file.id}


# ------------------------------------------------------------------ roles
def test_nobody_changes_their_own_role_in_the_database(db, session_factory, people) -> None:  # type: ignore[no-untyped-def]
    clinic, clinic_admin, dsm, admin = people
    other_clinic = make_clinic(db, "B")

    def attempt(setup, sql: str, params: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
        with session_factory() as s:
            setup(s)
            s.execute(text(sql), params)
            s.commit()

    def me(user, all_clinics=False, staff=False):  # type: ignore[no-untyped-def]
        def _setup(s):  # type: ignore[no-untyped-def]
            set_current_user(s, user.id, is_staff=staff)
            set_tenant_scope(s, None if all_clinics else [clinic.id, other_clinic.id])

        return _setup

    role = "UPDATE users SET platform_role = :r WHERE id = :id"
    active = "UPDATE users SET is_active = :a WHERE id = :id"
    refused = "role and active flag change only by a Platform Administrator"
    with pytest.raises(DBAPIError, match=refused):  # a clinic user promotes themselves
        attempt(me(clinic_admin), role, {"r": "platform_administrator", "id": clinic_admin.id})
    with pytest.raises(DBAPIError, match=refused):  # a DSM promotes themselves
        attempt(me(dsm, staff=True), role, {"r": "platform_administrator", "id": dsm.id})
    with pytest.raises(DBAPIError, match=refused):  # even the Admin cannot change their OWN role
        attempt(me(admin, all_clinics=True, staff=True), role, {"r": "clinic_user", "id": admin.id})
    with pytest.raises(DBAPIError, match=refused):
        attempt(me(admin, all_clinics=True, staff=True), active, {"a": False, "id": admin.id})
    with pytest.raises(DBAPIError, match=refused):  # a DSM cannot deactivate a clinic user
        attempt(me(dsm, staff=True), active, {"a": False, "id": clinic_admin.id})
    # The Platform Administrator may change SOMEONE ELSE (the Users screen: deactivate).
    attempt(me(admin, all_clinics=True, staff=True), active, {"a": False, "id": dsm.id})
    db.expire_all()
    assert db.get(User, dsm.id).is_active is False  # type: ignore[union-attr]
    # Ordinary profile edits still work.
    attempt(me(clinic_admin), "UPDATE users SET full_name = 'Dr R' WHERE id = :id", {"id": clinic_admin.id})

    membership_role = "UPDATE clinic_memberships SET role = :r WHERE user_id = :u AND clinic_id = :c"
    with pytest.raises(DBAPIError, match="never on your own membership"):
        attempt(me(clinic_admin), membership_role,
                {"r": "clinic_team_member", "u": clinic_admin.id, "c": clinic.id})  # fmt: skip
    with session_factory() as s:  # nor give yourself a role in another clinic in scope
        me(clinic_admin)(s)
        s.add(ClinicMembership(clinic_id=other_clinic.id, user_id=clinic_admin.id,
                               role=ClinicRole.CLINIC_ADMINISTRATOR))  # fmt: skip
        with pytest.raises(DBAPIError, match="cannot give yourself a clinic role"):
            s.flush()
    # Deactivating ANOTHER member (the team screen) still works.
    teammate = make_user(db, PlatformRole.CLINIC_USER)
    add_member(db, clinic, teammate, ClinicRole.CLINIC_TEAM_MEMBER)
    attempt(me(clinic_admin), "UPDATE clinic_memberships SET is_active = false WHERE user_id = :u",
            {"u": teammate.id})  # fmt: skip


def test_media_labels_change_only_through_migrations(db, session_factory) -> None:  # type: ignore[no-untyped-def]
    with session_factory() as s:
        set_tenant_scope(s, None)
        assert s.query(MediaTaxonomyValue).count() == 16  # readable by everyone signed in
        with pytest.raises(DBAPIError, match="permission denied"):
            s.execute(text("UPDATE media_taxonomy SET label = 'x'"))


def test_clinic_people_cannot_decide_report_reviews_in_the_database(db, session_factory, people) -> None:  # type: ignore[no-untyped-def]
    """Decision D24: report outputs are reviewed by Radial Pulse staff only."""
    clinic, clinic_admin, dsm, _ = people
    report = ReportArtifact(clinic_id=clinic.id, report_type="website_brief", report_key="k", title="T")
    db.add(report)
    db.flush()
    approval = Approval(
        clinic_id=clinic.id,
        resource_type="report_artifact",
        resource_id=report.id,
        state=ApprovalState.SUBMITTED,
    )
    db.add(approval)
    report.approval_state = ApprovalState.SUBMITTED
    db.commit()
    for sql in (
        "UPDATE approvals SET state = 'approved' WHERE id = :id",
        "UPDATE approvals SET publication_state = 'published' WHERE id = :id",
        "UPDATE approvals SET clinic_message = 'ok' WHERE id = :id",
    ):
        with session_factory() as s:
            _as_clinic_user(s, clinic, clinic_admin)
            with pytest.raises(DBAPIError, match="only Radial Pulse staff review"):
                s.execute(text(sql), {"id": approval.id})
    with session_factory() as s:
        _as_dsm(s, clinic, dsm)
        s.execute(text("UPDATE approvals SET state = 'approved' WHERE id = :id"), {"id": approval.id})
        s.execute(
            text("UPDATE report_artifacts SET approval_state = 'approved' WHERE id = :id"), {"id": report.id}
        )
        s.commit()


def test_review_activity_is_invisible_in_the_audit_log_for_clinic_people(db, session_factory, people) -> None:  # type: ignore[no-untyped-def]
    from app.models import AuditEvent

    clinic, clinic_admin, dsm, _ = people
    for action, resource_type in (
        ("approval.approve", "asset"),
        ("assessment.requested", "assessment"),
        ("asset.upload_confirmed", "asset"),
    ):
        db.add(AuditEvent(action=action, resource_type=resource_type, clinic_id=clinic.id, details={}))
    db.commit()
    with session_factory() as s:
        _as_clinic_user(s, clinic, clinic_admin)
        assert {e.action for e in s.query(AuditEvent).all()} == {"asset.upload_confirmed"}
    with session_factory() as s:
        _as_dsm(s, clinic, dsm)
        assert len(s.query(AuditEvent).all()) == 3


def test_clinic_people_cannot_resubmit_media_sent_back_for_a_retake(db, session_factory, people) -> None:  # type: ignore[no-untyped-def]
    """A retake is a new upload: the database refuses moving the old review back to submitted."""
    clinic, clinic_admin, _, _ = people
    asset = _asset(db, clinic)
    approval = _submitted(db, asset)
    approval.state = ApprovalState.REDO_REQUESTED
    asset.approval_state = ApprovalState.REDO_REQUESTED
    db.commit()
    with session_factory() as s:
        _as_clinic_user(s, clinic, clinic_admin)
        with pytest.raises(DBAPIError, match="only Radial Pulse staff review"):
            s.execute(text("UPDATE approvals SET state = 'submitted' WHERE id = :id"), {"id": approval.id})


def test_migration_0013_moves_review_comments_to_private_notes_and_back() -> None:
    """On a scratch database: old comments become staff-only notes, and a downgrade puts them back."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    from tests.conftest import API_ROOT, TEST_DATABASE_URL

    assert TEST_DATABASE_URL is not None
    base = make_url(TEST_DATABASE_URL)
    scratch = f"rp_0013_migration_test_{uuid.uuid4().hex[:8]}"
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

    def q(sql: str) -> list:  # type: ignore[type-arg]
        with engine.connect() as conn:
            return list(conn.execute(text(sql)).all())

    try:
        migrate("0012")
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO organizations (id, name) VALUES ('00000000-0000-0000-0000-0000000000aa', 'O');
                    INSERT INTO clinics (id, organization_id, name, country, is_active, stage,
                                         stage_changed_at)
                      VALUES ('00000000-0000-0000-0000-0000000000cc', '00000000-0000-0000-0000-0000000000aa',
                              'C', 'IN', true, 'prospective_client', now());
                    INSERT INTO report_artifacts (id, clinic_id, report_type, report_key, version, title,
                                                  provenance, approval_state, publication_state)
                      VALUES ('00000000-0000-0000-0000-0000000000dd', '00000000-0000-0000-0000-0000000000cc',
                              't', 'k', 1, 'T', '{}', 'submitted', 'unpublished');
                    INSERT INTO approvals (id, clinic_id, resource_type, resource_id, state,
                                           publication_state,
                                           last_comment)
                      VALUES ('00000000-0000-0000-0000-0000000000ee', '00000000-0000-0000-0000-0000000000cc',
                              'report_artifact', '00000000-0000-0000-0000-0000000000dd', 'submitted',
                              'unpublished', 'old reviewer note');
                    """
                )
            )
        migrate("head")
        assert q("SELECT body FROM approval_notes") == [("old reviewer note",)]
        assert q("SELECT last_comment FROM approvals") == [(None,)]
        assert q("SELECT count(*) FROM media_taxonomy") == [(16,)]
        migrate("0012", down=True)
        assert q("SELECT last_comment FROM approvals") == [("old reviewer note",)]
        migrate("head")
        assert q("SELECT body FROM approval_notes") == [("old reviewer note",)]
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch}"'))
        admin.dispose()
