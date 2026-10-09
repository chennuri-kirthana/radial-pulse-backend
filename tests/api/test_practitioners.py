"""Area E5: practitioners: the shared record and each clinic's link (docs/01 sections 5 + 14)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import PlatformRole
from app.models import AuditEvent
from tests.factories import World, build_world, make_practitioner, make_user

pytestmark = pytest.mark.integration

GOOD_HOURS = {
    "mon": [{"from": "10:00", "to": "14:00"}],
    "fri": [{"from": "10:00", "to": "13:00"}, {"from": "17:00", "to": "20:00"}],
    "sun": [],
}


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


def links(world: World, tail: str = "") -> str:
    return f"/api/v1/clinics/{world.clinic_a.id}/clinic-practitioners{tail}"


def link_url(world: World) -> str:
    return links(world, f"/{world.practitioner_a.id}")


def record(world: World) -> str:
    return f"/api/v1/practitioners/{world.practitioner_a.id}"


# ------------------------------------------------------------------ clinic links: read
@pytest.mark.parametrize("who", ["admin", "dsm", "clinic_admin", "team_member", "practitioner"])
def test_everyone_of_the_clinic_sees_its_practitioners(
    client: TestClient, auth, world: World, who: str
) -> None:  # type: ignore[no-untyped-def]
    r = client.get(links(world), headers=auth(world.people_a()[who]))
    assert r.status_code == 200
    assert [p["practitioner"]["full_name"] for p in r.json()] == ["Dr. Pooja Shah"]


def test_other_clinic_is_404(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    assert client.get(links(world), headers=auth(world.clinic_admin_b)).status_code == 404
    assert (
        client.get(record(world), headers=auth(world.clinic_admin_b)).status_code == 404
    )  # shared record hidden too


# ------------------------------------------------------------------ lookup + link (no duplicates)
def test_lookup_then_link_an_existing_practitioner(
    client: TestClient, auth, world: World, db: Session
) -> None:  # type: ignore[no-untyped-def]
    elsewhere = make_practitioner(db, world.clinic_b, full_name="Dr. Mehta", registration_number="KA-1234")
    db.commit()
    h = auth(world.clinic_admin_a)
    found = client.get(links(world, "/lookup"), params={"registration_number": " ka-1234 "}, headers=h)
    assert found.json() == {"id": str(elsewhere.id), "full_name": "Dr. Mehta", "specialty": None}
    assert (
        client.get(links(world, "/lookup"), params={"registration_number": "NOPE"}, headers=h).json() is None
    )

    r = client.post(
        links(world), json={"practitioner_id": str(elsewhere.id), "designation": "Visiting"}, headers=h
    )
    assert r.status_code == 201, r.text
    assert (r.json()["designation"], r.json()["consultation_time_zone"]) == ("Visiting", "Asia/Kolkata")
    assert client.get(f"/api/v1/practitioners/{elsewhere.id}", headers=h).status_code == 200  # now visible
    assert (
        client.post(links(world), json={"practitioner_id": str(elsewhere.id)}, headers=h).status_code == 409
    )


def test_create_a_new_practitioner(client: TestClient, auth, world: World, db: Session) -> None:  # type: ignore[no-untyped-def]
    body = {
        "practitioner": {
            "full_name": "Dr. Rao",
            "registration_number": " mh-77 ",
            "practice_start_year": 2011,
        }
    }
    r = client.post(links(world), json=body, headers=auth(world.clinic_admin_a))
    assert r.status_code == 201, r.text
    p = r.json()["practitioner"]
    assert (p["registration_number"], p["years_of_experience"]) == ("MH-77", datetime.now(UTC).year - 2011)
    assert {"practitioner.created", "clinic_practitioner.linked"} <= set(
        db.scalars(select(AuditEvent.action))
    )
    again = client.post(links(world), json=body, headers=auth(world.dsm_a))
    assert (again.status_code, again.json()["code"]) == (409, "state_conflict")  # same registration number


@pytest.mark.parametrize("who", ["team_member", "practitioner"])
def test_only_admin_dsm_clinic_admin_link(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.people_a()[who])
    assert client.post(links(world), json={"practitioner": {"full_name": "X"}}, headers=h).status_code == 403
    assert (
        client.get(links(world, "/lookup"), params={"registration_number": "X"}, headers=h).status_code == 403
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"practitioner_id": "00000000-0000-0000-0000-000000000000", "practitioner": {"full_name": "X"}},
        {"practitioner": {"full_name": ""}},
    ],
)
def test_link_bad_input(client: TestClient, auth, world: World, body: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
    assert client.post(links(world), json=body, headers=auth(world.clinic_admin_a)).status_code == 400


# ------------------------------------------------------------------ clinic link fields
def test_clinic_admin_sets_schedule_fee_holiday(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    body = {
        "consultation_hours": GOOD_HOURS,
        "weekly_off_days": ["sun", "sun"],
        "consultation_fee": "500",
        "consultation_fee_currency": "inr",
        "consultation_time_zone": "Asia/Kolkata",
        "schedule_notes": "Emergency on call",
    }
    r = client.patch(link_url(world), json=body, headers=auth(world.clinic_admin_a))
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["weekly_off_days"], got["consultation_fee"], got["consultation_fee_currency"]) == (
        ["sun"],
        "500.00",
        "INR",
    )
    assert got["consultation_hours"]["fri"][1] == {"from": "17:00", "to": "20:00"}


@pytest.mark.parametrize(
    "body",
    [
        {"consultation_hours": {"monday": []}},
        {"consultation_hours": {"mon": [{"from": "14:00", "to": "10:00"}]}},
        {"consultation_hours": {"mon": [{"from": "25:00", "to": "26:00"}]}},
        {"consultation_hours": {"mon": [{"from": "10:00", "to": "11:00", "note": "x"}]}},
        {"consultation_hours": {"mon": {"from": "10:00", "to": "11:00"}}},
        {"consultation_hours": None},
        {"consultation_time_zone": "Mars/Olympus"},
        {"consultation_fee": -1},
        {"consultation_fee_currency": "RUPEE"},
        {"weekly_off_days": ["holiday"]},
    ],
)
def test_link_fields_bad_input_is_400(client: TestClient, auth, world: World, body: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
    r = client.patch(link_url(world), json=body, headers=auth(world.clinic_admin_a))
    assert (r.status_code, r.json()["code"]) == (400, "invalid_request")


@pytest.mark.parametrize("who", ["team_member", "practitioner"])
def test_practitioner_and_team_member_cannot_change_link_fields(
    client: TestClient, auth, world: World, who: str
) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(link_url(world), json={"consultation_fee": 900}, headers=auth(world.people_a()[who]))
    assert r.status_code == 403


def test_one_primary_practitioner_per_clinic(client: TestClient, auth, world: World, db: Session) -> None:  # type: ignore[no-untyped-def]
    second = make_practitioner(db, world.clinic_a, full_name="Dr. Second")
    db.commit()
    h = auth(world.dsm_a)
    assert client.patch(link_url(world), json={"is_primary": True}, headers=h).json()["is_primary"] is True
    client.patch(links(world, f"/{second.id}"), json={"is_primary": True}, headers=h)
    listed = client.get(links(world), headers=h).json()
    assert [(p["practitioner"]["full_name"], p["is_primary"]) for p in listed] == [
        ("Dr. Second", True),
        ("Dr. Pooja Shah", False),
    ]


# ------------------------------------------------------------------ shared record
def test_practitioner_edits_his_own_record(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.practitioner_login_a)
    body = {"bio": "Smiles", "services_and_conditions": ["Root canal", "Braces"], "practice_start_year": 2011}
    r = client.patch(record(world), json=body, headers=h)
    assert (r.status_code, r.json()["services_and_conditions"]) == (200, ["Root canal", "Braces"])
    assert r.json()["years_of_experience"] == datetime.now(UTC).year - 2011
    assert (
        client.patch(record(world), json={"full_name": "Dr. P"}, headers=h).status_code == 403
    )  # staff only


def test_clinic_admin_cannot_edit_the_shared_record(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(record(world), json={"bio": "x"}, headers=auth(world.clinic_admin_a))
    assert r.status_code == 403
    assert (
        client.patch(record(world), json={"bio": "x"}, headers=auth(world.team_member_a)).status_code == 403
    )


@pytest.mark.parametrize("who", ["admin", "dsm"])
def test_staff_edit_name_and_registration(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(
        record(world),
        json={"full_name": "Dr. Pooja S. Shah", "registration_number": "gj-9"},
        headers=auth(world.people_a()[who]),
    )
    assert (r.status_code, r.json()["registration_number"]) == (200, "GJ-9")


@pytest.mark.parametrize(
    "body",
    [
        {"practice_start_year": datetime.now(UTC).year + 1},
        {"practice_start_year": 1900},
        {"services_and_conditions": [""]},
        {"services_and_conditions": None},
        {"approx_patients_treated": -5},
        {"full_name": None},
    ],
)
def test_record_bad_input_is_400(client: TestClient, auth, world: World, body: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
    assert client.patch(record(world), json=body, headers=auth(world.dsm_a)).status_code == 400


def test_linking_the_practitioner_login(client: TestClient, auth, world: World, db: Session) -> None:  # type: ignore[no-untyped-def]
    other = make_practitioner(db, world.clinic_a, full_name="Dr. Login")
    login = make_user(db, PlatformRole.PRACTITIONER)
    db.commit()
    url = f"/api/v1/practitioners/{other.id}"
    wrong = client.patch(url, json={"user_id": str(world.clinic_admin_a.id)}, headers=auth(world.dsm_a))
    assert (wrong.status_code, wrong.json()["code"]) == (409, "state_conflict")  # not a practitioner login
    assert client.patch(url, json={"user_id": str(login.id)}, headers=auth(world.dsm_a)).status_code == 200
    me = client.get("/api/v1/auth/me", headers=auth(login)).json()
    assert (me["practitioner_id"], [c["clinic_id"] for c in me["clinics"]]) == (
        str(other.id),
        [str(world.clinic_a.id)],
    )
