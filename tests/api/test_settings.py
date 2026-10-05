"""Settings: platform settings (Admin), integrations, my notification switches, my profile photo."""

from __future__ import annotations

from app.integrations.storage import ObjectInfo
from app.models import Notification


def test_everyone_reads_platform_settings_only_admin_changes_them(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/settings/platform", headers=auth(world.clinic_admin_a))
    assert r.status_code == 200
    assert r.json()["timezone"] == "Asia/Kolkata" and r.json()["date_format"] == "DD MMM YYYY"

    change = {"support_email": "Help@RadialPulse.com", "organization_name": "Radial Pulse Pvt Ltd"}
    assert (
        client.patch("/api/v1/settings/platform", headers=auth(world.dsm_a), json=change).status_code == 403
    )
    r = client.patch("/api/v1/settings/platform", headers=auth(world.admin), json=change)
    assert r.status_code == 200, r.text
    assert r.json()["support_email"] == "help@radialpulse.com"
    got = client.get("/api/v1/settings/platform", headers=auth(world.team_member_a)).json()
    assert got["organization_name"] == "Radial Pulse Pvt Ltd"


def test_platform_settings_validation(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.admin)
    assert (
        client.patch("/api/v1/settings/platform", headers=h, json={"timezone": "Mars/Base"}).status_code
        == 422
    )
    assert (
        client.patch("/api/v1/settings/platform", headers=h, json={"organization_name": None}).status_code
        == 422
    )
    assert (
        client.patch("/api/v1/settings/platform", headers=h, json={"date_format": "MM/DD"}).status_code == 422
    )


def test_integrations_are_admin_only_and_show_no_secrets(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/settings/integrations", headers=auth(world.dsm_a)).status_code == 403
    r = client.get("/api/v1/settings/integrations", headers=auth(world.admin))
    assert r.status_code == 200
    configured = {c["platform"]: c["configured"] for c in r.json()["connections"]}
    assert configured["instagram"] is True and configured["x"] is False
    assert "secret" not in r.text


def test_notification_switches_default_on_and_are_respected(client, world, auth, db) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.dsm_a)
    items = client.get("/api/v1/auth/me/notification-settings", headers=h).json()["items"]
    assert items and all(i["enabled"] for i in items)

    off = {"items": [{"category": "work_item_assigned", "channel": "in_app", "enabled": False}]}
    r = client.put("/api/v1/auth/me/notification-settings", headers=h, json=off)
    assert r.status_code == 200
    states = {(i["category"], i["channel"]): i["enabled"] for i in r.json()["items"]}
    assert states[("work_item_assigned", "in_app")] is False
    assert states[("work_item_assigned", "email")] is True

    # The Admin gives the DSM a work item: no notification, because the DSM switched it off.
    r = client.post(
        f"/api/v1/clinics/{world.clinic_a.id}/work-items",
        headers=auth(world.admin),
        json={"title": "Fix GBP hours", "owner_user_id": str(world.dsm_a.id)},
    )
    assert r.status_code == 201, r.text
    assert db.query(Notification).filter(Notification.user_id == world.dsm_a.id).count() == 0

    # Someone else's switches are not theirs to change or see.
    other = client.get("/api/v1/auth/me/notification-settings", headers=auth(world.admin)).json()["items"]
    assert all(i["enabled"] for i in other)


def test_profile_photo_upload_confirm_and_remove(client, world, auth, storage) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.dsm_a)
    bad = client.post(
        "/api/v1/auth/me/avatar/uploads", headers=h, json={"mime_type": "image/gif", "size_bytes": 10}
    )
    assert bad.status_code == 422
    up = client.post(
        "/api/v1/auth/me/avatar/uploads", headers=h, json={"mime_type": "image/png", "size_bytes": 10}
    )
    assert up.status_code == 200, up.text
    key = up.json()["key"]
    assert key.startswith(f"users/{world.dsm_a.id}/avatar/")

    # Someone else's key, or a key that was never uploaded, is refused.
    other_key = f"users/{world.admin.id}/avatar/x.png"
    assert (
        client.post("/api/v1/auth/me/avatar/confirm", headers=h, json={"key": other_key}).status_code == 422
    )
    assert client.post("/api/v1/auth/me/avatar/confirm", headers=h, json={"key": key}).status_code == 422

    storage.objects[key] = ObjectInfo(size_bytes=10, content_type="image/png", etag="e")
    r = client.post("/api/v1/auth/me/avatar/confirm", headers=h, json={"key": key})
    assert r.status_code == 200, r.text
    assert key in r.json()["avatar_url"]
    assert client.get("/api/v1/auth/me", headers=h).json()["sign_in_method"] == "google"

    r = client.delete("/api/v1/auth/me/avatar", headers=h)
    assert r.status_code == 200 and r.json()["avatar_url"] is None
    assert key in storage.deleted
