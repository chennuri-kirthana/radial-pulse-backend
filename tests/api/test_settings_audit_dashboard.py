"""Area E15: platform settings, the clinic audit log, the dashboard."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import PlatformSettings
from tests.factories import World, build_world

pytestmark = pytest.mark.integration


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


@pytest.fixture
def settings_row(db: Session) -> None:
    """The one settings row (created outside the app: see the open point in the Step E notes)."""
    db.add(PlatformSettings(id=1))
    db.commit()


# ------------------------------------------------------------------ platform settings
@pytest.mark.parametrize("who", ["admin", "dsm", "clinic_admin", "team_member", "practitioner"])
def test_everyone_reads_settings(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/api/v1/platform-settings", headers=auth(world.people_a()[who]))
    assert (r.status_code, r.json()["timezone"], r.json()["updated_at"]) == (200, "Asia/Kolkata", None)


@pytest.mark.usefixtures("settings_row")
def test_admin_changes_settings(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    body = {"support_email": "Help@RadialPulse.in", "timezone": "Asia/Dubai"}
    r = client.patch("/api/v1/platform-settings", json=body, headers=auth(world.admin))
    assert (r.status_code, r.json()["support_email"], r.json()["timezone"]) == (
        200,
        "help@radialpulse.in",
        "Asia/Dubai",
    )
    assert (
        client.get("/api/v1/platform-settings", headers=auth(world.team_member_a)).json()["timezone"]
        == "Asia/Dubai"
    )


@pytest.mark.usefixtures("settings_row")
@pytest.mark.parametrize("who", ["dsm", "clinic_admin", "team_member", "practitioner"])
def test_only_the_admin_changes_settings(client: TestClient, auth, world: World, who: str) -> None:  # type: ignore[no-untyped-def]
    assert (
        client.patch(
            "/api/v1/platform-settings", json={"date_format": "x"}, headers=auth(world.people_a()[who])
        ).status_code
        == 403
    )


@pytest.mark.usefixtures("settings_row")
@pytest.mark.parametrize(
    "body", [{"timezone": "Mars/Base"}, {"support_email": "nope"}, {"date_format": ""}, {"name": "x"}]
)
def test_settings_bad_input(client: TestClient, auth, world: World, body: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
    assert client.patch("/api/v1/platform-settings", json=body, headers=auth(world.admin)).status_code == 400


def test_settings_without_the_row_is_409(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    r = client.patch(
        "/api/v1/platform-settings", json={"date_format": "DD/MM/YYYY"}, headers=auth(world.admin)
    )
    assert (r.status_code, r.json()["code"]) == (409, "state_conflict")


# ------------------------------------------------------------------ audit log
def test_clinic_audit_log(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    client.patch(
        f"/api/v1/clinics/{world.clinic_a.id}", json={"city": "Pune"}, headers=auth(world.clinic_admin_a)
    )
    url = f"/api/v1/clinics/{world.clinic_a.id}/audit-events"
    for who in ["admin", "dsm", "clinic_admin"]:
        page = client.get(url, headers=auth(world.people_a()[who])).json()
        assert [e["action"] for e in page["items"]] == ["clinic.updated"]
        assert page["items"][0]["actor_user_id"] == str(world.clinic_admin_a.id)
    for who in ["team_member", "practitioner"]:
        assert client.get(url, headers=auth(world.people_a()[who])).status_code == 403
    assert client.get(url, headers=auth(world.clinic_admin_b)).status_code == 404
    assert client.get(url, params={"limit": 500}, headers=auth(world.admin)).status_code == 400
    assert (
        client.get(url, params={"action": "clinic.archived"}, headers=auth(world.admin)).json()["total"] == 0
    )


# ------------------------------------------------------------------ dashboard
def test_dashboard_counts_what_each_person_sees(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    admin = client.get("/api/v1/dashboard/summary", headers=auth(world.admin)).json()
    assert admin["clinics_by_stage"]["prospective_client"] == 2
    dsm = client.get("/api/v1/dashboard/summary", headers=auth(world.dsm_a)).json()
    assert dsm["clinics_by_stage"]["prospective_client"] == 1
    clinic_side = client.get("/api/v1/dashboard/summary", headers=auth(world.team_member_a)).json()
    assert (
        clinic_side["photos_waiting_for_review"],
        clinic_side["clinics_by_stage"]["prospective_client"],
    ) == (0, 1)
    assert client.get("/api/v1/dashboard/summary").status_code == 401
