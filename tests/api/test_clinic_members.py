"""Area E4: clinic members (docs/01 section 4, docs/02)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import PlatformRole
from app.models import AuditEvent, ClinicMember, User
from tests.conftest import FakeIdentityDirectory
from tests.factories import World, build_world, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


def url(world: World, tail: str = "") -> str:
    return f"/api/v1/clinics/{world.clinic_a.id}/clinic-members{tail}"


@pytest.mark.parametrize("who", ["admin", "dsm", "clinic_admin", "team_member"])
def test_team_list(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    r = client.get(url(world), headers=auth(world.people_a()[who]))
    assert r.status_code == 200
    assert {m["role"] for m in r.json()} == {"clinic_administrator", "clinic_team_member"}


def test_practitioner_does_not_see_the_team_and_others_get_404(
    client: TestClient, auth, world: World
) -> None:  # type: ignore[no-untyped-def]
    assert client.get(url(world), headers=auth(world.practitioner_login_a)).status_code == 403
    assert client.get(url(world), headers=auth(world.clinic_admin_b)).status_code == 404


@pytest.mark.parametrize("who", ["admin", "dsm", "clinic_admin"])
def test_adding_a_new_person_invites_them(
    client: TestClient, auth, world: World, db: Session, directory: FakeIdentityDirectory, who: str
) -> None:  # type: ignore[no-untyped-def]
    body = {"email": "Front.Desk@Example.test", "full_name": "Asha", "role": "clinic_team_member"}
    r = client.post(url(world), json=body, headers=auth(world.people_a()[who]))
    assert r.status_code == 201, r.text
    assert (r.json()["email"], r.json()["has_signed_in"]) == ("front.desk@example.test", False)
    assert [c.email for c in directory.sent] == ["front.desk@example.test"]
    user = db.scalar(select(User).where(User.email == "front.desk@example.test"))
    assert user is not None and user.platform_role == "clinic_member"
    actions = set(db.scalars(select(AuditEvent.action)))
    assert {"user.invited", "clinic_member.added"} <= actions
    # the new person signs in later and sees the clinic
    assert (
        client.post(url(world), json=body, headers=auth(world.admin)).status_code == 409
    )  # already a member


def test_existing_clinic_member_login_is_linked_not_invited(
    client: TestClient, auth, world: World, directory: FakeIdentityDirectory
) -> None:  # type: ignore[no-untyped-def]
    body = {"email": world.clinic_admin_b.email, "role": "clinic_administrator"}
    r = client.post(url(world), json=body, headers=auth(world.admin))
    assert r.status_code == 201
    assert directory.sent == []
    me = client.get("/api/v1/auth/me", headers=auth(world.clinic_admin_b)).json()
    assert len(me["clinics"]) == 2


@pytest.mark.parametrize("who", ["team_member", "practitioner"])
def test_team_members_and_practitioners_cannot_add_people(
    client: TestClient, auth, world: World, who: str
) -> None:  # type: ignore[no-untyped-def]
    body = {"email": "x@example.test", "role": "clinic_team_member"}
    assert client.post(url(world), json=body, headers=auth(world.people_a()[who])).status_code == 403


def test_add_member_errors(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.admin)
    assert (
        client.post(url(world), json={"email": "x@example.test", "role": "owner"}, headers=h).status_code
        == 400
    )
    assert (
        client.post(url(world), json={"email": "nope", "role": "clinic_team_member"}, headers=h).status_code
        == 400
    )
    # a practitioner's login can never be a clinic member (trigger)
    r = client.post(
        url(world), json={"email": world.practitioner_login_a.email, "role": "clinic_team_member"}, headers=h
    )
    assert (r.status_code, r.json()["code"]) == (409, "state_conflict")
    other = f"/api/v1/clinics/{world.clinic_b.id}/clinic-members"
    assert (
        client.post(
            other,
            json={"email": "x@example.test", "role": "clinic_team_member"},
            headers=auth(world.clinic_admin_a),
        ).status_code
        == 404
    )


def test_role_change_and_last_admin_rule(client: TestClient, auth, world: World, db: Session) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.clinic_admin_a)
    tm = url(world, f"/{world.team_member_a.id}")
    r = client.patch(tm, json={"role": "clinic_administrator"}, headers=h)
    assert (r.status_code, r.json()["role"]) == (200, "clinic_administrator")
    # two admins now: one may step down
    assert (
        client.patch(
            url(world, f"/{world.clinic_admin_a.id}"), json={"is_active": False}, headers=h
        ).status_code
        == 200
    )
    # the last active admin can't be switched off (trigger)
    last = client.patch(tm, json={"is_active": False}, headers=auth(world.dsm_a))
    assert (last.status_code, last.json()["code"]) == (409, "state_conflict")
    assert "at least one active Clinic Administrator" in last.json()["detail"]
    assert db.get(ClinicMember, (world.clinic_a.id, world.team_member_a.id)).is_active  # type: ignore[union-attr]


def test_update_errors(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.clinic_admin_a)
    assert (
        client.patch(url(world, f"/{uuid.uuid4()}"), json={"is_active": False}, headers=h).status_code == 404
    )
    assert (
        client.patch(url(world, f"/{world.team_member_a.id}"), json={"role": None}, headers=h).status_code
        == 400
    )
    assert (
        client.patch(
            url(world, f"/{world.team_member_a.id}"),
            json={"is_active": False},
            headers=auth(world.team_member_a),
        ).status_code
        == 403
    )


def test_resend_invite_for_a_member(
    client: TestClient, auth, world: World, db: Session, directory: FakeIdentityDirectory
) -> None:  # type: ignore[no-untyped-def]
    invited = make_user(db, PlatformRole.CLINIC_MEMBER, linked=False)
    db.add(ClinicMember(clinic_id=world.clinic_a.id, user_id=invited.id, role="clinic_team_member"))
    db.commit()
    directory.subs[invited.email] = "sub-from-the-first-invite"
    h = auth(world.clinic_admin_a)
    assert client.post(url(world, f"/{invited.id}/resend-invite"), headers=h).status_code == 204
    assert client.post(url(world, f"/{world.team_member_a.id}/resend-invite"), headers=h).status_code == 409
