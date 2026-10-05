"""Client Collaboration (chat): one conversation per clinic, unread counts, attachments, who may send."""

from __future__ import annotations

from app.integrations.storage import ObjectInfo
from app.models import AuditEvent


def _chat(clinic_id: object) -> str:
    return f"/api/v1/clinics/{clinic_id}/chat"


def _send(client, auth, user, clinic_id, text: str):  # type: ignore[no-untyped-def]
    r = client.post(f"{_chat(clinic_id)}/messages", headers=auth(user), json={"body": text})
    assert r.status_code == 201, r.text
    return r.json()


def test_dsm_and_clinic_admin_talk_and_unread_counts_follow(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_a.id
    sent = _send(client, auth, world.dsm_a, cid, "Hello Dr. Rahul, your report is ready")
    assert sent["sender_side"] == "radial_pulse"
    assert sent["sender_name"]  # copied at send time

    page = client.get(f"{_chat(cid)}/messages", headers=auth(world.clinic_admin_a)).json()
    assert [m["body"] for m in page["items"]] == ["Hello Dr. Rahul, your report is ready"]
    assert page["unread_count"] == 1
    inbox = client.get("/api/v1/chat/inbox", headers=auth(world.clinic_admin_a)).json()
    assert inbox["unread_threads"] == 1 and inbox["unread_messages"] == 1
    assert inbox["items"][0]["clinic_name"] == "Smile Dental A"

    reply = _send(client, auth, world.clinic_admin_a, cid, "Thanks!")
    assert reply["sender_side"] == "clinic"
    # Sending marks my own reading position, so the DSM's message is now read for me …
    inbox = client.get("/api/v1/chat/inbox", headers=auth(world.clinic_admin_a)).json()
    assert inbox["unread_messages"] == 0
    # … and the DSM has one unread reply.
    inbox = client.get("/api/v1/chat/inbox", headers=auth(world.dsm_a)).json()
    assert inbox["unread_threads"] == 1
    assert inbox["items"][0]["last_message"]["body"] == "Thanks!"

    r = client.post(f"{_chat(cid)}/read", headers=auth(world.dsm_a), json={})
    assert r.status_code == 204
    assert client.get("/api/v1/chat/inbox", headers=auth(world.dsm_a)).json()["unread_messages"] == 0


def test_team_member_reads_but_cannot_send(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_a.id
    _send(client, auth, world.dsm_a, cid, "Hi team")
    assert client.get(f"{_chat(cid)}/messages", headers=auth(world.team_member_a)).status_code == 200
    r = client.post(f"{_chat(cid)}/messages", headers=auth(world.team_member_a), json={"body": "Hi"})
    assert r.status_code == 403


def test_other_clinic_cannot_read_or_write(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_a.id
    _send(client, auth, world.dsm_a, cid, "private to A")
    h = auth(world.clinic_admin_b)
    assert client.get(f"{_chat(cid)}/messages", headers=h).status_code == 404
    assert client.post(f"{_chat(cid)}/messages", headers=h, json={"body": "x"}).status_code == 404
    assert client.get("/api/v1/chat/inbox", headers=h).json()["items"] == []


def test_paging_older_and_polling_newer(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_a.id
    ids = [_send(client, auth, world.dsm_a, cid, f"m{i}")["id"] for i in range(5)]
    h = auth(world.clinic_admin_a)

    newest = client.get(f"{_chat(cid)}/messages", headers=h, params={"limit": 2}).json()
    assert [m["body"] for m in newest["items"]] == ["m3", "m4"]  # oldest first
    assert newest["has_more"] is True

    older = client.get(f"{_chat(cid)}/messages", headers=h, params={"limit": 2, "before": ids[3]}).json()
    assert [m["body"] for m in older["items"]] == ["m1", "m2"]
    oldest = client.get(f"{_chat(cid)}/messages", headers=h, params={"limit": 2, "before": ids[1]}).json()
    assert [m["body"] for m in oldest["items"]] == ["m0"] and oldest["has_more"] is False

    polled = client.get(f"{_chat(cid)}/messages", headers=h, params={"after": ids[2]}).json()
    assert [m["body"] for m in polled["items"]] == ["m3", "m4"] and polled["has_more"] is False
    both = client.get(f"{_chat(cid)}/messages", headers=h, params={"after": ids[0], "before": ids[4]})
    assert both.status_code == 422


def test_empty_message_is_refused(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{_chat(world.clinic_a.id)}/messages", headers=auth(world.dsm_a), json={"body": "   "})
    assert r.status_code == 422


def test_attachment_must_be_an_uploaded_chat_file_of_this_clinic(client, world, auth, storage) -> None:  # type: ignore[no-untyped-def]
    cid = world.clinic_a.id
    h = auth(world.clinic_admin_a)
    up = client.post(
        f"/api/v1/clinics/{cid}/assets/uploads",
        headers=h,
        json={"kind": "chat_attachment", "mime_type": "application/pdf", "size_bytes": 1000},
    ).json()["asset"]
    # Not uploaded yet → refused.
    r = client.post(f"{_chat(cid)}/messages", headers=h, json={"attachment_asset_id": up["id"]})
    assert r.status_code == 422

    storage.objects[f"clinics/{cid}/chat_attachment/{up['id']}.pdf"] = ObjectInfo(
        size_bytes=1000, content_type="application/pdf", etag="e"
    )
    assert client.post(f"/api/v1/clinics/{cid}/assets/{up['id']}/confirm", headers=h).status_code == 200
    r = client.post(f"{_chat(cid)}/messages", headers=h, json={"attachment_asset_id": up["id"]})
    assert r.status_code == 201, r.text
    assert r.json()["attachment_asset_id"] == up["id"] and r.json()["body"] is None

    # An asset of clinic A cannot be sent into clinic B's chat.
    r = client.post(
        f"{_chat(world.clinic_b.id)}/messages",
        headers=auth(world.admin),
        json={"attachment_asset_id": up["id"]},
    )
    assert r.status_code == 404


def test_admin_inbox_only_has_chats_they_took_part_in(client, world, auth) -> None:  # type: ignore[no-untyped-def]
    _send(client, auth, world.dsm_a, world.clinic_a.id, "hello A")
    _send(client, auth, world.clinic_admin_b, world.clinic_b.id, "hello B")
    h = auth(world.admin)
    assert client.get("/api/v1/chat/inbox", headers=h).json()["items"] == []
    # The admin opens B's chat (reads it) → B is now in their inbox.
    assert client.post(f"{_chat(world.clinic_b.id)}/read", headers=h, json={}).status_code == 204
    inbox = client.get("/api/v1/chat/inbox", headers=h).json()
    assert [t["clinic_name"] for t in inbox["items"]] == ["Bright Clinic B"]
    assert inbox["unread_messages"] == 0


def test_audit_log_records_the_message_but_never_its_text(client, db, world, auth) -> None:  # type: ignore[no-untyped-def]
    _send(client, auth, world.dsm_a, world.clinic_a.id, "secret words")
    events = [e for e in db.query(AuditEvent).all() if e.action == "chat.message_sent"]
    assert len(events) == 1
    assert "secret words" not in str(events[0].details)
