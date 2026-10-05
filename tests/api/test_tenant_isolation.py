"""Multi-tenant isolation: the most important tests in this repo.

A user must never reach another clinic's data by changing an id in the URL.
Every clinic-scoped endpoint is listed here; add yours when you add a route.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.enums import AssessmentStatus, AssetKind, AssetStatus, DataSource, SnapshotStatus
from app.models import Assessment, Asset, ClinicMembership, MetricSnapshot, ReportArtifact, WorkItem

CLINIC_SCOPED_GETS = [
    "/api/v1/clinics/{cid}",
    "/api/v1/clinics/{cid}/team",
    "/api/v1/clinics/{cid}/practitioners",
    "/api/v1/clinics/{cid}/assignments",
    "/api/v1/clinics/{cid}/profile",
    "/api/v1/clinics/{cid}/assets",
    "/api/v1/clinics/{cid}/approvals",
    "/api/v1/clinics/{cid}/approvals?resource_type=asset",
    "/api/v1/clinics/{cid}/assets?approval_state=submitted",
    "/api/v1/clinics/{cid}/work-items",
    "/api/v1/clinics/{cid}/snapshots",
    "/api/v1/clinics/{cid}/reports",
    "/api/v1/clinics/{cid}/presence-profiles",
    "/api/v1/clinics/{cid}/assessments",
    "/api/v1/clinics/{cid}/chat/messages",
    "/api/v1/clinics/{cid}/connections",
    "/api/v1/clinics/{cid}/connections/instagram",
]


@pytest.mark.parametrize("path", CLINIC_SCOPED_GETS)
def test_clinic_admin_of_b_gets_404_for_every_clinic_a_endpoint(client, world, auth, path) -> None:  # type: ignore[no-untyped-def]
    r = client.get(path.format(cid=world.clinic_a.id), headers=auth(world.clinic_admin_b))
    assert r.status_code == 404, r.text
    assert r.json()["type"] == "not_found"


@pytest.mark.parametrize("path", CLINIC_SCOPED_GETS)
def test_unassigned_digital_success_manager_gets_404(client, world, auth, path) -> None:  # type: ignore[no-untyped-def]
    r = client.get(path.format(cid=world.clinic_a.id), headers=auth(world.unassigned_dsm))
    assert r.status_code == 404


@pytest.mark.parametrize("path", CLINIC_SCOPED_GETS)
def test_clinic_admin_of_a_can_read_own_clinic(client, world, auth, path) -> None:  # type: ignore[no-untyped-def]
    r = client.get(path.format(cid=world.clinic_a.id), headers=auth(world.clinic_admin_a))
    assert r.status_code == 200, (path, r.text)


def test_unknown_clinic_id_is_404_not_500(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"/api/v1/clinics/{uuid.uuid4()}", headers=auth(world.clinic_admin_a))
    assert r.status_code == 404


def test_clinic_list_only_contains_accessible_clinics(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    def names(user):  # type: ignore[no-untyped-def]
        r = client.get("/api/v1/clinics", headers=auth(user))
        assert r.status_code == 200
        return {c["name"] for c in r.json()["items"]}

    assert names(world.clinic_admin_a) == {"Smile Dental A"}
    assert names(world.clinic_admin_b) == {"Bright Clinic B"}
    assert names(world.dsm_a) == {"Smile Dental A"}
    assert names(world.unassigned_dsm) == set()
    assert names(world.admin) == {"Smile Dental A", "Bright Clinic B"}


def test_cross_clinic_lists_only_contain_accessible_clinics(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    """GET /assessments and GET /work-items (no clinic in the path) follow the same scope as GET /clinics."""
    a, b = world.clinic_a.id, world.clinic_b.id
    published = Assessment(
        clinic_id=a, sequence=1, status=AssessmentStatus.COMPLETED, methodology_version="t"
    )
    db.add_all(
        [
            published,
            Assessment(clinic_id=a, sequence=2, status=AssessmentStatus.COMPLETED, methodology_version="t"),
            Assessment(clinic_id=b, sequence=1, status=AssessmentStatus.COMPLETED, methodology_version="t"),
            WorkItem(clinic_id=a, kind="k", title="A task"),
            WorkItem(clinic_id=b, kind="k", title="B task"),
        ]
    )
    db.commit()
    # Publish A's first assessment the proper way (submit → approve → publish by the DSM).
    for action in ("submit", "approve", "publish"):
        r = client.post(
            f"/api/v1/clinics/{a}/approvals/actions",
            headers=auth(world.dsm_a),
            json={"resource_type": "assessment", "resource_id": str(published.id), "action": action},
        )
        assert r.status_code == 200, r.text

    def clinics(user, path, **params):  # type: ignore[no-untyped-def]
        r = client.get(path, headers=auth(user), params=params)
        assert r.status_code == 200, r.text
        return sorted(row["clinic_name"] for row in r.json()["items"])

    assessments, work = "/api/v1/assessments", "/api/v1/work-items"
    assert clinics(world.admin, assessments) == ["Bright Clinic B", "Smile Dental A", "Smile Dental A"]
    assert clinics(world.dsm_a, assessments) == ["Smile Dental A", "Smile Dental A"]
    assert clinics(world.clinic_admin_a, assessments) == ["Smile Dental A"]  # PUBLISHED only
    assert clinics(world.clinic_admin_b, assessments) == []  # B's assessment is not published
    assert clinics(world.unassigned_dsm, assessments) == []
    assert clinics(world.admin, work) == ["Bright Clinic B", "Smile Dental A"]
    assert clinics(world.dsm_a, work) == ["Smile Dental A"]
    assert clinics(world.team_member_a, work) == ["Smile Dental A"]
    assert clinics(world.clinic_admin_b, work) == ["Bright Clinic B"]
    assert clinics(world.unassigned_dsm, work) == []
    # Asking for a clinic you cannot see matches nothing (and reveals nothing).
    assert clinics(world.dsm_a, assessments, clinic_id=str(b)) == []
    assert clinics(world.dsm_a, work, clinic_id=str(b)) == []
    assert clinics(world.admin, assessments, publication_state="published") == ["Smile Dental A"]
    row = client.get(assessments, headers=auth(world.clinic_admin_a)).json()["items"][0]
    assert row["clinic_id"] == str(a) and row["primary_practitioner_name"] == "Dr. A"


def test_practitioner_of_b_cannot_be_reached_through_clinic_a_path(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    """Admin of A has practitioners:write in A. Using A's path with B's practitioner id must not touch B."""
    r = client.patch(
        f"/api/v1/clinics/{world.clinic_a.id}/practitioners/{world.practitioner_b.id}",
        headers=auth(world.clinic_admin_a),
        json={"full_name": "Hijacked"},
    )
    assert r.status_code == 404


def test_writes_into_other_clinic_are_blocked(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_b.id
    h = auth(world.clinic_admin_a)
    assert (
        client.post(f"/api/v1/clinics/{cid}/practitioners", headers=h, json={"full_name": "X"}).status_code
        == 404
    )
    assert client.patch(f"/api/v1/clinics/{cid}", headers=h, json={"name": "X"}).status_code == 404
    assert (
        client.post(
            f"/api/v1/clinics/{cid}/assets/uploads",
            headers=h,
            json={"kind": "clinic_photo", "mime_type": "image/png", "size_bytes": 10},
        ).status_code
        == 404
    )


def test_ids_from_other_clinic_are_404_for_nested_resources(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    b = world.clinic_b.id
    asset = Asset(
        clinic_id=b, kind=AssetKind.LOGO, mime_type="image/png", size_bytes=1,
        storage_key=f"clinics/{b}/logo/x.png", status=AssetStatus.UPLOADED,
    )  # fmt: skip
    report = ReportArtifact(clinic_id=b, report_type="seo_audit", report_key="k", title="B report")
    item = WorkItem(clinic_id=b, kind="k", title="B task")
    db.add_all([asset, report, item])
    db.commit()

    a = world.clinic_a.id
    h = auth(world.dsm_a)  # full access to A
    assert client.get(f"/api/v1/clinics/{a}/assets/{asset.id}/download-url", headers=h).status_code == 404
    assert client.get(f"/api/v1/clinics/{a}/assets/{asset.id}", headers=h).status_code == 404
    assert client.post(f"/api/v1/clinics/{a}/assets/{asset.id}/confirm", headers=h).status_code == 404
    assert client.get(f"/api/v1/clinics/{a}/reports/{report.id}", headers=h).status_code == 404
    assert client.get(f"/api/v1/clinics/{a}/work-items/{item.id}", headers=h).status_code == 404
    r = client.post(
        f"/api/v1/clinics/{a}/approvals/actions",
        headers=h,
        json={"resource_type": "report_artifact", "resource_id": str(report.id), "action": "submit"},
    )
    assert r.status_code == 404


def test_snapshots_are_tenant_scoped(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    from app.db.base import utcnow

    db.add(
        MetricSnapshot(
            clinic_id=world.clinic_b.id, source=DataSource.MANUAL, metric_key="gbp.review_count",
            value={"value": 9}, fetched_at=utcnow(), status=SnapshotStatus.OK,
        )
    )  # fmt: skip
    db.commit()
    r = client.get(f"/api/v1/clinics/{world.clinic_a.id}/snapshots", headers=auth(world.dsm_a))
    assert r.status_code == 200
    assert r.json()["total"] == 0


@pytest.mark.parametrize("path", CLINIC_SCOPED_GETS)
def test_clinic_team_member_can_view_own_clinic(client, world, auth, path) -> None:  # type: ignore[no-untyped-def]
    r = client.get(path.format(cid=world.clinic_a.id), headers=auth(world.team_member_a))
    assert r.status_code == 200, (path, r.text)


@pytest.mark.parametrize("path", CLINIC_SCOPED_GETS)
def test_clinic_team_member_cannot_see_other_clinics(client, world, auth, path) -> None:  # type: ignore[no-untyped-def]
    r = client.get(path.format(cid=world.clinic_b.id), headers=auth(world.team_member_a))
    assert r.status_code == 404


def test_clinic_team_member_is_view_only(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    """Staff can look and upload files, but not edit, add people, approve, or read the activity log.

    Clinic media (photos for review, voice samples) is the Clinic Administrator's in V1."""
    h = auth(world.team_member_a)
    a = f"/api/v1/clinics/{world.clinic_a.id}"
    assert client.patch(a, headers=h, json={"phone": "1"}).status_code == 403
    assert client.post(f"{a}/team", headers=h, json={"email": "x@example.test"}).status_code == 403
    assert client.post(f"{a}/practitioners", headers=h, json={"full_name": "Dr. X"}).status_code == 403
    assert client.post(f"{a}/work-items", headers=h, json={"kind": "k", "title": "t"}).status_code == 403
    assert client.get(f"{a}/audit-events", headers=h).status_code == 403
    assert client.post(f"{a}/stage", headers=h, json={"stage": "client_discussion"}).status_code == 403
    r = client.post(
        f"{a}/assets/uploads",
        headers=h,
        json={"kind": "clinic_photo", "mime_type": "image/png", "size_bytes": 10, "category": "team_at_work"},
    )
    assert r.status_code == 403, r.text
    document = {"kind": "document", "mime_type": "application/pdf", "size_bytes": 10}
    r = client.post(f"{a}/assets/uploads", headers=h, json=document)
    assert r.status_code == 201, r.text


