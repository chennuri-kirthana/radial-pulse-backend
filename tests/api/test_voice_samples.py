"""Area E13: voice samples (docs/01-decisions.md section 7)."""

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

TITLE_USED = "This title is already used. Please give another title."


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


def url(world: World, tail: str = "") -> str:
    return f"/api/v1/clinics/{world.clinic_a.id}/voice-samples{tail}"


def upload(
    client: TestClient,
    auth,
    world: World,
    storage: InMemoryStorage,
    user: Any,
    title: str,
    practitioner_id: Any = None,
) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    body = {
        "practitioner_id": str(practitioner_id or world.practitioner_a.id),
        "title": title,
        "content_type": "audio/mp4",
        "size_bytes": 4000,
    }
    r = client.post(url(world, "/uploads"), json=body, headers=auth(user))
    assert r.status_code == 201, r.text
    key = r.json()["upload"]["key"]
    assert key.startswith(f"clinics/{world.clinic_a.id}/voice/")
    storage.objects[key] = ObjectInfo(size_bytes=4000, content_type="audio/mp4", etag="e")
    done = client.post(url(world, f"/{r.json()['voice_sample']['id']}/complete"), headers=auth(user))
    assert done.status_code == 200
    return done.json()  # type: ignore[no-any-return]


@pytest.mark.parametrize("who", ["clinic_admin", "practitioner"])
def test_clinic_admin_and_the_practitioner_upload(
    client: TestClient, auth, world: World, storage: InMemoryStorage, who: str
) -> None:  # type: ignore[no-untyped-def]
    sample = upload(client, auth, world, storage, world.people_a()[who], "Clinic greeting")
    assert (sample["processing_status"], sample["title"]) == ("ready", "Clinic greeting")


def test_title_cannot_be_reused(client: TestClient, auth, world: World, storage: InMemoryStorage) -> None:  # type: ignore[no-untyped-def]
    upload(client, auth, world, storage, world.clinic_admin_a, "Reading sample 1")
    body = {
        "practitioner_id": str(world.practitioner_a.id),
        "title": "READING SAMPLE 1",
        "content_type": "audio/mpeg",
        "size_bytes": 10,
    }
    r = client.post(url(world, "/uploads"), json=body, headers=auth(world.practitioner_login_a))
    assert (r.status_code, r.json()["code"], r.json()["detail"]) == (409, "state_conflict", TITLE_USED)


def test_who_sees_which_recordings(
    client: TestClient, auth, world: World, storage: InMemoryStorage, db: Session
) -> None:  # type: ignore[no-untyped-def]
    colleague = make_practitioner(db, world.clinic_a, full_name="Dr. Other")
    db.commit()
    mine = upload(client, auth, world, storage, world.clinic_admin_a, "Mine")
    upload(client, auth, world, storage, world.clinic_admin_a, "Theirs", colleague.id)
    for who in ["admin", "dsm", "clinic_admin"]:
        assert len(client.get(url(world), headers=auth(world.people_a()[who])).json()) == 2
    own = client.get(url(world), headers=auth(world.practitioner_login_a)).json()
    assert [s["id"] for s in own] == [mine["id"]]
    assert client.get(url(world), headers=auth(world.team_member_a)).status_code == 403
    assert client.get(url(world), headers=auth(world.clinic_admin_b)).status_code == 404


@pytest.mark.parametrize("who", ["admin", "dsm", "team_member"])
def test_staff_and_team_members_never_upload(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    body = {
        "practitioner_id": str(world.practitioner_a.id),
        "title": "X",
        "content_type": "audio/mpeg",
        "size_bytes": 10,
    }
    assert (
        client.post(url(world, "/uploads"), json=body, headers=auth(world.people_a()[who])).status_code == 403
    )


def test_practitioner_cannot_upload_for_a_colleague(
    client: TestClient, auth, world: World, db: Session
) -> None:  # type: ignore[no-untyped-def]
    colleague = make_practitioner(db, world.clinic_a, full_name="Dr. Other")
    db.commit()
    body = {
        "practitioner_id": str(colleague.id),
        "title": "X",
        "content_type": "audio/mpeg",
        "size_bytes": 10,
    }
    assert (
        client.post(url(world, "/uploads"), json=body, headers=auth(world.practitioner_login_a)).status_code
        == 403
    )


@pytest.mark.parametrize(
    "body",
    [
        {"title": "X", "content_type": "video/mp4", "size_bytes": 10},
        {"title": "", "content_type": "audio/mpeg", "size_bytes": 10},
        {"title": "X", "content_type": "audio/mpeg", "size_bytes": 60_000_000},
        {"title": "X" * 121, "content_type": "audio/mpeg", "size_bytes": 10},
    ],
)
def test_upload_bad_input(client: TestClient, auth, world: World, body: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
    full = {"practitioner_id": str(world.practitioner_a.id), **body}
    assert (
        client.post(url(world, "/uploads"), json=full, headers=auth(world.clinic_admin_a)).status_code == 400
    )


def test_rename_view_and_delete(
    client: TestClient, auth, world: World, storage: InMemoryStorage, db: Session
) -> None:  # type: ignore[no-untyped-def]
    a = upload(client, auth, world, storage, world.clinic_admin_a, "First")
    upload(client, auth, world, storage, world.clinic_admin_a, "Second")
    h = auth(world.practitioner_login_a)
    clash = client.patch(url(world, f"/{a['id']}"), json={"title": "second"}, headers=h)
    assert (clash.status_code, clash.json()["detail"]) == (409, TITLE_USED)
    assert (
        client.patch(url(world, f"/{a['id']}"), json={"title": "Greeting"}, headers=h).json()["title"]
        == "Greeting"
    )
    assert client.get(url(world, f"/{a['id']}/view"), headers=auth(world.dsm_a)).status_code == 200
    assert (
        db.scalar(select(AuditEvent.actor_user_id).where(AuditEvent.action == "voice_sample.viewed"))
        == world.dsm_a.id
    )
    assert client.delete(url(world, f"/{a['id']}"), headers=auth(world.dsm_a)).status_code == 403
    assert client.delete(url(world, f"/{a['id']}"), headers=h).status_code == 204
