"""/api/v1/internal Phase 1 for the SEO team: GET /active-clinics and GET /clinic-nap/{clinic_id}.

Integration tests (real PostgreSQL 16, real v15 baseline migration, the app login with access rules):
active client clinics only, exact fields, the same 404 for every "not readable" case, bad input,
IAM caller checks, read only.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import Clinic
from tests.factories import World, build_world, make_clinic

pytestmark = pytest.mark.integration

SEO = "test-seo-role"  # clinics.read only (see tests/conftest.py)
ACTIVE_LIST = "/api/v1/internal/active-clinics"


def nap_url(clinic_id: object) -> str:
    return f"/api/v1/internal/clinic-nap/{clinic_id}"


@pytest.fixture
def world(db: Session) -> World:
    """clinic_a = active client with full NAP; clinic_b = a lead; plus one archived and one active
    client without a website/phone, in another business."""
    w = build_world(db)
    a = db.get(Clinic, w.clinic_a.id)
    assert a is not None
    a.stage = "active_client"
    a.phone = "+91 79 4000 1234"
    a.website_url = "https://familydental.example"
    a.address_line = "12 CG Road"
    a.city = "Ahmedabad"
    a.state = "Gujarat"
    a.postal_code = "380009"
    make_clinic(db, w.org_b, name="Bright Smile", stage="active_client", city="Surat")
    make_clinic(
        db,
        w.org_b,
        name="Closed Branch",
        stage="active_client",
        is_active=False,
        archived_reason="Closed in 2026",
    )
    db.commit()
    return w


def test_active_clinics_counts_and_lists_only_active_clients(
    client: TestClient, service_auth, world: World
) -> None:  # type: ignore[no-untyped-def]
    h = service_auth(SEO)
    r = client.get(ACTIVE_LIST, headers=h)
    assert r.status_code == 200
    body = r.json()
    # not the lead (clinic_b), not the archived branch
    assert body["total"] == 2
    assert [i["name"] for i in body["items"]] == ["Bright Smile", "Family Dental Clinic"]
    assert all(set(i) == {"clinic_id", "name"} for i in body["items"])
    assert (body["limit"], body["offset"]) == (50, 0)


def test_active_clinics_paging_keeps_the_total(client: TestClient, service_auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = service_auth(SEO)
    first = client.get(ACTIVE_LIST, params={"limit": 1}, headers=h).json()
    second = client.get(ACTIVE_LIST, params={"limit": 1, "offset": 1}, headers=h).json()
    third = client.get(ACTIVE_LIST, params={"limit": 1, "offset": 2}, headers=h).json()
    assert (first["total"], second["total"], third["total"]) == (2, 2, 2)
    assert [first["items"][0]["name"], second["items"][0]["name"]] == ["Bright Smile", "Family Dental Clinic"]
    assert third["items"] == []


def test_clinic_nap_returns_exactly_the_agreed_fields(client: TestClient, service_auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = service_auth(SEO)
    r = client.get(nap_url(world.clinic_a.id), headers=h)
    assert r.status_code == 200
    assert r.json() == {
        "clinic_id": str(world.clinic_a.id),
        "name": "Family Dental Clinic",
        "address": {
            "line": "12 CG Road",
            "city": "Ahmedabad",
            "state": "Gujarat",
            "postal_code": "380009",
            "country": "IN",
        },
        "phone": "+91 79 4000 1234",
        "website_url": "https://familydental.example",
    }


def test_clinic_nap_without_website_or_phone_gives_null(
    client: TestClient, service_auth, world: World
) -> None:  # type: ignore[no-untyped-def]
    h = service_auth(SEO)
    listed = client.get(ACTIVE_LIST, headers=h).json()["items"]
    bright = next(i for i in listed if i["name"] == "Bright Smile")
    body = client.get(nap_url(bright["clinic_id"]), headers=h).json()
    assert (body["website_url"], body["phone"], body["address"]["city"]) == (None, None, "Surat")


def test_clinic_nap_same_404_for_lead_archived_and_unknown(
    client: TestClient, service_auth, world: World, db: Session
) -> None:  # type: ignore[no-untyped-def]
    h = service_auth(SEO)
    archived = db.query(Clinic).filter(Clinic.name == "Closed Branch").one()
    answers = [
        client.get(nap_url(clinic_id), headers=h)
        for clinic_id in (world.clinic_b.id, archived.id, uuid.uuid4())  # lead, archived, unknown
    ]
    assert [a.status_code for a in answers] == [404, 404, 404]
    bodies = [{k: v for k, v in a.json().items() if k != "request_id"} for a in answers]
    assert bodies[0] == bodies[1] == bodies[2]
    assert bodies[0]["code"] == "not_found"


def test_bad_input_is_400(client: TestClient, service_auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = service_auth(SEO)
    assert client.get(nap_url("not-a-uuid"), headers=h).status_code == 400
    assert client.get(ACTIVE_LIST, params={"limit": 0}, headers=h).status_code == 400
    assert client.get(ACTIVE_LIST, params={"limit": 201}, headers=h).status_code == 400
    assert client.get(ACTIVE_LIST, params={"offset": -1}, headers=h).status_code == 400


def test_iam_caller_rules_apply(client: TestClient, service_auth, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    for url in (ACTIVE_LIST, nap_url(world.clinic_a.id)):
        assert client.get(url).status_code == 401  # no request context
        assert client.get(url, headers=auth(world.admin)).status_code == 401  # a person's token
        assert client.get(url, headers=service_auth("someone-else-role")).status_code == 401
        assert client.get(url, headers=service_auth(SEO, api_id="otherapi")).status_code == 401
        assert client.get(url, headers=service_auth("test-noscope-role")).status_code == 403  # no scope


def test_internal_is_closed_when_not_behind_the_lambda_adapter(
    client: TestClient, service_auth, settings, world: World
) -> None:  # type: ignore[no-untyped-def]
    settings.internal_trust_lambda_context = False  # e.g. running locally / not on the Lambda
    assert client.get(ACTIVE_LIST, headers=service_auth(SEO)).status_code == 503


def test_phase1_routes_are_read_only(client: TestClient, service_auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = service_auth(SEO)
    assert client.post(ACTIVE_LIST, json={}, headers=h).status_code == 405
    assert client.patch(nap_url(world.clinic_a.id), json={"name": "x"}, headers=h).status_code == 405
    assert client.delete(nap_url(world.clinic_a.id), headers=h).status_code == 405
