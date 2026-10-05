"""Clinic media review (V1) and the security fixes from the backend audit (5 Oct 2026).

The Clinic Administrator uploads clinic photos, doctor photos and voice samples. Confirming the
upload submits it for review. Only the DSM / Platform Administrator approve, reject or ask for a
retake. Internal notes and unpublished report files never reach clinic people.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from app.core.enums import AssessmentStatus, AssetKind, AssetStatus
from app.db.base import utcnow
from app.integrations.storage import ObjectInfo
from app.models import Approval, ApprovalNote, Assessment, Asset, AuditEvent

PHOTO = {
    "kind": "clinic_photo",
    "mime_type": "image/png",
    "size_bytes": 2048,
    "category": "reception_waiting",
}


def _base(world: Any, clinic: Any = None) -> str:
    return f"/api/v1/clinics/{(clinic or world.clinic_a).id}"


def _upload(client, world, auth, storage, user, body=None, confirm=True):  # type: ignore[no-untyped-def]
    """Step 1 (+ the S3 PUT + step 3). Returns the asset JSON after the last step."""
    body = body or PHOTO
    r = client.post(f"{_base(world)}/assets/uploads", headers=auth(user), json=body)
    assert r.status_code == 201, r.text
    asset = r.json()["asset"]
    if not confirm:
        return asset
    key = next(k for k in storage.signed_lengths if asset["id"] in k)
    storage.objects[key] = ObjectInfo(size_bytes=body["size_bytes"], content_type=body["mime_type"], etag="e")
    r = client.post(f"{_base(world)}/assets/{asset['id']}/confirm", headers=auth(user))
    assert r.status_code == 200, r.text
    return r.json()


def _act(client, world, auth, user, asset_id, action, **extra):  # type: ignore[no-untyped-def]
    return client.post(
        f"{_base(world)}/approvals/actions",
        headers=auth(user),
        json={"resource_type": "asset", "resource_id": asset_id, "action": action, **extra},
    )


# ------------------------------------------------------------------ upload → review
def test_confirmed_clinic_media_goes_to_review_and_only_staff_decide(
    client, db, world, auth, storage
) -> None:  # type: ignore[no-untyped-def]
    asset = _upload(client, world, auth, storage, world.clinic_admin_a)
    assert asset["status"] == "uploaded"
    assert asset["approval_state"] == "submitted"  # confirm = submitted for review
    assert asset["review"]["state"] == "submitted"
    assert asset["review"]["available_actions"] == []  # the clinic has nothing to decide
    assert asset["category"] == "reception_waiting"

    # The Clinic Administrator can NEVER approve, reject or ask for a retake of clinic media.
    for action in ("approve", "reject", "redo"):
        assert _act(client, world, auth, world.clinic_admin_a, asset["id"], action).status_code == 403
    assert _act(client, world, auth, world.team_member_a, asset["id"], "approve").status_code == 403

    # The DSM sees the review buttons and decides.
    seen = client.get(f"{_base(world)}/assets/{asset['id']}", headers=auth(world.dsm_a)).json()
    assert sorted(seen["review"]["available_actions"]) == ["approve", "handoff", "redo", "reject"]
    r = _act(client, world, auth, world.dsm_a, asset["id"], "approve")
    assert r.status_code == 200 and r.json()["state"] == "approved"
    assert db.get(Asset, UUID(asset["id"])).approval_state.value == "approved"
    actions = [e.action for e in db.query(AuditEvent).order_by(AuditEvent.occurred_at)]
    assert "approval.submit" in actions and "approval.approve" in actions


def test_platform_administrator_reviews_but_staff_never_upload_media(client, world, auth, storage) -> None:  # type: ignore[no-untyped-def]
    asset = _upload(client, world, auth, storage, world.clinic_admin_a)
    r = _act(client, world, auth, world.admin, asset["id"], "reject", clinic_message="Too dark")
    assert r.status_code == 200 and r.json()["state"] == "rejected"
    # Radial Pulse staff are read/review-only for clinic media.
    for staff in (world.admin, world.dsm_a):
        for body in (
            PHOTO,
            {"kind": "audio", "mime_type": "audio/mpeg", "size_bytes": 10, "category": "clinic_greeting"},
        ):
            r = client.post(f"{_base(world)}/assets/uploads", headers=auth(staff), json=body)
            assert r.status_code == 403, r.text


def test_nothing_is_reviewed_before_the_upload_is_confirmed(client, db, world, auth, storage) -> None:  # type: ignore[no-untyped-def]
    pending = _upload(client, world, auth, storage, world.clinic_admin_a, confirm=False)
    assert pending["status"] == "pending_upload" and pending["review"] is None
    # No review exists yet, so nobody can decide; a manual submit is refused while unconfirmed.
    assert _act(client, world, auth, world.dsm_a, pending["id"], "approve").status_code == 409
    assert _act(client, world, auth, world.clinic_admin_a, pending["id"], "submit").status_code == 409
    assert db.query(Approval).count() == 0

    # A failed upload (wrong size) never enters review either.
    key = next(k for k in storage.signed_lengths if pending["id"] in k)
    storage.objects[key] = ObjectInfo(size_bytes=1, content_type="image/png", etag="e")
    r = client.post(f"{_base(world)}/assets/{pending['id']}/confirm", headers=auth(world.clinic_admin_a))
    assert r.status_code == 422
    assert db.query(Approval).count() == 0


def test_team_member_cannot_confirm_media_uploaded_by_the_administrator(
    client, db, world, auth, storage
) -> None:  # type: ignore[no-untyped-def]
    pending = _upload(client, world, auth, storage, world.clinic_admin_a, confirm=False)
    key = next(k for k in storage.signed_lengths if pending["id"] in k)
    storage.objects[key] = ObjectInfo(size_bytes=2048, content_type="image/png", etag="e")
    r = client.post(f"{_base(world)}/assets/{pending['id']}/confirm", headers=auth(world.team_member_a))
    assert r.status_code == 403
    assert db.get(Asset, UUID(pending["id"])).status is AssetStatus.PENDING_UPLOAD


def test_retake_is_a_new_upload_linked_to_the_old_one(client, db, world, auth, storage) -> None:  # type: ignore[no-untyped-def]
    first = _upload(client, world, auth, storage, world.clinic_admin_a)
    r = _act(
        client, world, auth, world.dsm_a, first["id"], "redo", clinic_message="Please retake in daylight"
    )
    assert r.json()["state"] == "redo_requested"

    # The same file cannot simply be sent again: a retake is a new upload.
    assert _act(client, world, auth, world.clinic_admin_a, first["id"], "submit").status_code == 409
    old = client.get(f"{_base(world)}/assets/{first['id']}", headers=auth(world.clinic_admin_a)).json()
    assert "submit" not in old["review"]["available_actions"]
    assert old["review"]["clinic_message"] == "Please retake in daylight"

    retake = _upload(
        client, world, auth, storage, world.clinic_admin_a, body={**PHOTO, "previous_version_id": first["id"]}
    )
    assert retake["version"] == 2 and retake["previous_version_id"] == first["id"]
    assert retake["review"]["state"] == "submitted"
    assert db.get(Asset, UUID(first["id"])).approval_state.value == "redo_requested"
    # A new version must be the same kind of file.
    r = client.post(
        f"{_base(world)}/assets/uploads",
        headers=auth(world.clinic_admin_a),
        json={"kind": "audio", "mime_type": "audio/mpeg", "size_bytes": 10, "category": "clinic_greeting",
              "previous_version_id": first["id"]},
    )  # fmt: skip
    assert r.status_code == 422


# ------------------------------------------------------------------ review notes
def test_internal_notes_never_reach_clinic_people(client, db, world, auth, storage) -> None:  # type: ignore[no-untyped-def]
    asset = _upload(client, world, auth, storage, world.clinic_admin_a)
    r = _act(
        client, world, auth, world.dsm_a, asset["id"], "reject",
        comment="Internal: watermark from a stock site", clinic_message="Please upload your own photo",
    )  # fmt: skip
    assert r.status_code == 200
    assert r.json()["last_comment"] == "Internal: watermark from a stock site"
    assert db.query(ApprovalNote).count() == 1
    assert db.query(Approval).one().last_comment is None  # the old column is no longer written

    approval_id = r.json()["id"]
    for user in (world.clinic_admin_a, world.team_member_a):
        h = auth(user)
        rows = client.get(f"{_base(world)}/approvals", headers=h).json()["items"]
        one = client.get(f"{_base(world)}/approvals/{approval_id}", headers=h).json()
        file = client.get(f"{_base(world)}/assets/{asset['id']}", headers=h).json()
        listed = client.get(f"{_base(world)}/assets", headers=h).json()["items"][0]
        for seen in (rows[0], one):
            assert seen["last_comment"] is None
            assert seen["clinic_message"] == "Please upload your own photo"
        for seen in (file, listed):
            assert seen["review"]["internal_note"] is None
            assert seen["review"]["clinic_message"] == "Please upload your own photo"
        assert "watermark" not in str(rows) + str(one) + str(file) + str(listed)
    staff_view = client.get(f"{_base(world)}/assets/{asset['id']}", headers=auth(world.admin)).json()
    assert staff_view["review"]["internal_note"] == "Internal: watermark from a stock site"
    # The audit log (readable by the Clinic Administrator) never holds the note text.
    assert "watermark" not in str([e.details for e in db.query(AuditEvent).all()])


def test_clinic_people_never_decide_any_review_nor_write_internal_notes(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        f"{_base(world)}/reports", headers=auth(world.dsm_a),
        json={"report_type": "website_brief", "report_key": "brief:1", "title": "Brief"},
    )  # fmt: skip
    body = {"resource_type": "report_artifact", "resource_id": r.json()["id"]}
    actions = f"{_base(world)}/approvals/actions"
    assert (
        client.post(actions, headers=auth(world.dsm_a), json={**body, "action": "submit"}).status_code == 200
    )
    # Report outputs are reviewed by Radial Pulse staff only (decision D24).
    for action in ("approve", "reject", "redo", "publish", "handoff"):
        r = client.post(actions, headers=auth(world.clinic_admin_a), json={**body, "action": action})
        assert r.status_code == 403, action
    r = client.post(
        actions, headers=auth(world.dsm_a), json={**body, "action": "approve", "clinic_message": "OK"}
    )
    assert r.status_code == 200 and r.json()["clinic_message"] == "OK"
    # A clinic message only goes with a decision.
    r = client.post(
        actions, headers=auth(world.dsm_a), json={**body, "action": "publish", "clinic_message": "x"}
    )
    assert r.status_code == 422

    # The one thing a clinic person may do is submit their own media — without an internal note.
    draft = Asset(
        clinic_id=world.clinic_a.id, kind=AssetKind.CLINIC_PHOTO, mime_type="image/png", size_bytes=1,
        storage_key=f"clinics/{world.clinic_a.id}/clinic_photo/draft.png", status=AssetStatus.UPLOADED,
    )  # fmt: skip
    db.add(draft)
    db.commit()
    media = {"resource_type": "asset", "resource_id": str(draft.id), "action": "submit"}
    r = client.post(actions, headers=auth(world.clinic_admin_a), json={**media, "comment": "note"})
    assert r.status_code == 403
    assert client.post(actions, headers=auth(world.clinic_admin_a), json=media).status_code == 200


def test_review_activity_stays_out_of_the_clinic_audit_log(client, db, world, auth, storage) -> None:  # type: ignore[no-untyped-def]
    asset = _upload(client, world, auth, storage, world.clinic_admin_a)
    _act(client, world, auth, world.dsm_a, asset["id"], "approve")
    assessment = Assessment(
        clinic_id=world.clinic_a.id, sequence=1, status=AssessmentStatus.COMPLETED, methodology_version="t"
    )
    db.add(assessment)
    db.add(
        AuditEvent(
            action="assessment.requested", resource_type="assessment", resource_id=str(assessment.id),
            clinic_id=world.clinic_a.id, details={},
        )
    )  # fmt: skip
    db.commit()

    def actions(user):  # type: ignore[no-untyped-def]
        r = client.get(f"{_base(world)}/audit-events", headers=auth(user), params={"limit": 200})
        assert r.status_code == 200, r.text
        return {e["action"] for e in r.json()["items"]}

    clinic_view = actions(world.clinic_admin_a)
    assert "asset.upload_confirmed" in clinic_view  # their own work stays visible
    assert not any(a.startswith(("approval.", "assessment.")) for a in clinic_view)
    assert {"approval.submit", "approval.approve", "assessment.requested"} <= actions(world.dsm_a)


def test_staff_only_reviews_are_invisible_to_clinic_people(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    assessment = Assessment(
        clinic_id=world.clinic_a.id, sequence=1, status=AssessmentStatus.COMPLETED, methodology_version="t"
    )
    db.add(assessment)
    db.commit()
    r = client.post(
        f"{_base(world)}/approvals/actions", headers=auth(world.dsm_a),
        json={"resource_type": "assessment", "resource_id": str(assessment.id), "action": "submit",
              "comment": "Score looks too low, rerun SEO"},
    )  # fmt: skip
    approval_id = r.json()["id"]
    for user in (world.clinic_admin_a, world.team_member_a):
        assert client.get(f"{_base(world)}/approvals/{approval_id}", headers=auth(user)).status_code == 404
        assert client.get(f"{_base(world)}/approvals", headers=auth(user)).json()["total"] == 0
    assert client.get(f"{_base(world)}/approvals/{approval_id}", headers=auth(world.dsm_a)).status_code == 200


# ------------------------------------------------------------------ report files
def test_unpublished_report_files_cannot_be_listed_or_downloaded_by_clinic_people(  # type: ignore[no-untyped-def]
    client, db, world, auth, storage
) -> None:
    base = _base(world)
    # The DSM uploads the rendered report file and registers the report.
    file = _upload(
        client, world, auth, storage, world.dsm_a,
        body={"kind": "report", "mime_type": "application/pdf", "size_bytes": 300},
    )  # fmt: skip
    r = client.post(
        f"{base}/reports", headers=auth(world.dsm_a),
        json={"report_type": "assessment_export", "report_key": "export:1", "title": "Export",
              "asset_id": file["id"]},
    )  # fmt: skip
    report_id = r.json()["id"]
    stray = _upload(  # a report file that is not attached to any report yet
        client, world, auth, storage, world.dsm_a,
        body={"kind": "report", "mime_type": "application/pdf", "size_bytes": 301},
    )  # fmt: skip

    def clinic_can_see(asset_id: str) -> bool:
        h = auth(world.clinic_admin_a)
        listed = {a["id"] for a in client.get(f"{base}/assets", headers=h).json()["items"]}
        single = client.get(f"{base}/assets/{asset_id}", headers=h).status_code
        link = client.get(f"{base}/assets/{asset_id}/download-url", headers=h).status_code
        assert (single == 200) == (link == 200) == (asset_id in listed), (single, link)
        return asset_id in listed

    assert not clinic_can_see(file["id"])
    assert not clinic_can_see(stray["id"])
    assert (
        client.get(f"{base}/assets/{file['id']}/download-url", headers=auth(world.dsm_a)).status_code == 200
    )

    for action in ("submit", "approve", "publish"):
        r = client.post(
            f"{base}/approvals/actions", headers=auth(world.dsm_a),
            json={"resource_type": "report_artifact", "resource_id": report_id, "action": action},
        )  # fmt: skip
        assert r.status_code == 200, r.text
    assert clinic_can_see(file["id"])  # published: readable like before
    assert not clinic_can_see(stray["id"])
    # Clinic people cannot upload "report" files themselves.
    r = client.post(
        f"{base}/assets/uploads", headers=auth(world.clinic_admin_a),
        json={"kind": "report", "mime_type": "application/pdf", "size_bytes": 10},
    )  # fmt: skip
    assert r.status_code == 403


# ------------------------------------------------------------------ labels + filters
def test_media_labels_follow_the_kind_and_the_taxonomy(client, world, auth, storage) -> None:  # type: ignore[no-untyped-def]
    url = f"{_base(world)}/assets/uploads"
    h = auth(world.clinic_admin_a)
    doctor = {"kind": "practitioner_photo", "mime_type": "image/jpeg", "size_bytes": 10,
              "practitioner_id": str(world.practitioner_a.id), "apron": "with_apron", "angle": "45_left",
              "outfit": "outfit_1"}  # fmt: skip
    r = client.post(url, headers=h, json=doctor)
    assert r.status_code == 201, r.text
    got = r.json()["asset"]
    assert (got["practitioner_id"], got["apron"], got["angle"], got["outfit"]) == (
        str(world.practitioner_a.id),
        "with_apron",
        "45_left",
        "outfit_1",
    )
    bad = [
        {**doctor, "practitioner_id": None},  # who is in the photo?
        {**doctor, "angle": None},  # every doctor-photo label is required
        {**doctor, "angle": "outfit_1"},  # a value of another list
        {**doctor, "outfit": "outfit_9"},  # not in the taxonomy
        {**doctor, "category": "team_at_work"},  # not a doctor-photo label
        {**PHOTO, "category": None},
        {**PHOTO, "category": "clinic_greeting"},  # a voice sample, not a photo category
        {**PHOTO, "apron": "with_apron"},
        {**PHOTO, "practitioner_id": str(world.practitioner_a.id)},
        {"kind": "audio", "mime_type": "audio/mpeg", "size_bytes": 10, "category": "exterior_signage"},
        {"kind": "document", "mime_type": "application/pdf", "size_bytes": 10, "category": "team_at_work"},
    ]
    for body in bad:
        body = {k: v for k, v in body.items() if v is not None}
        assert client.post(url, headers=h, json=body).status_code == 422, body
    # A practitioner of ANOTHER clinic cannot be used (same answer as "does not exist").
    r = client.post(url, headers=h, json={**doctor, "practitioner_id": str(world.practitioner_b.id)})
    assert r.status_code == 404
    voice = {"kind": "audio", "mime_type": "audio/mpeg", "size_bytes": 10, "category": "clinic_greeting"}
    assert client.post(url, headers=h, json=voice).json()["asset"]["category"] == "clinic_greeting"


def test_asset_filters_and_single_get(client, world, auth, storage) -> None:  # type: ignore[no-untyped-def]
    reviewed = _upload(client, world, auth, storage, world.clinic_admin_a)
    _upload(client, world, auth, storage, world.clinic_admin_a, body={**PHOTO, "category": "team_at_work"})
    _upload(client, world, auth, storage, world.clinic_admin_a, confirm=False)
    doctor = _upload(
        client, world, auth, storage, world.clinic_admin_a,
        body={"kind": "practitioner_photo", "mime_type": "image/jpeg", "size_bytes": 10,
              "practitioner_id": str(world.practitioner_a.id), "apron": "without_apron", "angle": "straight",
              "outfit": "outfit_2"},
    )  # fmt: skip
    _act(client, world, auth, world.dsm_a, reviewed["id"], "approve")
    h = auth(world.dsm_a)

    def ids(**params: str) -> set[str]:
        r = client.get(f"{_base(world)}/assets", headers=h, params=params)
        assert r.status_code == 200, r.text
        return {a["id"] for a in r.json()["items"]}

    assert len(ids(approval_state="submitted")) == 2  # the review queue of this clinic
    assert ids(approval_state="approved") == {reviewed["id"]}
    assert len(ids(status="pending_upload")) == 1
    assert ids(practitioner_id=str(world.practitioner_a.id)) == {doctor["id"]}
    assert ids(kind="clinic_photo", category="reception_waiting") >= {reviewed["id"]}
    assert ids(category="no_such_category") == set()
    r = client.get(
        f"{_base(world)}/approvals", headers=h, params={"resource_type": "asset", "state": "submitted"}
    )
    assert r.json()["total"] == 2
    one = client.get(f"{_base(world)}/assets/{doctor['id']}", headers=h).json()
    assert one["angle"] == "straight" and one["review"]["state"] == "submitted"


def test_taxonomy_lists_the_exact_v1_values_in_display_order(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/media/taxonomy", headers=auth(world.clinic_admin_a))
    assert r.status_code == 200
    by_dimension: dict[str, list[str]] = {}
    for row in r.json():
        by_dimension.setdefault(row["dimension"], []).append(row["code"])
    assert by_dimension == {
        "clinic_photo_category": ["exterior_signage", "reception_waiting", "consult_procedure_rooms",
                                  "equipment_facilities", "team_at_work", "logo_cover_photo"],
        "practitioner_apron": ["with_apron", "without_apron"],
        "practitioner_angle": ["90_left", "45_left", "straight", "45_right", "90_right"],
        "practitioner_outfit": ["outfit_1", "outfit_2"],
        "voice_sample": ["clinic_greeting"],
    }  # fmt: skip
    assert client.get("/api/v1/media/taxonomy").status_code == 401


# ------------------------------------------------------------------ upload safety
def test_size_limits_are_per_file_type_and_signed_into_the_upload_url(
    client, world, auth, storage, settings
) -> None:  # type: ignore[no-untyped-def]
    settings.max_image_upload_bytes = 1000
    url = f"{_base(world)}/assets/uploads"
    h = auth(world.clinic_admin_a)
    assert client.post(url, headers=h, json={**PHOTO, "size_bytes": 1001}).status_code == 422
    assert client.post(url, headers=h, json={**PHOTO, "size_bytes": 1000}).status_code == 201
    doc = {"kind": "document", "mime_type": "application/pdf", "size_bytes": 1001}
    r = client.post(url, headers=h, json=doc)
    assert r.status_code == 201  # the image limit does not apply to PDFs
    key = next(k for k in storage.signed_lengths if r.json()["asset"]["id"] in k)
    assert storage.signed_lengths[key] == 1001  # S3 refuses a body of any other size
    assert "Content-Length" not in r.json()["upload_headers"]


def test_stale_uploads_are_removed_from_storage(db, world, session_factory, storage, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app import cli

    def pending(age_hours: int, status: AssetStatus = AssetStatus.PENDING_UPLOAD) -> Asset:
        asset = Asset(
            clinic_id=world.clinic_a.id, kind=AssetKind.DOCUMENT, mime_type="application/pdf", size_bytes=5,
            storage_key=f"clinics/{world.clinic_a.id}/document/{age_hours}-{status.value}.pdf", status=status,
            created_at=utcnow() - timedelta(hours=age_hours),
        )  # fmt: skip
        db.add(asset)
        db.commit()
        return asset

    old, fresh, done = pending(30), pending(2), pending(30, AssetStatus.UPLOADED)
    storage.objects[old.storage_key] = ObjectInfo(size_bytes=5, content_type="application/pdf", etag="e")
    monkeypatch.setattr(cli, "get_sessionmaker", lambda: session_factory)

    assert "would remove 1" in cli.cleanup_stale_uploads(dry_run=True, hours=24, storage=storage)
    assert storage.deleted == []
    assert "removed 1" in cli.cleanup_stale_uploads(dry_run=False, hours=24, storage=storage)
    db.expire_all()
    assert db.get(Asset, old.id).status is AssetStatus.FAILED
    assert db.get(Asset, fresh.id).status is AssetStatus.PENDING_UPLOAD
    assert db.get(Asset, done.id).status is AssetStatus.UPLOADED
    assert storage.deleted == [old.storage_key]
    assert db.query(AuditEvent).filter_by(action="asset.upload_expired").count() == 1


# ------------------------------------------------------------------ roles
def test_nobody_changes_their_own_role_through_the_api(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    for user in (world.clinic_admin_a, world.dsm_a, world.admin):
        r = client.patch(
            "/api/v1/auth/me", headers=auth(user), json={"platform_role": "platform_administrator"}
        )
        assert r.status_code == 422
        r = client.patch("/api/v1/auth/me", headers=auth(user), json={"is_active": True})
        assert r.status_code == 422
    # The Users screen has no role field at all, even for the Platform Administrator.
    r = client.patch(
        f"/api/v1/users/{world.admin.id}", headers=auth(world.admin), json={"platform_role": "clinic_user"}
    )
    assert r.status_code == 422
    r = client.patch(
        f"/api/v1/users/{world.dsm_a.id}",
        headers=auth(world.dsm_a),
        json={"platform_role": "platform_administrator"},
    )
    assert r.status_code in (403, 422)
