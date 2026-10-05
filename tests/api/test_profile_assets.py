from __future__ import annotations

from app.integrations.storage import ObjectInfo
from app.models import AuditEvent


def test_profile_read_update_and_version_conflict(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    path = f"/api/v1/clinics/{world.clinic_a.id}/profile"
    h = auth(world.clinic_admin_a)
    profile = client.get(path, headers=h).json()
    assert profile["version"] == 1
    assert profile["team"]  # roles are part of the client context

    update = {
        "version": 1,
        "brand": {"tagline": "Gentle dentistry", "primary_color": "#167973"},
        "schedule": {"opening_hours": {"mon": [{"opens": "09:00", "closes": "18:00"}]}},
    }
    r = client.put(path, headers=h, json=update)
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 2
    assert r.json()["brand"]["tagline"] == "Gentle dentistry"

    stale = client.put(path, headers=h, json=update)
    assert stale.status_code == 409
    assert db.query(AuditEvent).filter_by(action="profile.update").count() == 1


def test_profile_rejects_bad_values(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    path = f"/api/v1/clinics/{world.clinic_a.id}/profile"
    bad = {"version": 1, "brand": {"primary_color": "red"}}
    assert client.put(path, headers=auth(world.clinic_admin_a), json=bad).status_code == 422
    unknown = {"version": 1, "brand": {"favourite_food": "dosa"}}
    assert client.put(path, headers=auth(world.clinic_admin_a), json=unknown).status_code == 422


def test_asset_upload_flow(client, db, world, auth, storage) -> None:  # type: ignore[no-untyped-def]
    base = f"/api/v1/clinics/{world.clinic_a.id}/assets"
    h = auth(world.clinic_admin_a)
    r = client.post(
        f"{base}/uploads",
        headers=h,
        json={
            "kind": "clinic_photo",
            "mime_type": "image/png",
            "size_bytes": 2048,
            "original_filename": "../../x.png",
            "category": "reception_waiting",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    asset = body["asset"]
    assert asset["status"] == "pending_upload"
    assert body["upload_headers"] == {"Content-Type": "image/png"}
    key = f"clinics/{world.clinic_a.id}/clinic_photo/{asset['id']}.png"
    assert key in body["upload_url"]  # the filename never becomes part of the key

    # Confirm before upload -> rejected, asset stays pending
    assert client.post(f"{base}/{asset['id']}/confirm", headers=h).status_code == 422

    storage.objects[key] = ObjectInfo(size_bytes=2048, content_type="image/png", etag="e")
    r = client.post(f"{base}/{asset['id']}/confirm", headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "uploaded"
    assert client.post(f"{base}/{asset['id']}/confirm", headers=h).status_code == 409

    r = client.get(f"{base}/{asset['id']}/download-url", headers=h)
    assert r.status_code == 200
    actions = [e.action for e in db.query(AuditEvent).order_by(AuditEvent.occurred_at)]
    assert actions[:1] == ["asset.upload_requested"]
    assert "asset.upload_confirmed" in actions and "asset.download_url_issued" in actions


def test_asset_size_mismatch_fails_and_deletes_object(client, world, auth, storage) -> None:  # type: ignore[no-untyped-def]
    base = f"/api/v1/clinics/{world.clinic_a.id}/assets"
    h = auth(world.clinic_admin_a)
    asset = client.post(
        f"{base}/uploads", headers=h, json={"kind": "logo", "mime_type": "image/png", "size_bytes": 100}
    ).json()["asset"]
    key = f"clinics/{world.clinic_a.id}/logo/{asset['id']}.png"
    storage.objects[key] = ObjectInfo(size_bytes=999_999, content_type="image/png", etag="e")
    assert client.post(f"{base}/{asset['id']}/confirm", headers=h).status_code == 422
    assert key in storage.deleted


def test_asset_type_and_size_limits(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    base = f"/api/v1/clinics/{world.clinic_a.id}/assets/uploads"
    h = auth(world.clinic_admin_a)
    exe = {"kind": "clinic_photo", "mime_type": "application/x-msdownload", "size_bytes": 10}
    assert client.post(base, headers=h, json=exe).status_code == 422
    huge = {"kind": "video", "mime_type": "video/mp4", "size_bytes": 10 * 1024 * 1024 + 1}
    assert client.post(base, headers=h, json=huge).status_code == 422
