"""Area E12: photos (docs/01-decisions.md section 6)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.storage import ObjectInfo
from app.models import AuditEvent
from tests.conftest import InMemoryStorage
from tests.factories import World, build_world, make_practitioner

pytestmark = pytest.mark.integration


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


def url(world: World, tail: str = "") -> str:
    return f"/api/v1/clinics/{world.clinic_a.id}/photos{tail}"


def slot(world: World, **extra: Any) -> dict[str, Any]:
    return {
        "practitioner_id": str(world.practitioner_a.id),
        "attire": "with_apron",
        "outfit_no": 1,
        "angle": "front",
        **extra,
    }


def upload(
    client: TestClient, auth, world: World, storage: InMemoryStorage, user: Any, **fields: Any
) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """Steps 1-3: ask, put the file in (fake) S3, complete."""
    body = {"content_type": "image/jpeg", "size_bytes": 1234, **fields}
    r = client.post(url(world, "/uploads"), json=body, headers=auth(user))
    assert r.status_code == 201, r.text
    photo, ticket = r.json()["photo"], r.json()["upload"]
    assert ticket["key"] == f"clinics/{world.clinic_a.id}/photos/{photo['id']}.jpg"
    storage.objects[ticket["key"]] = ObjectInfo(size_bytes=1234, content_type="image/jpeg", etag="e")
    done = client.post(url(world, f"/{photo['id']}/complete"), headers=auth(user))
    assert done.status_code == 200, done.text
    return done.json()  # type: ignore[no-any-return]


def review(client: TestClient, auth, world: World, photo_id: str, **body: Any):  # type: ignore[no-untyped-def]
    return client.post(url(world, f"/{photo_id}/review"), json=body, headers=auth(world.dsm_a))


def test_upload_approve_and_replace(
    client: TestClient, auth, world: World, storage: InMemoryStorage, db: Session
) -> None:  # type: ignore[no-untyped-def]
    first = upload(client, auth, world, storage, world.clinic_admin_a, **slot(world))
    assert (first["processing_status"], first["review_state"]) == ("ready", "pending")
    assert (
        review(client, auth, world, first["id"], review_state="approved").json()["review_state"] == "approved"
    )

    # the replacement waits; the old one stays live until the new one is approved
    second = upload(client, auth, world, storage, world.clinic_admin_a, **slot(world))
    assert review(client, auth, world, second["id"], review_state="approved").status_code == 200
    states = {
        p["id"]: (p["review_state"], p["review_note"])
        for p in client.get(url(world), headers=auth(world.dsm_a)).json()
    }
    assert states[first["id"]] == ("rejected", "Replaced by a newer photo")
    assert states[second["id"]] == ("approved", None)
    assert "photo.replaced" in set(db.scalars(select(AuditEvent.action)))


def test_one_waiting_photo_per_slot(client: TestClient, auth, world: World, storage: InMemoryStorage) -> None:  # type: ignore[no-untyped-def]
    upload(client, auth, world, storage, world.clinic_admin_a, **slot(world))
    r = client.post(
        url(world, "/uploads"),
        json={"content_type": "image/png", "size_bytes": 10, **slot(world)},
        headers=auth(world.clinic_admin_a),
    )
    assert (r.status_code, r.json()["code"]) == (409, "state_conflict")


def test_practitioner_uploads_only_his_own_photos(
    client: TestClient, auth, world: World, storage: InMemoryStorage, db: Session
) -> None:  # type: ignore[no-untyped-def]
    colleague = make_practitioner(db, world.clinic_a, full_name="Dr. Other")
    db.commit()
    own = upload(client, auth, world, storage, world.practitioner_login_a, **slot(world))
    assert own["practitioner_id"] == str(world.practitioner_a.id)
    other = slot(world, practitioner_id=str(colleague.id))
    r = client.post(
        url(world, "/uploads"),
        json={"content_type": "image/jpeg", "size_bytes": 10, **other},
        headers=auth(world.practitioner_login_a),
    )
    assert r.status_code == 403
    clinic_photo = {"content_type": "image/jpeg", "size_bytes": 10, "category": "reception_waiting"}
    assert (
        client.post(
            url(world, "/uploads"), json=clinic_photo, headers=auth(world.practitioner_login_a)
        ).status_code
        == 403
    )


@pytest.mark.parametrize("who", ["admin", "dsm", "team_member"])
def test_staff_and_team_members_never_upload(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    body = {"content_type": "image/jpeg", "size_bytes": 10, "category": "logo"}
    assert (
        client.post(url(world, "/uploads"), json=body, headers=auth(world.people_a()[who])).status_code == 403
    )


def test_clinic_photo_is_sorted_before_approval(
    client: TestClient, auth, world: World, storage: InMemoryStorage
) -> None:  # type: ignore[no-untyped-def]
    photo = upload(client, auth, world, storage, world.clinic_admin_a)  # no category: unsorted
    unsorted = client.get(url(world), params={"unsorted": True}, headers=auth(world.dsm_a)).json()
    assert [p["id"] for p in unsorted] == [photo["id"]]
    assert review(client, auth, world, photo["id"], review_state="approved").status_code == 400  # sort first
    r = review(client, auth, world, photo["id"], review_state="approved", category="exterior_signage")
    assert (r.status_code, r.json()["category"]) == (200, "exterior_signage")


def test_rejection_needs_a_note_and_happens_once(
    client: TestClient, auth, world: World, storage: InMemoryStorage
) -> None:  # type: ignore[no-untyped-def]
    photo = upload(client, auth, world, storage, world.clinic_admin_a, **slot(world))
    assert review(client, auth, world, photo["id"], review_state="rejected").status_code == 400
    r = review(client, auth, world, photo["id"], review_state="rejected", review_note="Blurry")
    assert (r.json()["review_state"], r.json()["review_note"]) == ("rejected", "Blurry")
    assert review(client, auth, world, photo["id"], review_state="approved").status_code == 409


@pytest.mark.parametrize("who", ["clinic_admin", "team_member", "practitioner"])
def test_only_staff_review_and_sort(
    client: TestClient, auth, world: World, storage: InMemoryStorage, who: str
) -> None:  # type: ignore[no-untyped-def]
    photo = upload(client, auth, world, storage, world.clinic_admin_a)
    h = auth(world.people_a()[who])
    assert (
        client.post(
            url(world, f"/{photo['id']}/review"), json={"review_state": "approved"}, headers=h
        ).status_code
        == 403
    )
    assert (
        client.post(url(world, f"/{photo['id']}/sort"), json={"category": "logo"}, headers=h).status_code
        == 403
    )


def test_view_link_is_audited(
    client: TestClient, auth, world: World, storage: InMemoryStorage, db: Session
) -> None:  # type: ignore[no-untyped-def]
    photo = upload(client, auth, world, storage, world.clinic_admin_a, category="team_at_work")
    r = client.get(url(world, f"/{photo['id']}/view"), headers=auth(world.team_member_a))
    assert r.status_code == 200 and r.json()["url"]
    viewers = db.scalars(select(AuditEvent.actor_user_id).where(AuditEvent.action == "photo.viewed")).all()
    assert viewers == [world.team_member_a.id]


def test_one_waiting_logo(client: TestClient, auth, world: World, storage: InMemoryStorage) -> None:  # type: ignore[no-untyped-def]
    upload(client, auth, world, storage, world.clinic_admin_a, category="logo")
    r = client.post(
        url(world, "/uploads"),
        json={"content_type": "image/png", "size_bytes": 5, "category": "logo"},
        headers=auth(world.clinic_admin_a),
    )
    assert r.status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"content_type": "image/gif", "size_bytes": 10, "category": "logo"},
        {"content_type": "image/png", "size_bytes": 20_000_000, "category": "logo"},
        {"content_type": "image/png", "size_bytes": 10, "attire": "with_apron"},
        {"content_type": "image/png", "size_bytes": 10, "category": "selfie"},
    ],
)
def test_upload_bad_input(client: TestClient, auth, world: World, body: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
    assert (
        client.post(url(world, "/uploads"), json=body, headers=auth(world.clinic_admin_a)).status_code == 400
    )


def test_complete_before_the_file_is_there(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        url(world, "/uploads"),
        json={"content_type": "image/png", "size_bytes": 5, "category": "logo"},
        headers=auth(world.clinic_admin_a),
    )
    photo_id = r.json()["photo"]["id"]
    assert (
        client.post(url(world, f"/{photo_id}/complete"), headers=auth(world.clinic_admin_a)).status_code
        == 400
    )


def test_delete_rules_and_other_clinic(
    client: TestClient, auth, world: World, storage: InMemoryStorage
) -> None:  # type: ignore[no-untyped-def]
    photo = upload(client, auth, world, storage, world.clinic_admin_a, category="cover")
    assert client.delete(url(world, f"/{photo['id']}"), headers=auth(world.dsm_a)).status_code == 403
    assert client.get(url(world), headers=auth(world.clinic_admin_b)).status_code == 404
    assert client.delete(url(world, f"/{photo['id']}"), headers=auth(world.clinic_admin_a)).status_code == 204
    assert (
        client.get(url(world, f"/{photo['id']}/view"), headers=auth(world.clinic_admin_a)).status_code == 404
    )


def test_inactive_link_takes_approved_photos_offline(
    client: TestClient, auth, world: World, storage: InMemoryStorage
) -> None:  # type: ignore[no-untyped-def]
    photo = upload(client, auth, world, storage, world.clinic_admin_a, **slot(world))
    review(client, auth, world, photo["id"], review_state="approved")
    link = f"/api/v1/clinics/{world.clinic_a.id}/clinic-practitioners/{world.practitioner_a.id}"
    assert (
        client.patch(link, json={"is_active": False}, headers=auth(world.clinic_admin_a)).status_code == 200
    )
    states = [p["review_state"] for p in client.get(url(world), headers=auth(world.dsm_a)).json()]
    assert states == ["pending"]  # trigger L4: back to pending (the DSM can approve again if he returns)
