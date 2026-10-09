"""Step F: the Practitioner Profile screen, checked against db/seed-family-dental-v15.sql (prompts Step F)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from tests.factories import build_world

pytestmark = pytest.mark.integration

SEED = Path(__file__).resolve().parents[2] / "db" / "seed-family-dental-v15.sql"
CLINIC = "00000000-0000-0000-0000-00000000cc01"
POOJA_RECORD = "00000000-0000-0000-0000-00000000dd01"
URL = f"/api/v1/clinics/{CLINIC}/practitioner-profile"
SUBS = {"anil": "sub-anil", "ravi": "sub-ravi", "mehul": "sub-mehul", "pooja": "sub-pooja"}


@pytest.fixture
def seeded(engines: tuple[Engine, Engine]) -> Iterator[None]:
    """The Family Dental scenario, loaded as the table owner (psql lines left out)."""
    sql = "\n".join(
        line for line in SEED.read_text(encoding="utf-8").splitlines() if not line.startswith("\\")
    )
    raw = engines[0].raw_connection()
    driver = raw.driver_connection
    try:
        driver.autocommit = True  # type: ignore[union-attr]  # the seed has its own BEGIN / COMMIT
        driver.execute(sql.encode())  # type: ignore[union-attr]
    finally:
        driver.autocommit = False  # type: ignore[union-attr]  # back to normal before it returns to the pool
        raw.close()
    yield


def as_(make_token, who: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {"Authorization": f"Bearer {make_token(SUBS[who])}"}


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize("who", ["anil", "ravi", "mehul", "pooja"])
def test_the_screen_shows_the_seed_values(client: TestClient, make_token, who: str) -> None:  # type: ignore[no-untyped-def]
    r = client.get(URL, headers=as_(make_token, who))
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["full_name"], p["specialty"], p["qualifications"]) == (
        "Dr. Pooja Shah",
        "Family Dentistry",
        "BDS, FAGE",
    )
    assert (p["practice_start_year"], p["years_of_experience"]) == (2011, datetime.now(UTC).year - 2011)
    org = p["client_organization_information"]
    assert (org["name"], org["established_year"]) == ("Family Dental Clinic", 2008)
    assert (org["address_line"], org["city"], org["state"], org["postal_code"]) == (
        "12 CG Road",
        "Ahmedabad",
        "Gujarat",
        "380009",
    )
    days = {d["day"]: d["slots"] for d in p["consultation_schedule"]}
    assert [d["day"] for d in p["consultation_schedule"]] == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    for day in ("mon", "tue", "wed", "thu"):
        assert days[day] == [{"from": "10:00", "to": "14:00"}]
    assert days["fri"] == [{"from": "10:00", "to": "14:00"}, {"from": "17:00", "to": "19:00"}]
    assert days["sat"] == [{"from": "10:00", "to": "13:00"}]
    assert days["sun"] == []  # "No consultation"
    assert (p["consultation_time_zone"], p["weekly_off_days"]) == ("Asia/Kolkata", ["sun"])
    assert (p["consultation_fee"], p["consultation_fee_currency"]) == ("500.00", "INR")
    assert len(p["services_and_conditions"]) == 4
    assert (p["approx_patients_treated"], p["highlights"].startswith("Gujarat Dental Council")) == (
        12000,
        True,
    )


@pytest.mark.usefixtures("seeded")
def test_empty_values_come_back_as_null(client: TestClient, make_token) -> None:  # type: ignore[no-untyped-def]
    body = {
        "practitioner": {"highlights": None, "services_and_conditions": []},
        "clinic_practitioner": {"schedule_notes": None},
    }
    r = client.patch(f"{URL}/{POOJA_RECORD}", json=body, headers=as_(make_token, "ravi"))
    assert r.status_code == 200, r.text
    assert (r.json()["highlights"], r.json()["services_and_conditions"], r.json()["schedule_notes"]) == (
        None,
        None,
        None,
    )


@pytest.mark.usefixtures("seeded")
def test_who_edits_which_part(client: TestClient, make_token) -> None:  # type: ignore[no-untyped-def]
    fee = {"clinic_practitioner": {"consultation_fee": 600}}
    bio = {"practitioner": {"bio": "Gentle care"}}
    # the practitioner edits her own record, but not the clinic's fee
    assert (
        client.patch(f"{URL}/{POOJA_RECORD}", json=bio, headers=as_(make_token, "pooja")).json()["bio"]
        == "Gentle care"
    )
    assert (
        client.patch(f"{URL}/{POOJA_RECORD}", json=fee, headers=as_(make_token, "pooja")).status_code == 403
    )
    # the Clinic Administrator edits the clinic's details, but not the shared record
    assert (
        client.patch(f"{URL}/{POOJA_RECORD}", json=fee, headers=as_(make_token, "mehul")).json()[
            "consultation_fee"
        ]
        == "600.00"
    )
    assert (
        client.patch(f"{URL}/{POOJA_RECORD}", json=bio, headers=as_(make_token, "mehul")).status_code == 403
    )
    # name: staff only
    name = {"practitioner": {"full_name": "Dr. P. Shah"}}
    assert (
        client.patch(f"{URL}/{POOJA_RECORD}", json=name, headers=as_(make_token, "pooja")).status_code == 403
    )
    assert (
        client.patch(f"{URL}/{POOJA_RECORD}", json=name, headers=as_(make_token, "ravi")).status_code == 200
    )


BAD: list[dict[str, Any]] = [
    {"clinic_practitioner": {"consultation_hours": {"mon": [{"from": "10", "to": "14:00"}]}}},  # HH:MM
    {"clinic_practitioner": {"consultation_hours": {"mon": [{"from": "14:00", "to": "10:00"}]}}},  # from < to
    {"clinic_practitioner": {"consultation_hours": {"funday": []}}},  # weekday
    {"clinic_practitioner": {"consultation_hours": {"mon": "10-14"}}},  # shape
    {"clinic_practitioner": {"weekly_off_days": ["sunday"]}},
    {"clinic_practitioner": {"consultation_fee": -1}},
    {"clinic_practitioner": {"consultation_fee_currency": "RS"}},
    {"clinic_practitioner": {"consultation_time_zone": "India/Ahmedabad"}},
    {"practitioner": {"practice_start_year": datetime.now(UTC).year + 1}},
]


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize("body", BAD)
def test_each_rule_is_refused_with_400(client: TestClient, make_token, body: dict[str, Any]) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(f"{URL}/{POOJA_RECORD}", json=body, headers=as_(make_token, "ravi"))
    assert (r.status_code, r.json()["code"]) == (400, "invalid_request")
    assert r.json()["fields"]


@pytest.mark.usefixtures("seeded")
def test_other_clinic_is_404(client: TestClient, auth, db: Session) -> None:  # type: ignore[no-untyped-def]
    outsider = build_world(db).clinic_admin_b
    assert client.get(URL, headers=auth(outsider)).status_code == 404
    assert (
        client.patch(
            f"{URL}/{POOJA_RECORD}", json={"practitioner": {"bio": "x"}}, headers=auth(outsider)
        ).status_code
        == 404
    )
