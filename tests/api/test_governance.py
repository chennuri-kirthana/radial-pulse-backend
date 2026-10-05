from __future__ import annotations

from app.core.enums import AssessmentStatus
from app.models import Assessment, AuditEvent, Notification


def _report(client, world, auth) -> str:  # type: ignore[no-untyped-def]
    r = client.post(
        f"/api/v1/clinics/{world.clinic_a.id}/reports",
        headers=auth(world.dsm_a),
        json={
            "report_type": "website_brief",
            "report_key": "website_brief:2026-09",
            "title": "September website brief",
            "provenance": {"producer": "website-team/brief-agent@0.1"},
        },
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def _act(client, world, user, auth, report_id, action, **extra):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/v1/clinics/{world.clinic_a.id}/approvals/actions",
        headers=auth(user),
        json={"resource_type": "report_artifact", "resource_id": report_id, "action": action, **extra},
    )


def test_report_review_and_publish_flow(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    report_id = _report(client, world, auth)
    reports_path = f"/api/v1/clinics/{world.clinic_a.id}/reports"

    # Clinic Administrators never see unpublished outputs.
    assert client.get(reports_path, headers=auth(world.clinic_admin_a)).json()["total"] == 0
    assert client.get(f"{reports_path}/{report_id}", headers=auth(world.clinic_admin_a)).status_code == 404

    assert _act(client, world, world.dsm_a, auth, report_id, "approve").status_code == 409  # not submitted
    assert _act(client, world, world.clinic_admin_a, auth, report_id, "submit").status_code == 403
    r = _act(client, world, world.dsm_a, auth, report_id, "submit")
    assert r.status_code == 200 and r.json()["state"] == "submitted"
    assert _act(client, world, world.dsm_a, auth, report_id, "publish").status_code == 409  # not approved
    # Every review decision is Radial Pulse staff work (decision D24): the clinic never approves.
    for action in ("approve", "reject", "redo"):
        assert _act(client, world, world.clinic_admin_a, auth, report_id, action).status_code == 403
    assert _act(client, world, world.dsm_a, auth, report_id, "approve").json()["state"] == "approved"
    assert _act(client, world, world.clinic_admin_a, auth, report_id, "publish").status_code == 403
    r = _act(client, world, world.dsm_a, auth, report_id, "publish")
    assert r.json()["publication_state"] == "published"

    report = client.get(f"{reports_path}/{report_id}", headers=auth(world.clinic_admin_a))
    assert report.status_code == 200
    assert report.json()["published_at"] is not None
    actions = {e.action for e in db.query(AuditEvent).filter(AuditEvent.action.like("approval.%"))}
    assert actions == {"approval.submit", "approval.approve", "approval.publish"}


def test_redo_retracts_published_report(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    report_id = _report(client, world, auth)
    for user, action in [
        (world.dsm_a, "submit"),
        (world.dsm_a, "approve"),
        (world.dsm_a, "publish"),
    ]:
        assert _act(client, world, user, auth, report_id, action).status_code == 200
    r = _act(client, world, world.dsm_a, auth, report_id, "redo", comment="Fix the GBP section")
    assert r.json()["state"] == "redo_requested"
    assert r.json()["publication_state"] == "retracted"
    assert r.json()["last_comment"] == "Fix the GBP section"
    listed = client.get(
        f"/api/v1/clinics/{world.clinic_a.id}/reports", headers=auth(world.clinic_admin_a)
    ).json()
    assert listed["total"] == 0


def test_handoff_notifies_assignee_with_access_only(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    report_id = _report(client, world, auth)
    assert _act(client, world, world.dsm_a, auth, report_id, "submit").status_code == 200
    r = _act(
        client, world, world.dsm_a, auth, report_id, "handoff", assignee_user_id=str(world.clinic_admin_b.id)
    )
    assert r.status_code == 422  # Clinic Administrator of B has no access to A
    r = _act(
        client, world, world.dsm_a, auth, report_id, "handoff", assignee_user_id=str(world.clinic_admin_a.id)
    )
    assert r.status_code == 200
    assert db.query(Notification).filter_by(user_id=world.clinic_admin_a.id).count() == 1
    notes = client.get("/api/v1/notifications", headers=auth(world.clinic_admin_a)).json()
    assert notes["total"] == 1
    note_id = notes["items"][0]["id"]
    assert client.post(f"/api/v1/notifications/{note_id}/read", headers=auth(world.dsm_a)).status_code == 404
    assert (
        client.post(f"/api/v1/notifications/{note_id}/read", headers=auth(world.clinic_admin_a)).status_code
        == 200
    )


def test_available_actions_follow_state_and_permissions(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    """The API says which buttons to show; screens never repeat the state machine."""
    report_id = _report(client, world, auth)
    approvals = f"/api/v1/clinics/{world.clinic_a.id}/approvals"

    def listed(user):  # type: ignore[no-untyped-def]
        rows = client.get(approvals, headers=auth(user)).json()["items"]
        return {row["resource_type"]: sorted(row["available_actions"]) for row in rows}

    r = _act(client, world, world.dsm_a, auth, report_id, "submit")
    assert sorted(r.json()["available_actions"]) == ["approve", "handoff", "redo", "reject"]
    assert listed(world.clinic_admin_a)["report_artifact"] == []  # staff decide (D24)
    assert listed(world.team_member_a)["report_artifact"] == []  # view only
    r = _act(client, world, world.dsm_a, auth, report_id, "approve")
    assert sorted(r.json()["available_actions"]) == ["handoff", "publish", "redo"]
    r = _act(client, world, world.dsm_a, auth, report_id, "publish")
    assert sorted(r.json()["available_actions"]) == ["handoff", "redo"]  # already published

    # An assessment is reviewed by Radial Pulse staff only (decision D15): nothing for clinic people.
    assessment = Assessment(
        clinic_id=world.clinic_a.id, sequence=1, status=AssessmentStatus.COMPLETED, methodology_version="t"
    )
    db.add(assessment)
    db.commit()
    r = client.post(
        f"{approvals}/actions",
        headers=auth(world.dsm_a),
        json={"resource_type": "assessment", "resource_id": str(assessment.id), "action": "submit"},
    )
    assert r.status_code == 200, r.text
    assert sorted(r.json()["available_actions"]) == ["approve", "handoff", "redo", "reject"]
    # Clinic people do not even see that the review exists (audit SEC-2).
    assert "assessment" not in listed(world.clinic_admin_a)


def test_unregistered_resource_types_are_rejected(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        f"/api/v1/clinics/{world.clinic_a.id}/approvals/actions",
        headers=auth(world.dsm_a),
        json={"resource_type": "anything", "resource_id": str(world.clinic_a.id), "action": "submit"},
    )
    assert r.status_code == 422


def test_work_items_and_snapshots(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    a = world.clinic_a.id
    r = client.post(
        f"/api/v1/clinics/{a}/work-items",
        headers=auth(world.dsm_a),
        json={"kind": "seo_audit_review", "title": "Review audit", "owner_user_id": str(world.dsm_a.id)},
    )
    assert r.status_code == 201, r.text
    item = r.json()
    bad_owner = client.patch(
        f"/api/v1/clinics/{a}/work-items/{item['id']}",
        headers=auth(world.dsm_a),
        json={"owner_user_id": str(world.clinic_admin_b.id)},
    )
    assert bad_owner.status_code == 422
    done = client.patch(
        f"/api/v1/clinics/{a}/work-items/{item['id']}", headers=auth(world.dsm_a), json={"status": "done"}
    )
    assert done.json()["status"] == "done"
    assert (
        client.post(
            f"/api/v1/clinics/{a}/work-items",
            headers=auth(world.clinic_admin_a),
            json={"kind": "x", "title": "y"},
        ).status_code
        == 403
    )

    snap = {
        "source": "google_business_profile",
        "metric_key": "gbp.review_count",
        "value": {"value": 128},
        "fetched_at": "2026-09-25T06:00:00Z",
        "status": "ok",
    }
    err = {**snap, "status": "error", "error_code": "quota", "retry_count": 2, "value": {}}
    r = client.post(
        f"/api/v1/clinics/{a}/snapshots", headers=auth(world.dsm_a), json={"snapshots": [snap, err]}
    )
    assert r.status_code == 201, r.text
    listed = client.get(
        f"/api/v1/clinics/{a}/snapshots?metric_key=gbp.review_count", headers=auth(world.clinic_admin_a)
    ).json()
    assert listed["total"] == 2
    assert (
        client.post(
            f"/api/v1/clinics/{a}/snapshots", headers=auth(world.clinic_admin_a), json={"snapshots": [snap]}
        ).status_code
        == 403
    )
    bad_key = {**snap, "metric_key": "NoDots"}
    assert (
        client.post(
            f"/api/v1/clinics/{a}/snapshots", headers=auth(world.dsm_a), json={"snapshots": [bad_key]}
        ).status_code
        == 422
    )
