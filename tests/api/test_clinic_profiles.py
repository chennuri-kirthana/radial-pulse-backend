"""Areas E6 + E7: clinic profile and clinic online profiles."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.factories import World, build_world

pytestmark = pytest.mark.integration

EVERYONE = ["admin", "dsm", "clinic_admin", "team_member", "practitioner"]


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


def url(world: World, tail: str) -> str:
    return f"/api/v1/clinics/{world.clinic_a.id}{tail}"


# ------------------------------------------------------------------ clinic profile
@pytest.mark.parametrize("who", EVERYONE)
def test_everyone_of_the_clinic_reads_the_profile(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    r = client.get(url(world, "/clinic-profile"), headers=auth(world.people_a()[who]))
    assert (r.status_code, r.json()["version"], r.json()["brand"]) == (200, 0, {})


def test_versioned_save(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.clinic_admin_a)
    first = client.put(
        url(world, "/clinic-profile"), json={"brand": {"tone": "warm"}, "version": 0}, headers=h
    )
    assert (first.status_code, first.json()["version"]) == (200, 1)
    # a second person who still has version 0 open can't overwrite it
    stale = client.put(
        url(world, "/clinic-profile"),
        json={"brand": {"tone": "cold"}, "version": 0},
        headers=auth(world.dsm_a),
    )
    assert (stale.status_code, stale.json()["code"]) == (409, "state_conflict")
    second = client.put(
        url(world, "/clinic-profile"),
        json={"brand": {"tone": "calm"}, "version": 1},
        headers=auth(world.dsm_a),
    )
    assert (second.json()["version"], second.json()["brand"]) == (2, {"tone": "calm"})


@pytest.mark.parametrize("who", ["team_member", "practitioner"])
def test_read_only_people_cannot_save_the_profile(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    r = client.put(url(world, "/clinic-profile"), json={"version": 0}, headers=auth(world.people_a()[who]))
    assert r.status_code == 403


def test_profile_other_clinic_and_bad_input(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    assert client.get(url(world, "/clinic-profile"), headers=auth(world.clinic_admin_b)).status_code == 404
    h = auth(world.clinic_admin_a)
    assert (
        client.put(url(world, "/clinic-profile"), json={"brand": {}}, headers=h).status_code == 400
    )  # no version
    assert (
        client.put(url(world, "/clinic-profile"), json={"brand": "x", "version": 0}, headers=h).status_code
        == 400
    )


# ------------------------------------------------------------------ online profiles
def test_clinic_admin_adds_and_staff_confirm(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    body = {"platform": "instagram", "url": "HTTP://www.Instagram.com/familydental/"}
    r = client.post(url(world, "/clinic-online-profiles"), json=body, headers=auth(world.clinic_admin_a))
    assert r.status_code == 201, r.text
    added = r.json()
    assert (added["url"], added["verification"], added["discovered_by"]) == (
        "https://instagram.com/familydental",
        "unverified",
        "manual",
    )  # cleaned by the database
    again = client.post(url(world, "/clinic-online-profiles"), json=body, headers=auth(world.dsm_a))
    assert again.status_code == 409  # same cleaned URL

    one = url(world, f"/clinic-online-profiles/{added['id']}")
    assert (
        client.patch(one, json={"verification": "confirmed"}, headers=auth(world.clinic_admin_a)).status_code
        == 403
    )
    r = client.patch(one, json={"verification": "confirmed"}, headers=auth(world.dsm_a))
    assert r.json()["verification"] == "confirmed"
    listed = client.get(
        url(world, "/clinic-online-profiles"), headers=auth(world.practitioner_login_a)
    ).json()
    assert [p["platform"] for p in listed] == ["instagram"]
    assert client.delete(one, headers=auth(world.clinic_admin_a)).status_code == 403
    assert client.delete(one, headers=auth(world.admin)).status_code == 204
    assert client.delete(one, headers=auth(world.admin)).status_code == 404


@pytest.mark.parametrize("who", ["team_member", "practitioner"])
def test_read_only_people_cannot_add_online_profiles(
    client: TestClient, auth, world: World, who: str
) -> None:  # type: ignore[no-untyped-def]
    body = {"platform": "facebook", "url": "https://facebook.com/x"}
    assert (
        client.post(
            url(world, "/clinic-online-profiles"), json=body, headers=auth(world.people_a()[who])
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "body",
    [
        {"platform": "website", "url": "https://x.test"},
        {"platform": "facebook", "url": "ftp://x"},
        {"platform": "facebook"},
    ],
)
def test_online_profile_bad_input(client: TestClient, auth, world: World, body: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
    assert (
        client.post(url(world, "/clinic-online-profiles"), json=body, headers=auth(world.dsm_a)).status_code
        == 400
    )


def test_online_profiles_other_clinic(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    assert client.get(url(world, "/clinic-online-profiles"), headers=auth(world.dsm_b)).status_code == 404
    other = url(world, f"/clinic-online-profiles/{uuid.uuid4()}")
    assert (
        client.patch(other, json={"verification": "rejected"}, headers=auth(world.dsm_a)).status_code == 404
    )
