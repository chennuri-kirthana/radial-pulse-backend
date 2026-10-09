"""Area E1: people (/users, admin only) and my own account (/auth/me...)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import PlatformRole
from app.integrations.storage import ObjectInfo
from app.models import AuditEvent, User
from tests.conftest import FakeIdentityDirectory, InMemoryStorage
from tests.factories import World, build_world, make_user

pytestmark = pytest.mark.integration

NOT_ADMINS = ["dsm", "clinic_admin", "team_member", "practitioner"]


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


def actions(db: Session) -> list[str]:
    return list(db.scalars(select(AuditEvent.action).order_by(AuditEvent.occurred_at)))


# ------------------------------------------------------------------ /users (Platform Administrator)
def test_admin_lists_and_searches_people(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/users", headers=auth(world.admin))
    assert r.status_code == 200
    assert r.json()["total"] == 7  # the world's 7 people
    r = client.get("/api/v1/users", params={"platform_role": "practitioner"}, headers=auth(world.admin))
    assert [u["id"] for u in r.json()["items"]] == [str(world.practitioner_login_a.id)]


@pytest.mark.parametrize("who", NOT_ADMINS)
def test_only_the_admin_manages_people(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.people_a()[who])
    assert client.get("/api/v1/users", headers=h).status_code == 403
    body = {"email": "x@example.test", "platform_role": "clinic_member"}
    assert client.post("/api/v1/users", json=body, headers=h).status_code == 403
    assert (
        client.patch(f"/api/v1/users/{world.admin.id}", json={"full_name": "X"}, headers=h).status_code == 403
    )


def test_admin_invites_a_person(
    client: TestClient, auth, world: World, db: Session, directory: FakeIdentityDirectory
) -> None:  # type: ignore[no-untyped-def]
    body = {
        "email": " New.DSM@Example.test ",
        "full_name": "Ravi",
        "platform_role": "digital_success_manager",
    }
    r = client.post("/api/v1/users", json=body, headers=auth(world.admin))
    assert r.status_code == 201, r.text
    assert (r.json()["email"], r.json()["has_signed_in"]) == ("new.dsm@example.test", False)
    assert [c.email for c in directory.sent] == ["new.dsm@example.test"]
    assert "user.invited" in actions(db)
    again = client.post("/api/v1/users", json=body, headers=auth(world.admin))
    assert (again.status_code, again.json()["code"]) == (409, "state_conflict")


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "platform_role": "clinic_member"},
        {"email": "a@example.test", "platform_role": "receptionist"},
        {"email": "a@example.test", "platform_role": "clinic_member", "extra": 1},
    ],
)
def test_invite_bad_input_is_400(client: TestClient, auth, world: World, body: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
    r = client.post("/api/v1/users", json=body, headers=auth(world.admin))
    assert (r.status_code, r.json()["code"]) == (400, "invalid_request")
    assert r.json()["fields"]


def test_cognito_outage_is_502_and_nothing_is_saved(
    client: TestClient, auth, world: World, db: Session, directory: FakeIdentityDirectory
) -> None:  # type: ignore[no-untyped-def]
    directory.fail = True
    body = {"email": "later@example.test", "platform_role": "clinic_member"}
    assert client.post("/api/v1/users", json=body, headers=auth(world.admin)).status_code == 502
    assert db.scalar(select(User).where(User.email == "later@example.test")) is None


def test_switching_someone_off_blocks_their_sign_in(
    client: TestClient, auth, world: World, directory: FakeIdentityDirectory
) -> None:  # type: ignore[no-untyped-def]
    target = world.clinic_admin_b
    r = client.patch(f"/api/v1/users/{target.id}", json={"is_active": False}, headers=auth(world.admin))
    assert (r.status_code, r.json()["is_active"]) == (200, False)
    assert directory.disabled == [target.email]
    me = client.get("/api/v1/auth/me", headers=auth(target))
    assert (me.status_code, me.json()["code"]) == (403, "account_disabled")


def test_user_changes_the_database_refuses_are_409(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.admin)
    own = client.patch(f"/api/v1/users/{world.admin.id}", json={"is_active": False}, headers=h)
    assert own.status_code == 409
    # still a clinic member: the role can't change (trigger)
    r = client.patch(
        f"/api/v1/users/{world.clinic_admin_a.id}",
        json={"platform_role": "digital_success_manager"},
        headers=h,
    )
    assert (r.status_code, r.json()["code"]) == (409, "state_conflict")
    assert "remove the user's clinic" in r.json()["detail"]
    assert client.patch(f"/api/v1/users/{uuid.uuid4()}", json={"phone": "1"}, headers=h).status_code == 404
    bad = client.patch(f"/api/v1/users/{world.dsm_a.id}", json={"is_active": None}, headers=h)
    assert bad.status_code == 400


def test_resend_invite(
    client: TestClient, auth, world: World, db: Session, directory: FakeIdentityDirectory
) -> None:  # type: ignore[no-untyped-def]
    invited = make_user(db, PlatformRole.CLINIC_MEMBER, linked=False)
    db.commit()
    directory.subs[invited.email] = "cognito-sub-of-the-invite"  # invited before, not signed in yet
    h = auth(world.admin)
    assert client.post(f"/api/v1/users/{invited.id}/resend-invite", headers=h).status_code == 204
    assert directory.sent[-1].resend is True
    assert client.post(f"/api/v1/users/{world.dsm_a.id}/resend-invite", headers=h).status_code == 409


# ------------------------------------------------------------------ /auth/me (everyone)
@pytest.mark.parametrize("who", ["admin", *NOT_ADMINS])
def test_everyone_edits_their_own_profile(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    r = client.patch("/api/v1/auth/me", json={"full_name": "New Name"}, headers=auth(world.people_a()[who]))
    assert (r.status_code, r.json()["full_name"]) == (200, "New Name")


def test_profile_bad_input(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.dsm_a)
    assert client.patch("/api/v1/auth/me", json={"full_name": "x" * 201}, headers=h).status_code == 400
    assert (
        client.patch("/api/v1/auth/me", json={"email": "a@b.test"}, headers=h).status_code == 400
    )  # not mine to change


def test_profile_photo_upload_confirm_view_remove(
    client: TestClient, auth, world: World, db: Session, storage: InMemoryStorage
) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.team_member_a)
    t = client.post(
        "/api/v1/auth/me/avatar/uploads", json={"content_type": "image/png", "size_bytes": 1000}, headers=h
    )
    assert t.status_code == 200
    key = t.json()["key"]
    assert key.startswith(f"users/{world.team_member_a.id}/avatar/")
    assert storage.signed_lengths[key] == 1000
    confirm = {"key": key, "content_type": "image/png", "size_bytes": 1000}
    assert (
        client.post("/api/v1/auth/me/avatar/confirm", json=confirm, headers=h).status_code == 400
    )  # not uploaded
    storage.objects[key] = ObjectInfo(size_bytes=1000, content_type="image/png", etag="e")
    assert client.post("/api/v1/auth/me/avatar/confirm", json=confirm, headers=h).status_code == 204
    me = client.get("/api/v1/auth/me", headers=h).json()
    assert me["avatar_url"] and "user.avatar_viewed" in actions(db)
    assert client.delete("/api/v1/auth/me/avatar", headers=h).status_code == 204
    assert client.get("/api/v1/auth/me", headers=h).json()["avatar_url"] is None


def test_profile_photo_rules(client: TestClient, auth, world: World, storage: InMemoryStorage) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.team_member_a)
    up = "/api/v1/auth/me/avatar/uploads"
    assert client.post(up, json={"content_type": "image/gif", "size_bytes": 10}, headers=h).status_code == 400
    assert (
        client.post(up, json={"content_type": "image/png", "size_bytes": 6_000_000}, headers=h).status_code
        == 400
    )
    someone_else = f"users/{world.dsm_a.id}/avatar/x.png"
    storage.objects[someone_else] = ObjectInfo(size_bytes=10, content_type="image/png", etag="e")
    r = client.post(
        "/api/v1/auth/me/avatar/confirm",
        json={"key": someone_else, "content_type": "image/png", "size_bytes": 10},
        headers=h,
    )
    assert r.status_code == 400


def test_notification_preferences_are_mine_only(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    url = "/api/v1/auth/me/notification-preferences"
    mine = client.get(url, headers=auth(world.dsm_a)).json()
    assert len(mine) == 8 and all(p["is_enabled"] for p in mine)
    change = {"items": [{"category": "portfolio_allocated", "channel": "email", "is_enabled": False}]}
    after = client.put(url, json=change, headers=auth(world.dsm_a)).json()
    off = [(p["category"], p["channel"]) for p in after if not p["is_enabled"]]
    assert off == [("portfolio_allocated", "email")]
    others = client.get(url, headers=auth(world.dsm_b)).json()
    assert all(p["is_enabled"] for p in others)
    bad = {"items": [{"category": "clinic_assigned", "channel": "email", "is_enabled": False}]}
    assert client.put(url, json=bad, headers=auth(world.dsm_a)).status_code == 400
