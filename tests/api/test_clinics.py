"""Area E2: Client Organizations and clinics (docs/01 section 2, docs/02)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, ClinicStageChange
from tests.factories import World, build_world

pytestmark = pytest.mark.integration

A_PEOPLE = ["admin", "dsm", "clinic_admin", "team_member", "practitioner"]


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


def url(world: World, tail: str = "") -> str:
    return f"/api/v1/clinics/{world.clinic_a.id}{tail}"


def audited(db: Session, action: str) -> int:
    return len(db.scalars(select(AuditEvent).where(AuditEvent.action == action)).all())


# ------------------------------------------------------------------ list + read
def test_each_role_lists_only_its_clinics(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    def names(user) -> set[str]:  # type: ignore[no-untyped-def]
        return {c["name"] for c in client.get("/api/v1/clinics", headers=auth(user)).json()["items"]}

    assert names(world.admin) == {"Family Dental Clinic", "SmileCare Andheri"}
    for who in ["dsm", "clinic_admin", "team_member", "practitioner"]:
        assert names(world.people_a()[who]) == {"Family Dental Clinic"}
    assert names(world.clinic_admin_b) == {"SmileCare Andheri"}


@pytest.mark.parametrize("who", A_PEOPLE)
def test_everyone_of_the_clinic_reads_it(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    r = client.get(url(world), headers=auth(world.people_a()[who]))
    assert (r.status_code, r.json()["name"]) == (200, "Family Dental Clinic")


def test_other_clinic_or_unknown_is_404(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    assert client.get(url(world), headers=auth(world.clinic_admin_b)).status_code == 404
    assert client.get(url(world), headers=auth(world.dsm_b)).status_code == 404
    assert client.get(f"/api/v1/clinics/{uuid.uuid4()}", headers=auth(world.admin)).status_code == 404


# ------------------------------------------------------------------ new leads (admin only)
def test_admin_adds_a_new_lead_and_its_business_in_one_step(
    client: TestClient, auth, world: World, db: Session
) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        "/api/v1/clinics", json={"name": "Sunrise Dental", "city": "Pune"}, headers=auth(world.admin)
    )
    assert r.status_code == 201, r.text
    clinic = r.json()
    assert (clinic["stage"], clinic["country"]) == ("prospective_client", "IN")
    org = client.get(
        f"/api/v1/client-organizations/{clinic['client_organization_id']}", headers=auth(world.admin)
    )
    assert org.json()["name"] == "Sunrise Dental"  # the business is named after the clinic
    assert audited(db, "client_organization.created") == 1 and audited(db, "clinic.created") == 1
    # a new lead has no DSM yet: only the Platform Administrator sees it
    dsm_view = client.get(f"/api/v1/clinics/{clinic['id']}", headers=auth(world.dsm_a))
    assert dsm_view.status_code == 404


def test_admin_adds_a_branch_to_an_existing_business(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    body = {"name": "Family Dental Satellite", "client_organization_id": str(world.org_a.id)}
    r = client.post("/api/v1/clinics", json=body, headers=auth(world.admin))
    assert r.status_code == 201
    # the DSM of that business sees the new branch at once
    assert client.get(f"/api/v1/clinics/{r.json()['id']}", headers=auth(world.dsm_a)).status_code == 200


@pytest.mark.parametrize("who", ["dsm", "clinic_admin", "team_member", "practitioner"])
def test_only_the_admin_adds_leads(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    r = client.post("/api/v1/clinics", json={"name": "X"}, headers=auth(world.people_a()[who]))
    assert r.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"name": ""},
        {"name": "X", "country": "india"},
        {"name": "X", "latitude": 10},
        {"name": "X", "established_year": datetime.now(UTC).year + 2},
        {"name": "X", "client_organization_id": str(uuid.uuid4()), "client_organization_name": "Y"},
    ],
)
def test_new_lead_bad_input_is_400(client: TestClient, auth, world: World, body: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
    r = client.post("/api/v1/clinics", json=body, headers=auth(world.admin))
    assert (r.status_code, r.json()["code"]) == (400, "invalid_request")


# ------------------------------------------------------------------ edit details
@pytest.mark.parametrize("who", ["admin", "dsm", "clinic_admin"])
def test_staff_and_clinic_admin_edit_details(
    client: TestClient, auth, world: World, who: str, db: Session
) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(
        url(world), json={"city": "Ahmedabad", "established_year": 2008}, headers=auth(world.people_a()[who])
    )
    assert (r.status_code, r.json()["city"], r.json()["established_year"]) == (200, "Ahmedabad", 2008)
    assert audited(db, "clinic.updated") == 1


@pytest.mark.parametrize("who", ["team_member", "practitioner"])
def test_team_member_and_practitioner_cannot_edit(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    assert (
        client.patch(url(world), json={"city": "X"}, headers=auth(world.people_a()[who])).status_code == 403
    )


def test_edit_rules(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    assert client.patch(url(world), json={"city": "X"}, headers=auth(world.clinic_admin_b)).status_code == 404
    h = auth(world.clinic_admin_a)
    assert client.patch(url(world), json={"name": None}, headers=h).status_code == 400
    assert client.patch(url(world), json={"latitude": 10}, headers=h).status_code == 400  # database pair rule
    assert (
        client.patch(url(world), json={"stage": "active_client"}, headers=h).status_code == 400
    )  # not a field here
    move = {"client_organization_id": str(world.org_b.id)}
    assert (
        client.patch(url(world), json=move, headers=h).status_code == 403
    )  # Clinic Administrator can't move it
    assert (
        client.patch(url(world), json=move, headers=auth(world.dsm_a)).status_code == 404
    )  # not his business
    r = client.patch(url(world), json=move, headers=auth(world.admin))
    assert (r.status_code, r.json()["client_organization_id"]) == (200, str(world.org_b.id))


# ------------------------------------------------------------------ stage, history, archive
def test_dsm_moves_the_stage_and_the_trigger_writes_history(
    client: TestClient, auth, world: World, db: Session
) -> None:  # type: ignore[no-untyped-def]
    r = client.post(
        url(world, "/stage"),
        json={"stage": "presence_discovered", "note": "found online"},
        headers=auth(world.dsm_a),
    )
    assert (r.status_code, r.json()["stage"]) == (200, "presence_discovered")
    history = db.scalars(
        select(ClinicStageChange).where(ClinicStageChange.clinic_id == world.clinic_a.id)
    ).all()
    moved = [h for h in history if h.to_stage == "presence_discovered"]
    assert [(h.from_stage, h.note, h.changed_by_user_id) for h in moved] == [
        ("prospective_client", "found online", world.dsm_a.id)
    ]
    listed = client.get(url(world, "/clinic-stage-changes"), headers=auth(world.dsm_a)).json()
    assert listed[0]["to_stage"] == "presence_discovered"
    same = client.post(url(world, "/stage"), json={"stage": "presence_discovered"}, headers=auth(world.dsm_a))
    assert same.status_code == 409


@pytest.mark.parametrize("who", ["clinic_admin", "team_member", "practitioner"])
def test_only_staff_move_stage_archive_and_see_history(
    client: TestClient, auth, world: World, who: str
) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.people_a()[who])
    assert client.post(url(world, "/stage"), json={"stage": "active_client"}, headers=h).status_code == 403
    assert client.get(url(world, "/clinic-stage-changes"), headers=h).status_code == 403
    assert client.post(url(world, "/archive"), json={"archived_reason": "x"}, headers=h).status_code == 403


def test_stage_bad_input_and_other_clinic(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    assert (
        client.post(
            url(world, "/stage"), json={"stage": "profile_enriched"}, headers=auth(world.dsm_a)
        ).status_code
        == 400
    )
    assert (
        client.post(
            url(world, "/stage"), json={"stage": "active_client"}, headers=auth(world.dsm_b)
        ).status_code
        == 404
    )


def test_archive_needs_a_reason_and_restore_clears_it(
    client: TestClient, auth, world: World, db: Session
) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.dsm_a)
    assert client.post(url(world, "/archive"), json={"archived_reason": ""}, headers=h).status_code == 400
    r = client.post(url(world, "/archive"), json={"archived_reason": "Closed for now"}, headers=h)
    assert (r.json()["is_active"], r.json()["archived_reason"]) == (False, "Closed for now")
    assert (
        client.post(url(world, "/archive"), json={"archived_reason": "again"}, headers=h).status_code == 409
    )
    r = client.post(url(world, "/restore"), headers=h)
    assert (r.json()["is_active"], r.json()["archived_reason"], r.json()["stage"]) == (
        True,
        None,
        "prospective_client",
    )
    assert audited(db, "clinic.archived") == 1 and audited(db, "clinic.restored") == 1


# ------------------------------------------------------------------ Client Organizations
def test_client_organizations_visibility_and_admin_only_changes(
    client: TestClient, auth, world: World
) -> None:  # type: ignore[no-untyped-def]
    def names(user) -> set[str]:  # type: ignore[no-untyped-def]
        return {
            o["name"] for o in client.get("/api/v1/client-organizations", headers=auth(user)).json()["items"]
        }

    assert names(world.admin) == {"Shah Healthcare Pvt Ltd", "SmileCare LLP"}
    assert names(world.dsm_a) == {"Shah Healthcare Pvt Ltd"}
    assert names(world.clinic_admin_b) == {"SmileCare LLP"}
    assert (
        client.get(f"/api/v1/client-organizations/{world.org_b.id}", headers=auth(world.dsm_a)).status_code
        == 404
    )

    assert (
        client.post(
            "/api/v1/client-organizations", json={"name": "New Co"}, headers=auth(world.admin)
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/client-organizations", json={"name": "New Co"}, headers=auth(world.dsm_a)
        ).status_code
        == 403
    )
    assert (
        client.post("/api/v1/client-organizations", json={"name": ""}, headers=auth(world.admin)).status_code
        == 400
    )
    rename = f"/api/v1/client-organizations/{world.org_a.id}"
    assert client.patch(rename, json={"name": "Shah Group"}, headers=auth(world.dsm_a)).status_code == 403
    assert (
        client.patch(rename, json={"name": "Shah Group"}, headers=auth(world.admin)).json()["name"]
        == "Shah Group"
    )