def test_permission_denied_inside_own_clinic_is_403(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    """A Clinic Administrator can see clinic A but cannot do Radial Pulse staff work in it."""
    h = auth(world.clinic_admin_a)
    a = world.clinic_a.id
    assert client.post(f"/api/v1/clinics/{a}/assessments", headers=h, json={}).status_code == 403
    # Moving stages is staff work. (Adding other Clinic Administrators IS allowed: decision D14.)
    assert (
        client.post(f"/api/v1/clinics/{a}/stage", headers=h, json={"stage": "client_discussion"}).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/clinics/{a}/work-items", headers=h, json={"kind": "k", "title": "t"}
        ).status_code
        == 403
    )


def test_milestone1_clinic_routes_are_tenant_scoped(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    """Stage, archive, team and practitioner routes of clinic A are invisible to clinic B's people."""
    a = world.clinic_a.id
    membership = db.query(ClinicMembership).filter_by(user_id=world.clinic_admin_a.id).one()
    h = auth(world.clinic_admin_b)
    calls = [
        ("post", f"/api/v1/clinics/{a}/stage", {"stage": "profile_enriched"}),
        ("get", f"/api/v1/clinics/{a}/stage-history", None),
        ("post", f"/api/v1/clinics/{a}/archive", {"reason": "sneaky"}),
        ("post", f"/api/v1/clinics/{a}/restore", None),
        ("post", f"/api/v1/clinics/{a}/team", {"email": "x@example.test"}),
        ("patch", f"/api/v1/clinics/{a}/team/{membership.id}", {"is_active": False}),
        ("post", f"/api/v1/clinics/{a}/team/{membership.id}/resend-invite", None),
        ("patch", f"/api/v1/clinics/{a}/practitioners/{world.practitioner_a.id}", {"full_name": "X"}),
    ]
    for method, path, body in calls:
        r = client.request(method.upper(), path, headers=h, json=body)
        assert r.status_code == 404, (method, path, r.status_code)


def test_team_member_ids_from_other_clinic_are_404(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    b_membership = db.query(ClinicMembership).filter_by(user_id=world.clinic_admin_b.id).one()
    r = client.patch(
        f"/api/v1/clinics/{world.clinic_a.id}/team/{b_membership.id}",
        headers=auth(world.dsm_a),
        json={"is_active": False},
    )
    assert r.status_code == 404


def test_assignment_routes_are_platform_administrator_only(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    path = f"/api/v1/clinics/{world.clinic_a.id}/assignment"
    body = {"user_id": str(world.unassigned_dsm.id)}
    for user in (world.dsm_a, world.clinic_admin_a, world.clinic_admin_b):
        assert client.put(path, headers=auth(user), json=body).status_code == 403
        assert client.delete(path, headers=auth(user)).status_code == 403
