"""Areas E10 + E11: my notifications and Client Collaboration messages (docs/01 section 10)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.storage import ObjectInfo
from app.models import AuditEvent, Notification
from tests.conftest import InMemoryStorage
from tests.factories import World, build_world

pytestmark = pytest.mark.integration

SENDERS = ["admin", "dsm", "clinic_admin", "practitioner"]


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


def msgs(world: World, tail: str = "") -> str:
    return f"/api/v1/clinics/{world.clinic_a.id}/collaboration-messages{tail}"


# ------------------------------------------------------------------ notifications
def test_my_notifications_only(client: TestClient, auth, world: World, db: Session) -> None:  # type: ignore[no-untyped-def]
    db.add_all(
        [
            Notification(user_id=world.dsm_a.id, category="portfolio_allocated", title="One"),
            Notification(user_id=world.dsm_a.id, category="work_item_assigned", title="Two"),
            Notification(user_id=world.dsm_b.id, category="portfolio_allocated", title="Not mine"),
        ]
    )
    db.commit()
    h = auth(world.dsm_a)
    page = client.get("/api/v1/notifications", headers=h).json()
    assert page["total"] == 2
    first = page["items"][0]["id"]
    assert client.post(f"/api/v1/notifications/{first}/read", headers=h).json()["read_at"] is not None
    assert client.get("/api/v1/notifications", params={"unread_only": True}, headers=h).json()["total"] == 1
    assert client.post("/api/v1/notifications/read-all", headers=h).status_code == 204
    assert client.get("/api/v1/notifications", params={"unread_only": True}, headers=h).json()["total"] == 0
    theirs = db.scalar(select(Notification.id).where(Notification.user_id == world.dsm_b.id))
    assert client.post(f"/api/v1/notifications/{theirs}/read", headers=h).status_code == 404
    assert client.post(f"/api/v1/notifications/{uuid.uuid4()}/read", headers=h).status_code == 404
    assert client.get("/api/v1/notifications", params={"limit": 0}, headers=h).status_code == 400


# ------------------------------------------------------------------ messages
@pytest.mark.parametrize("who", SENDERS)
def test_who_may_send(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    r = client.post(msgs(world), json={"body": "Hello"}, headers=auth(world.people_a()[who]))
    assert r.status_code == 201, r.text
    side = "radial_pulse" if who in ("admin", "dsm") else "clinic"
    assert (r.json()["sender_side"], r.json()["sender_user_id"]) == (side, str(world.people_a()[who].id))


def test_team_member_reads_but_does_not_send(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    client.post(msgs(world), json={"body": "Hi team"}, headers=auth(world.dsm_a))
    h = auth(world.team_member_a)
    assert client.get(msgs(world), headers=h).json()["total"] == 1
    assert client.post(msgs(world), json={"body": "Can I?"}, headers=h).status_code == 403


def test_threads_are_one_level_deep(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    first = client.post(msgs(world), json={"body": "Question"}, headers=auth(world.clinic_admin_a)).json()
    reply = client.post(
        msgs(world), json={"body": "Answer", "parent_message_id": first["id"]}, headers=auth(world.dsm_a)
    ).json()
    deeper = client.post(
        msgs(world), json={"body": "x", "parent_message_id": reply["id"]}, headers=auth(world.dsm_a)
    )
    assert (deeper.status_code, deeper.json()["code"]) == (409, "state_conflict")
    threads = client.get(msgs(world), headers=auth(world.clinic_admin_a)).json()["items"]
    assert [(t["id"], t["reply_count"]) for t in threads] == [(first["id"], 1)]
    replies = client.get(
        msgs(world, f"/{first['id']}/replies"), headers=auth(world.practitioner_login_a)
    ).json()
    assert [r["body"] for r in replies] == ["Answer"]


def test_attachment_upload_send_and_audited_view(
    client: TestClient, auth, world: World, db: Session, storage: InMemoryStorage
) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.clinic_admin_a)
    t = client.post(
        msgs(world, "/attachments/uploads"),
        json={"content_type": "application/pdf", "size_bytes": 2000},
        headers=h,
    )
    key = t.json()["key"]
    assert key.startswith(f"clinics/{world.clinic_a.id}/collaboration/")
    storage.objects[key] = ObjectInfo(size_bytes=2000, content_type="application/pdf", etag="e")
    body = {
        "attachment_key": key,
        "attachment_name": "menu.pdf",
        "attachment_content_type": "application/pdf",
        "attachment_size_bytes": 2000,
    }
    sent = client.post(msgs(world), json=body, headers=h).json()
    assert (sent["has_attachment"], sent["attachment_name"]) == (True, "menu.pdf")
    link = client.get(msgs(world, f"/{sent['id']}/attachment"), headers=auth(world.team_member_a))
    assert link.status_code == 200 and link.json()["url"]
    assert (
        db.scalar(
            select(AuditEvent.actor_user_id).where(
                AuditEvent.action == "collaboration_message.attachment_viewed"
            )
        )
        == world.team_member_a.id
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"body": ""},
        {"attachment_key": "clinics/x/collaboration/a.pdf"},
        {"body": "x", "extra": 1},
    ],
)
def test_message_bad_input(client: TestClient, auth, world: World, body: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
    assert client.post(msgs(world), json=body, headers=auth(world.dsm_a)).status_code == 400


def test_attachment_from_another_clinic_is_refused(
    client: TestClient, auth, world: World, storage: InMemoryStorage
) -> None:  # type: ignore[no-untyped-def]
    key = f"clinics/{world.clinic_b.id}/collaboration/x.pdf"
    storage.objects[key] = ObjectInfo(size_bytes=10, content_type="application/pdf", etag="e")
    body = {
        "attachment_key": key,
        "attachment_name": "x.pdf",
        "attachment_content_type": "application/pdf",
        "attachment_size_bytes": 10,
    }
    assert client.post(msgs(world), json=body, headers=auth(world.dsm_a)).status_code == 400
    bad_type = client.post(
        msgs(world, "/attachments/uploads"),
        json={"content_type": "video/mp4", "size_bytes": 10},
        headers=auth(world.dsm_a),
    )
    assert bad_type.status_code == 400


def test_other_clinic_and_delete_rules(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    assert client.get(msgs(world), headers=auth(world.clinic_admin_b)).status_code == 404
    sent = client.post(msgs(world), json={"body": "Oops"}, headers=auth(world.clinic_admin_a)).json()
    assert client.delete(msgs(world, f"/{sent['id']}"), headers=auth(world.dsm_a)).status_code == 403
    assert client.delete(msgs(world, f"/{sent['id']}"), headers=auth(world.admin)).status_code == 204
    assert client.get(msgs(world, f"/{sent['id']}/replies"), headers=auth(world.admin)).status_code == 404
