"""Area E14: connected accounts: list, disconnect, choose a location (docs/01 section 11).

Starting a new "Connect" (OAuth) waits for open question Q3, so tests add accounts directly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Clinic, ConnectedAccount, ConnectedAccountResource
from tests.conftest import InMemorySecretStore
from tests.factories import World, build_world

pytestmark = pytest.mark.integration

SECRET = "arn:aws:secretsmanager:ap-south-1:000000000000:secret:radial-pulse/test/connections/x"


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


def connect(
    db: Session, clinic: Clinic, location_id: str = "locations/1"
) -> tuple[ConnectedAccount, ConnectedAccountResource]:
    account = ConnectedAccount(
        clinic_id=clinic.id,
        provider="google",
        external_account_id=f"acct-{clinic.id}",
        secret_ref=SECRET,
        scopes=["s"],
    )
    db.add(account)
    db.flush()
    resource = ConnectedAccountResource(
        connected_account_id=account.id,
        clinic_id=clinic.id,
        resource_type="gbp_location",
        external_id=location_id,
    )
    db.add(resource)
    db.commit()
    return account, resource


def url(world: World, tail: str = "") -> str:
    return f"/api/v1/clinics/{world.clinic_a.id}/connected-accounts{tail}"


@pytest.mark.parametrize("who", ["admin", "dsm", "clinic_admin", "team_member"])
def test_who_sees_connected_accounts(client: TestClient, auth, world: World, db: Session, who: str) -> None:  # type: ignore[no-untyped-def]
    connect(db, world.clinic_a)
    r = client.get(url(world), headers=auth(world.people_a()[who]))
    assert r.status_code == 200
    assert [a["provider"] for a in r.json()] == ["google"]
    assert "secret_ref" not in r.json()[0]  # never returned


def test_practitioner_and_other_clinic(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    assert client.get(url(world), headers=auth(world.practitioner_login_a)).status_code == 403
    assert client.get(url(world), headers=auth(world.clinic_admin_b)).status_code == 404


def test_providers_list(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    got = {
        p["provider"]: p["available"]
        for p in client.get(url(world, "/providers"), headers=auth(world.dsm_a)).json()
    }
    assert got == {"google": True, "instagram": True, "facebook": True, "linkedin": False, "x": False}


def test_disconnect_removes_the_token(
    client: TestClient, auth, world: World, db: Session, secret_store: InMemorySecretStore
) -> None:  # type: ignore[no-untyped-def]
    account, resource = connect(db, world.clinic_a)
    h = auth(world.clinic_admin_a)
    client.put(url(world, f"/{account.id}/resources/{resource.id}"), json={"is_selected": True}, headers=h)
    r = client.post(url(world, f"/{account.id}/disconnect"), headers=h)
    assert (r.status_code, r.json()["status"]) == (200, "disconnected")
    assert secret_store.deleted == [SECRET]
    db.expire_all()
    assert db.get(ConnectedAccount, account.id).secret_ref is None  # type: ignore[union-attr]
    assert db.get(ConnectedAccountResource, resource.id).is_selected is False  # type: ignore[union-attr]
    assert client.post(url(world, f"/{account.id}/disconnect"), headers=h).status_code == 409


@pytest.mark.parametrize("who", ["team_member", "practitioner"])
def test_read_only_people_cannot_disconnect(
    client: TestClient, auth, world: World, db: Session, who: str
) -> None:  # type: ignore[no-untyped-def]
    account, _ = connect(db, world.clinic_a)
    assert (
        client.post(url(world, f"/{account.id}/disconnect"), headers=auth(world.people_a()[who])).status_code
        == 403
    )


def test_a_location_belongs_to_one_clinic(client: TestClient, auth, world: World, db: Session) -> None:  # type: ignore[no-untyped-def]
    a_account, a_location = connect(db, world.clinic_a, "locations/shared")
    b_account, b_location = connect(db, world.clinic_b, "locations/shared")  # same login, both clinics
    ok = client.put(
        url(world, f"/{a_account.id}/resources/{a_location.id}"),
        json={"is_selected": True},
        headers=auth(world.clinic_admin_a),
    )
    assert (ok.status_code, ok.json()["is_selected"]) == (200, True)
    other = f"/api/v1/clinics/{world.clinic_b.id}/connected-accounts/{b_account.id}/resources/{b_location.id}"
    taken = client.put(other, json={"is_selected": True}, headers=auth(world.clinic_admin_b))
    assert (taken.status_code, taken.json()["code"]) == (409, "state_conflict")


def test_resource_errors(client: TestClient, auth, world: World, db: Session) -> None:  # type: ignore[no-untyped-def]
    a_account, a_location = connect(db, world.clinic_a)
    _, b_location = connect(db, world.clinic_b, "locations/b")
    h = auth(world.clinic_admin_a)
    assert (
        client.put(
            url(world, f"/{a_account.id}/resources/{b_location.id}"), json={"is_selected": True}, headers=h
        ).status_code
        == 404
    )
    assert (
        client.put(
            url(world, f"/{a_account.id}/resources/{a_location.id}"), json={"is_selected": "maybe"}, headers=h
        ).status_code
        == 400
    )
    listed = client.get(url(world, f"/{a_account.id}/resources"), headers=auth(world.team_member_a)).json()
    assert [r["external_id"] for r in listed] == ["locations/1"]
