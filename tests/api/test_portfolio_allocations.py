"""Area E3: Portfolio Allocations (docs/01 section 3)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import PlatformRole
from app.models import AuditEvent, Notification, PortfolioAllocation
from tests.factories import World, build_world, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


def url(world: World) -> str:
    return f"/api/v1/portfolio-allocations/{world.org_a.id}"


def test_who_sees_which_allocations(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    def orgs(user) -> list[str]:  # type: ignore[no-untyped-def]
        return sorted(
            a["client_organization_name"]
            for a in client.get("/api/v1/portfolio-allocations", headers=auth(user)).json()
        )

    assert orgs(world.admin) == ["Shah Healthcare Pvt Ltd", "SmileCare LLP"]
    assert orgs(world.dsm_a) == ["Shah Healthcare Pvt Ltd"]  # My Client Portfolio
    assert orgs(world.clinic_admin_a) == ["Shah Healthcare Pvt Ltd"]  # the DSM of my business
    assert orgs(world.clinic_admin_b) == ["SmileCare LLP"]


def test_admin_moves_a_business_to_another_dsm(client: TestClient, auth, world: World, db: Session) -> None:  # type: ignore[no-untyped-def]
    new_dsm = make_user(db, PlatformRole.DIGITAL_SUCCESS_MANAGER)
    db.commit()
    r = client.put(url(world), json={"user_id": str(new_dsm.id)}, headers=auth(world.admin))
    assert (r.status_code, r.json()["user_id"], r.json()["is_active"]) == (200, str(new_dsm.id), True)

    rows = {
        a.user_id: a.is_active
        for a in db.scalars(
            select(PortfolioAllocation).where(PortfolioAllocation.client_organization_id == world.org_a.id)
        )
    }
    assert rows == {world.dsm_a.id: False, new_dsm.id: True}  # the past DSM stays, inactive
    assert db.scalars(select(Notification.category).where(Notification.user_id == new_dsm.id)).all() == [
        "portfolio_allocated"
    ]
    assert db.scalar(select(AuditEvent.action).where(AuditEvent.action == "portfolio_allocation.changed"))

    # the new DSM sees the clinics at once; the old one no longer does
    assert client.get(f"/api/v1/clinics/{world.clinic_a.id}", headers=auth(new_dsm)).status_code == 200
    assert client.get(f"/api/v1/clinics/{world.clinic_a.id}", headers=auth(world.dsm_a)).status_code == 404

    # same DSM again: no change, no second notification
    again = client.put(url(world), json={"user_id": str(new_dsm.id)}, headers=auth(world.admin))
    assert again.status_code == 200
    assert len(db.scalars(select(Notification).where(Notification.user_id == new_dsm.id)).all()) == 1


def test_moving_back_reactivates_the_old_row(client: TestClient, auth, world: World, db: Session) -> None:  # type: ignore[no-untyped-def]
    other = make_user(db, PlatformRole.DIGITAL_SUCCESS_MANAGER)
    db.commit()
    h = auth(world.admin)
    client.put(url(world), json={"user_id": str(other.id)}, headers=h)
    r = client.put(url(world), json={"user_id": str(world.dsm_a.id)}, headers=h)
    assert r.status_code == 200
    assert (
        len(
            db.scalars(
                select(PortfolioAllocation).where(
                    PortfolioAllocation.client_organization_id == world.org_a.id
                )
            ).all()
        )
        == 2
    )


def test_ending_makes_it_a_new_lead_again(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    assert client.delete(url(world), headers=auth(world.admin)).status_code == 204
    assert client.get(f"/api/v1/clinics/{world.clinic_a.id}", headers=auth(world.dsm_a)).status_code == 404
    assert client.delete(url(world), headers=auth(world.admin)).status_code == 404  # nothing active now


@pytest.mark.parametrize("who", ["dsm", "clinic_admin", "team_member", "practitioner"])
def test_only_the_admin_allocates(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.people_a()[who])
    assert client.put(url(world), json={"user_id": str(world.dsm_b.id)}, headers=h).status_code == 403
    assert client.delete(url(world), headers=h).status_code == 403


def test_allocation_errors(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = auth(world.admin)
    not_a_dsm = client.put(url(world), json={"user_id": str(world.clinic_admin_a.id)}, headers=h)
    assert (not_a_dsm.status_code, not_a_dsm.json()["code"]) == (409, "state_conflict")
    assert client.put(url(world), json={"user_id": str(uuid.uuid4())}, headers=h).status_code == 404
    unknown_org = f"/api/v1/portfolio-allocations/{uuid.uuid4()}"
    assert client.put(unknown_org, json={"user_id": str(world.dsm_b.id)}, headers=h).status_code == 404
    assert client.put(url(world), json={"user_id": "not-a-uuid"}, headers=h).status_code == 400
