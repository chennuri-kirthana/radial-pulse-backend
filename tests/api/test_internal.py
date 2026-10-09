"""Area E16: /api/v1/internal, read only, for other teams' backends (AWS IAM roles)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ConnectedAccount, Photo
from tests.factories import World, build_world

pytestmark = pytest.mark.integration

SEO = "test-seo-role"  # clinics.read
ACCOUNTS = "test-accounts-role"  # clinics.read + connected_accounts.read
NO_SCOPE = "test-noscope-role"


@pytest.fixture
def world(db: Session) -> World:
    w = build_world(db)
    db.add(
        ConnectedAccount(
            clinic_id=w.clinic_a.id, provider="google", external_account_id="acct", secret_ref="arn:secret"
        )
    )
    for state, note in (("approved", None), ("pending", None), ("rejected", "Blurry")):
        db.add(
            Photo(
                clinic_id=w.clinic_a.id,
                category="logo" if state != "rejected" else "cover",
                original_key=f"clinics/{w.clinic_a.id}/photos/{uuid.uuid4()}.jpg",
                mime_type="image/jpeg",
                size_bytes=10,
                processing_status="ready",
                review_state=state,
                review_note=note,
                reviewed_at=None if state == "pending" else "2026-10-01T00:00:00Z",
            )
        )
    db.commit()
    return w


def test_service_reads_clinics_and_their_data(client: TestClient, service_auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = service_auth(SEO)
    listed = client.get("/api/v1/internal/clinics", headers=h).json()
    assert listed["total"] == 2  # every clinic, also new leads
    one = client.get(f"/api/v1/internal/clinics/{world.clinic_a.id}", headers=h).json()
    assert (one["name"], one["client_organization_name"]) == (
        "Family Dental Clinic",
        "Shah Healthcare Pvt Ltd",
    )
    base = f"/api/v1/internal/clinics/{world.clinic_a.id}"
    assert client.get(f"{base}/clinic-profile", headers=h).json()["version"] == 0
    assert [
        p["practitioner"]["full_name"] for p in client.get(f"{base}/clinic-practitioners", headers=h).json()
    ] == ["Dr. Pooja Shah"]
    assert client.get(f"{base}/clinic-online-profiles", headers=h).json() == []
    photos = client.get(f"{base}/photos", headers=h).json()
    assert [p["review_state"] for p in photos] == ["approved"]  # the database shows approved photos only


def test_connected_accounts_never_include_the_secret(client: TestClient, service_auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = service_auth(ACCOUNTS)
    r = client.get(f"/api/v1/internal/clinics/{world.clinic_a.id}/connected-accounts", headers=h)
    assert r.status_code == 200
    assert [a["external_account_id"] for a in r.json()] == ["acct"]
    assert "secret" not in r.text
    assert (
        client.get(
            f"/api/v1/internal/clinics/{world.clinic_a.id}/connected-account-resources", headers=h
        ).json()
        == []
    )


def test_scopes_decide(client: TestClient, service_auth, world: World) -> None:  # type: ignore[no-untyped-def]
    only_clinics = service_auth(SEO)
    assert (
        client.get(
            f"/api/v1/internal/clinics/{world.clinic_a.id}/connected-accounts", headers=only_clinics
        ).status_code
        == 403
    )
    nothing = service_auth(NO_SCOPE)
    assert client.get("/api/v1/internal/clinics", headers=nothing).status_code == 403


def test_callers_that_are_not_allowed_iam_roles_are_401(
    client: TestClient, service_auth, auth, world: World
) -> None:  # type: ignore[no-untyped-def]
    url = "/api/v1/internal/clinics"
    assert client.get(url).status_code == 401  # no request context at all
    assert client.get(url, headers=auth(world.admin)).status_code == 401  # a person's Cognito token
    assert client.get(url, headers=service_auth("someone-else-role")).status_code == 401  # not listed
    # same role name, but in another AWS account
    assert client.get(url, headers=service_auth(SEO, account="999988887777")).status_code == 401
    # came through another API (e.g. the people's HTTP API), not our internal REST API
    assert client.get(url, headers=service_auth(SEO, api_id="otherapi")).status_code == 401
    # no IAM identity (method not set to AWS_IAM)
    assert client.get(url, headers=service_auth(SEO, identity={})).status_code == 401
    # an IAM user, not an assumed role
    user = service_auth(SEO, user_arn="arn:aws:iam::111122223333:user/test-seo-role")
    assert client.get(url, headers=user).status_code == 401
    assert client.get(url, headers={"x-amzn-request-context": "not json"}).status_code == 401


def test_service_roles_do_not_open_user_routes(client: TestClient, service_auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = service_auth(SEO)
    assert client.get(f"/api/v1/clinics/{world.clinic_a.id}", headers=h).status_code == 401


def test_unknown_clinic_and_bad_input(client: TestClient, service_auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = service_auth(SEO)
    assert client.get(f"/api/v1/internal/clinics/{uuid.uuid4()}", headers=h).status_code == 404
    assert client.get(f"/api/v1/internal/clinics/{uuid.uuid4()}/photos", headers=h).status_code == 404
    assert client.get("/api/v1/internal/clinics/not-a-uuid", headers=h).status_code == 400
    assert client.get("/api/v1/internal/clinics", params={"limit": 0}, headers=h).status_code == 400


def test_internal_is_read_only(client: TestClient, service_auth, world: World) -> None:  # type: ignore[no-untyped-def]
    h = service_auth(SEO)
    assert (
        client.patch(
            f"/api/v1/internal/clinics/{world.clinic_a.id}", json={"name": "x"}, headers=h
        ).status_code
        == 405
    )
