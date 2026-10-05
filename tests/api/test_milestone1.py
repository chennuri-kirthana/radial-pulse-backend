"""Milestone 1 behaviour: stages, archiving, list screens, practitioners, users & invites,
dashboard, "Fix Now" work items and clinic team rules. See docs/architecture/database-schema.md.
"""

from __future__ import annotations

from app.core.enums import (
    AssessmentComponentKey,
    AssessmentStatus,
    ClinicRole,
    ComponentStatus,
    FindingPriority,
    PlatformRole,
    WorkArea,
    WorkItemStatus,
)
from app.models import (
    Assessment,
    AssessmentComponent,
    AssessmentFinding,
    AuditEvent,
    ClinicMembership,
    ClinicPractitioner,
    Practitioner,
    User,
    WorkItem,
)
from tests.factories import add_member, make_clinic, make_user


def _clinic(world) -> str:  # type: ignore[no-untyped-def]
    return f"/api/v1/clinics/{world.clinic_a.id}"


# --------------------------------------------------------------------------- stages
def test_dsm_moves_clinic_through_stages_and_history_is_kept(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    path = _clinic(world)
    dsm = auth(world.dsm_a)
    r = client.post(f"{path}/stage", headers=dsm, json={"stage": "profile_enriched", "note": "GBP found"})
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "profile_enriched"
    assert client.post(f"{path}/stage", headers=dsm, json={"stage": "profile_enriched"}).status_code == 409
    # Stages can be skipped by hand (Milestone 1: all moves are manual).
    assert client.post(f"{path}/stage", headers=dsm, json={"stage": "client_discussion"}).status_code == 200
    history = client.get(f"{path}/stage-history", headers=dsm).json()
    assert [(h["from_stage"], h["to_stage"]) for h in history] == [
        ("prospective_client", "profile_enriched"),
        ("profile_enriched", "client_discussion"),
    ]
    assert history[0]["note"] == "GBP found"
    assert db.query(AuditEvent).filter_by(action="clinic.stage_change").count() == 2


def test_only_staff_move_stages(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    path = _clinic(world)
    body = {"stage": "active_client"}
    assert client.post(f"{path}/stage", headers=auth(world.clinic_admin_a), json=body).status_code == 403
    assert client.get(f"{path}/stage-history", headers=auth(world.clinic_admin_a)).status_code == 403
    assert client.post(f"{path}/stage", headers=auth(world.unassigned_dsm), json=body).status_code == 404
    assert client.post(f"{path}/stage", headers=auth(world.dsm_a), json={"stage": "lost"}).status_code == 422


def test_customer_needs_a_clinic_administrator_first(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/clinics", headers=auth(world.dsm_a), json={"name": "No Login Yet"})
    cid = r.json()["id"]
    to_customer = {"stage": "active_client"}
    r = client.post(f"/api/v1/clinics/{cid}/stage", headers=auth(world.dsm_a), json=to_customer)
    assert r.status_code == 409
    assert "Clinic Administrator" in r.json()["detail"]
    client.post(f"/api/v1/clinics/{cid}/team", headers=auth(world.dsm_a), json={"email": "dr@example.test"})
    r = client.post(f"/api/v1/clinics/{cid}/stage", headers=auth(world.dsm_a), json=to_customer)
    assert r.status_code == 200


# ------------------------------------------------------------------------- archive
def test_archive_needs_a_reason_hides_the_clinic_and_can_be_undone(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    path = _clinic(world)
    dsm = auth(world.dsm_a)
    assert client.post(f"{path}/archive", headers=dsm, json={}).status_code == 422
    assert client.post(f"{path}/archive", headers=dsm, json={"reason": ""}).status_code == 422
    r = client.post(f"{path}/archive", headers=dsm, json={"reason": "Not interested, has an agency"})
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    assert r.json()["archived_reason"] == "Not interested, has an agency"
    assert r.json()["stage"] == "prospective_client"  # stage is kept
    assert client.post(f"{path}/archive", headers=dsm, json={"reason": "again"}).status_code == 409
    assert client.post(f"{path}/stage", headers=dsm, json={"stage": "profile_enriched"}).status_code == 409

    live = client.get("/api/v1/clinics", headers=dsm).json()
    assert live["total"] == 0
    archived = client.get("/api/v1/clinics", headers=dsm, params={"archived": True}).json()
    assert [c["name"] for c in archived["items"]] == [world.clinic_a.name]

    r = client.post(f"{path}/restore", headers=dsm)
    assert r.status_code == 200
    assert r.json()["is_active"] is True and r.json()["archived_reason"] is None
    assert client.post(f"{path}/restore", headers=dsm).status_code == 409
    actions = [e.action for e in db.query(AuditEvent).filter(AuditEvent.action.like("clinic.%"))]
    assert "clinic.archive" in actions and "clinic.restore" in actions


# ---------------------------------------------------------------------- list screen
def test_clinic_list_rows_have_doctor_dsm_and_work_chips(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    db.add_all(
        [
            WorkItem(clinic_id=world.clinic_a.id, kind="k", title="SEO 1", area=WorkArea.SEARCH_READINESS),
            WorkItem(clinic_id=world.clinic_a.id, kind="k", title="SEO 2", area=WorkArea.SEARCH_READINESS),
            WorkItem(
                clinic_id=world.clinic_a.id, kind="k", title="GBP", area=WorkArea.GOOGLE_BUSINESS_PROFILE
            ),
            WorkItem(
                clinic_id=world.clinic_a.id,
                kind="k",
                title="Done",
                area=WorkArea.WEBSITE,
                status=WorkItemStatus.DONE,
            ),
        ]
    )
    db.commit()
    rows = client.get("/api/v1/clinics", headers=auth(world.admin)).json()["items"]
    a = next(r for r in rows if r["id"] == str(world.clinic_a.id))
    b = next(r for r in rows if r["id"] == str(world.clinic_b.id))
    assert a["primary_practitioner_name"] == "Dr. A"
    assert a["dsm"]["id"] == str(world.dsm_a.id)
    assert {c["area"]: c["open_count"] for c in a["open_work"]} == {
        "search_readiness": 2,
        "google_business_profile": 1,
    }
    assert b["dsm"] is None and b["open_work"] == []


def test_clinic_list_filters(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.admin)

    def names(**params):  # type: ignore[no-untyped-def]
        return {c["name"] for c in client.get("/api/v1/clinics", headers=h, params=params).json()["items"]}

    both = {world.clinic_a.name, world.clinic_b.name}
    assert names() == both
    assert names(stage=["prospective_client", "profile_enriched"]) == both  # the "Prospects" tab
    assert names(group="prospects") == both  # the same tab, without repeating the mapping
    assert names(group="in_progress") == set() and names(group="active") == set()
    assert names(group="prospects", stage="active_client") == set()  # both given: their overlap
    assert names(stage="active_client") == set()
    rows = client.get("/api/v1/clinics", headers=h).json()["items"]
    assert {r["stage_group"] for r in rows} == {"prospects"}
    assert names(dsm_user_id=str(world.dsm_a.id)) == {world.clinic_a.name}
    assert names(unassigned=True) == {world.clinic_b.name}
    assert names(q="dr. b") == {world.clinic_b.name}  # practitioner name
    assert names(q="SMILE") == {world.clinic_a.name}  # clinic name, any case


# -------------------------------------------------------------------- practitioners
def test_only_one_main_practitioner(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    path = f"{_clinic(world)}/practitioners"
    h = auth(world.clinic_admin_a)
    r = client.post(path, headers=h, json={"full_name": "Dr. New", "bio": "Implants", "is_primary": True})
    assert r.status_code == 201, r.text
    listed = client.get(path, headers=h).json()["items"]
    assert [(p["full_name"], p["is_primary"]) for p in listed] == [("Dr. New", True), ("Dr. A", False)]
    r = client.patch(f"{path}/{world.practitioner_a.id}", headers=h, json={"is_primary": True})
    assert r.status_code == 200
    db.expire_all()
    primaries = (
        db.query(Practitioner)
        .join(ClinicPractitioner, ClinicPractitioner.practitioner_id == Practitioner.id)
        .filter(ClinicPractitioner.clinic_id == world.clinic_a.id, ClinicPractitioner.is_primary.is_(True))
        .all()
    )
    assert [p.full_name for p in primaries] == ["Dr. A"]


def test_new_clinic_can_name_its_main_practitioner(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        "/api/v1/clinics",
        headers=auth(world.admin),
        json={
            "name": "Care Plus",
            "primary_practitioner_name": "Dr. Suresh Reddy",
            "specialty": "Dental",
            "latitude": 16.9891,
            "longitude": 82.2475,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["latitude"] == 16.9891
    rows = client.get("/api/v1/clinics", headers=auth(world.admin), params={"q": "care plus"}).json()["items"]
    assert rows[0]["primary_practitioner_name"] == "Dr. Suresh Reddy"
    bad = client.post("/api/v1/clinics", headers=auth(world.admin), json={"name": "X", "latitude": 10.0})
    assert bad.status_code == 422  # latitude without longitude


# -------------------------------------------------------------------- users & invites
def test_users_screen_shows_status_and_clinic_count(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    invited = make_user(db, PlatformRole.DIGITAL_SUCCESS_MANAGER, linked=False)
    rows = client.get(
        "/api/v1/users", headers=auth(world.admin), params={"platform_role": "digital_success_manager"}
    ).json()["items"]
    by_id = {r["id"]: r for r in rows}
    assert by_id[str(world.dsm_a.id)]["status"] == "active"
    assert by_id[str(world.dsm_a.id)]["assigned_clinic_count"] == 1
    assert by_id[str(world.unassigned_dsm.id)]["assigned_clinic_count"] == 0
    assert by_id[str(invited.id)]["status"] == "invited"


def test_creating_a_user_sends_an_invite_and_can_resend(client, db, world, auth, invites) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        "/api/v1/users",
        headers=auth(world.admin),
        json={
            "email": "priya@radialpulse.test",
            "full_name": "Priya",
            "platform_role": "digital_success_manager",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "invited"
    assert [i.role_label for i in invites.sent] == ["Digital Success Manager"]
    uid = r.json()["id"]
    assert client.post(f"/api/v1/users/{uid}/resend-invite", headers=auth(world.admin)).status_code == 204
    assert len(invites.sent) == 2
    assert db.get(User, world.dsm_a.id).cognito_sub is not None
    signed_in = f"/api/v1/users/{world.dsm_a.id}/resend-invite"
    assert client.post(signed_in, headers=auth(world.admin)).status_code == 409
    assert client.post(f"/api/v1/users/{uid}/resend-invite", headers=auth(world.dsm_a)).status_code == 403


def test_a_failed_invite_email_does_not_undo_the_user(client, db, world, auth, invites) -> None:  # type: ignore[no-untyped-def]
    invites.fail = True
    r = client.post(
        "/api/v1/users",
        headers=auth(world.admin),
        json={"email": "down@radialpulse.test", "platform_role": "digital_success_manager"},
    )
    assert r.status_code == 201
    user = db.query(User).filter_by(email="down@radialpulse.test").one()
    assert user.last_invited_at is None
    assert db.query(AuditEvent).filter_by(action="invite.failed").count() == 1


def test_admin_edits_and_deactivates_users_but_not_themselves(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    path = f"/api/v1/users/{world.dsm_a.id}"
    r = client.patch(path, headers=auth(world.admin), json={"phone": "+91 98765 43210"})
    assert r.status_code == 200 and r.json()["phone"] == "+91 98765 43210"
    r = client.patch(path, headers=auth(world.admin), json={"is_active": False})
    assert r.json()["status"] == "deactivated"
    assert client.get("/api/v1/auth/me", headers=auth(world.dsm_a)).status_code == 403  # cannot sign in
    me = f"/api/v1/users/{world.admin.id}"
    assert client.patch(me, headers=auth(world.admin), json={"is_active": False}).status_code == 409
    assert client.patch(path, headers=auth(world.unassigned_dsm), json={"phone": "1"}).status_code == 403


def test_everyone_can_update_their_own_profile(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(
        "/api/v1/auth/me",
        headers=auth(world.clinic_admin_a),
        json={"full_name": "Dr. Rahul", "phone": "+91 1"},
    )
    assert r.status_code == 200
    assert r.json()["full_name"] == "Dr. Rahul" and r.json()["phone"] == "+91 1"
    bad = client.patch("/api/v1/auth/me", headers=auth(world.clinic_admin_a), json={"platform_role": "x"})
    assert bad.status_code == 422


# ------------------------------------------------------------------------- dashboard
def test_dashboard_counts_only_what_the_caller_can_see(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    client.post(f"{_clinic(world)}/stage", headers=auth(world.dsm_a), json={"stage": "client_discussion"})
    admin = client.get("/api/v1/dashboard/summary", headers=auth(world.admin)).json()
    assert admin["total_clinics"] == 2
    assert (admin["prospects"], admin["in_progress"], admin["active"]) == (1, 1, 0)
    assert len(admin["new_clinics_by_month"]) == 6
    assert admin["new_clinics_by_month"][-1]["count"] == 2
    dsm = client.get("/api/v1/dashboard/summary", headers=auth(world.dsm_a)).json()
    assert dsm["total_clinics"] == 1 and dsm["in_progress"] == 1
    empty = client.get("/api/v1/dashboard/summary", headers=auth(world.unassigned_dsm)).json()
    assert empty["total_clinics"] == 0
    assert client.get("/api/v1/dashboard/summary", headers=auth(world.clinic_admin_a)).status_code == 403


# ---------------------------------------------------------------- "Fix Now" work items
def _finding(db, clinic, code="gbp.description_missing_keywords"):  # type: ignore[no-untyped-def]
    assessment = Assessment(
        clinic_id=clinic.id, sequence=1, status=AssessmentStatus.COMPLETED, methodology_version="t"
    )
    db.add(assessment)
    db.flush()
    component = AssessmentComponent(
        assessment_id=assessment.id,
        clinic_id=clinic.id,
        key=AssessmentComponentKey.GOOGLE_BUSINESS_PROFILE,
        status=ComponentStatus.COMPLETED,
    )
    db.add(component)
    db.flush()
    finding = AssessmentFinding(
        assessment_id=assessment.id, component_id=component.id, clinic_id=clinic.id, code=code,
        title="GBP description needs improvement", priority=FindingPriority.HIGH,
        recommendation="Add services and area keywords", evidence={"items": []},
    )  # fmt: skip
    db.add(finding)
    db.commit()
    return finding


def test_fix_now_creates_one_open_work_item_per_problem(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    finding = _finding(db, world.clinic_a)
    path = f"{_clinic(world)}/work-items"
    h = auth(world.dsm_a)
    r = client.post(path, headers=h, json={"source_finding_id": str(finding.id)})
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["title"] == "GBP description needs improvement"
    assert item["area"] == "google_business_profile"
    assert item["finding_code"] == "gbp.description_missing_keywords"
    assert item["description"] == "Add services and area keywords"
    # Same problem again (e.g. found again by a re-assessment) -> the existing item, not a duplicate.
    assert client.post(path, headers=h, json={"source_finding_id": str(finding.id)}).status_code == 409
    done = client.patch(f"{path}/{item['id']}", headers=h, json={"status": "done"}).json()
    assert done["completed_at"] is not None
    assert client.post(path, headers=h, json={"source_finding_id": str(finding.id)}).status_code == 201
    chips = client.get(path, headers=h, params={"area": "google_business_profile"}).json()
    assert chips["total"] == 2
    # A finding of another clinic cannot be used.
    other = _finding(db, world.clinic_b, code="gbp.other")
    assert client.post(path, headers=h, json={"source_finding_id": str(other.id)}).status_code == 404
    assert client.post(path, headers=h, json={"kind": "x"}).status_code == 422  # no title, no finding


def test_reopening_clears_completed_at(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    path = f"{_clinic(world)}/work-items"
    h = auth(world.dsm_a)
    item = client.post(path, headers=h, json={"title": "Upload photos", "area": "clinic_profile"}).json()
    assert item["area"] == "clinic_profile" and item["kind"] == "improvement"
    client.patch(f"{path}/{item['id']}", headers=h, json={"status": "done"})
    reopened = client.patch(f"{path}/{item['id']}", headers=h, json={"status": "in_progress"}).json()
    assert reopened["completed_at"] is None


# ------------------------------------------------------------------------ clinic team
def test_customer_clinic_keeps_its_last_clinic_administrator(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    path = _clinic(world)
    client.post(f"{path}/stage", headers=auth(world.dsm_a), json={"stage": "active_client"})
    team = client.get(f"{path}/team", headers=auth(world.dsm_a)).json()
    admin_row = next(m for m in team if m["user_id"] == str(world.clinic_admin_a.id))
    r = client.patch(f"{path}/team/{admin_row['id']}", headers=auth(world.dsm_a), json={"is_active": False})
    assert r.status_code == 409
    # With a second Clinic Administrator the first one can be removed.
    client.post(f"{path}/team", headers=auth(world.clinic_admin_a), json={"email": "partner@example.test"})
    r = client.patch(f"{path}/team/{admin_row['id']}", headers=auth(world.dsm_a), json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    # Reactivating works, and re-adding the same person asks to reactivate instead.
    r = client.post(f"{path}/team", headers=auth(world.dsm_a), json={"email": world.clinic_admin_a.email})
    assert r.status_code == 409 and "Reactivate" in r.json()["detail"]


def test_resend_team_invite_only_before_first_sign_in(client, db, world, auth, invites) -> None:  # type: ignore[no-untyped-def]
    path = _clinic(world)
    new = client.post(f"{path}/team", headers=auth(world.dsm_a), json={"email": "late@example.test"}).json()
    assert client.post(f"{path}/team/{new['id']}/resend-invite", headers=auth(world.dsm_a)).status_code == 204
    assert len(invites.sent) == 2
    signed_in = db.query(ClinicMembership).filter_by(user_id=world.clinic_admin_a.id).one()
    r = client.post(f"{path}/team/{signed_in.id}/resend-invite", headers=auth(world.dsm_a))
    assert r.status_code == 409


def test_clinic_admin_of_two_branches_sees_both(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    branch = make_clinic(db, "Smile Dental A - Branch 2", organization=world.clinic_a.organization)
    add_member(db, branch, world.clinic_admin_a, ClinicRole.CLINIC_ADMINISTRATOR)
    names = {
        c["name"] for c in client.get("/api/v1/clinics", headers=auth(world.clinic_admin_a)).json()["items"]
    }
    assert names == {world.clinic_a.name, branch.name}


def test_removing_a_disabled_login_is_not_blocked_by_last_admin_rule(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    """A Customer clinic with one working admin + one admin whose login is disabled:
    removing the disabled one is fine (it does not reduce the real number of admins)."""
    path = _clinic(world)
    client.post(f"{path}/stage", headers=auth(world.dsm_a), json={"stage": "active_client"})
    disabled = make_user(db, PlatformRole.CLINIC_USER)
    add_member(db, world.clinic_a, disabled, ClinicRole.CLINIC_ADMINISTRATOR)
    disabled.is_active = False
    db.commit()
    team = client.get(f"{path}/team", headers=auth(world.dsm_a)).json()
    row = next(m for m in team if m["user_id"] == str(disabled.id))
    r = client.patch(f"{path}/team/{row['id']}", headers=auth(world.dsm_a), json={"is_active": False})
    assert r.status_code == 200, r.text


def test_edit_requests_cannot_null_required_fields(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    """Leaving a field out is fine; sending null for a required one is a clear 422, not a 500."""
    h = auth(world.dsm_a)
    path = _clinic(world)
    assert client.patch(path, headers=h, json={"name": None}).status_code == 422
    assert client.patch(path, headers=h, json={"phone": None}).status_code == 200  # optional: clears it
    item = client.post(f"{path}/work-items", headers=h, json={"kind": "k", "title": "t"}).json()
    r = client.patch(f"{path}/work-items/{item['id']}", headers=h, json={"status": None})
    assert r.status_code == 422
    r = client.patch(f"/api/v1/users/{world.dsm_a.id}", headers=auth(world.admin), json={"is_active": None})
    assert r.status_code == 422


# ------------------------------------------------- one doctor, several branches (0008)
def test_same_doctor_can_work_at_two_branches(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.dsm_a)
    r = client.post(
        "/api/v1/clinics",
        headers=h,
        json={"name": "Smile Dental A — Branch 2", "organization_id": str(world.clinic_a.organization_id)},
    )
    assert r.status_code == 201, r.text
    branch = f"/api/v1/clinics/{r.json()['id']}"
    # Link the doctor who already works at clinic A (same business).
    r = client.post(
        f"{branch}/practitioners", headers=h, json={"practitioner_id": str(world.practitioner_a.id)}
    )
    assert r.status_code == 201, r.text
    assert r.json()["id"] == str(world.practitioner_a.id) and r.json()["is_primary"] is False
    assert (
        client.post(
            f"{branch}/practitioners", headers=h, json={"practitioner_id": str(world.practitioner_a.id)}
        ).status_code
        == 409
    )  # already linked
    # Editing the PERSON shows everywhere; the active flag is per clinic.
    r = client.patch(
        f"{branch}/practitioners/{world.practitioner_a.id}", headers=h, json={"full_name": "Dr. A Kumar"}
    )
    assert r.status_code == 200
    r = client.patch(
        f"{branch}/practitioners/{world.practitioner_a.id}", headers=h, json={"is_active": False}
    )
    assert r.json()["is_active"] is False
    at_a = client.get(f"{_clinic(world)}/practitioners", headers=h).json()["items"]
    assert [(p["full_name"], p["is_active"]) for p in at_a] == [("Dr. A Kumar", True)]


def test_cannot_link_a_doctor_of_another_business(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        f"{_clinic(world)}/practitioners",
        headers=auth(world.admin),
        json={"practitioner_id": str(world.practitioner_b.id)},
    )
    assert r.status_code == 404
    both = {"practitioner_id": str(world.practitioner_a.id), "full_name": "X"}
    assert (
        client.post(f"{_clinic(world)}/practitioners", headers=auth(world.admin), json=both).status_code
        == 422
    )
    assert (
        client.post(f"{_clinic(world)}/practitioners", headers=auth(world.admin), json={}).status_code == 422
    )


def test_clinic_admin_can_add_someone_who_already_has_an_account_elsewhere(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    """The account belongs to clinic B (invisible to A's people): found by email, then added."""
    r = client.post(
        f"{_clinic(world)}/team",
        headers=auth(world.clinic_admin_a),
        json={"email": world.clinic_admin_b.email, "role": "clinic_team_member"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["email"] == world.clinic_admin_b.email
