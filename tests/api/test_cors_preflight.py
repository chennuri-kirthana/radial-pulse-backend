"""Browser preflight (OPTIONS) must succeed while the protected GET stays protected.

Incident 10 Oct 2026: API Gateway forwarded `OPTIONS /api/v1/auth/me` to the Lambda, which had no
`CORS_ALLOWED_ORIGINS`, so FastAPI had no CORS middleware and answered 405. Browsers need 2xx.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from tests.conftest import WEB_CLIENT_ID
from tests.factories import World, build_world

pytestmark = pytest.mark.integration


@pytest.fixture
def world(db: Session) -> World:
    return build_world(db)


ORIGIN = "http://localhost:5173"  # the origin the test settings allow
PREFLIGHT = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"}


def test_preflight_from_allowed_origin_is_200_with_cors_headers(client: TestClient) -> None:
    r = client.options("/api/v1/auth/me", headers={"Origin": ORIGIN, **PREFLIGHT})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert "GET" in r.headers["access-control-allow-methods"]
    assert "authorization" in r.headers["access-control-allow-headers"].lower()
    assert "access-control-allow-credentials" not in r.headers  # bearer tokens, not cookies
    assert r.headers["x-request-id"]


def test_preflight_from_another_origin_gets_no_allow_origin(client: TestClient) -> None:
    r = client.options("/api/v1/auth/me", headers={"Origin": "https://evil.example", **PREFLIGHT})
    assert "access-control-allow-origin" not in r.headers
    assert r.status_code == 400  # Starlette refuses a preflight from a foreign origin


def test_preflight_does_not_open_the_protected_get(client: TestClient, auth, world: World) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/api/v1/auth/me", headers={"Origin": ORIGIN}).status_code == 401
    r = client.get("/api/v1/auth/me", headers={"Origin": ORIGIN, **auth(world.admin)})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ORIGIN  # real response also carries CORS
    assert "x-request-id" in r.headers["access-control-expose-headers"].lower()


def test_without_cors_origins_preflight_is_405_and_startup_warns(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Documents the failure mode and the warning that now points at it."""
    import app.main as main_module

    # create_app re-installs the root log handler (JSON lines), which would drop pytest's capture.
    monkeypatch.setattr(main_module, "configure_logging", lambda *a, **k: None)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="dev",
        cognito_region="ap-south-1",
        cognito_user_pool_id="ap-south-1_TEST",
        cognito_app_client_ids=[WEB_CLIENT_ID],
    )
    with caplog.at_level(logging.WARNING, logger="app.main"):
        app = create_app(settings)
    assert any("CORS_ALLOWED_ORIGINS is empty" in m for m in caplog.messages)
    with TestClient(app, raise_server_exceptions=False) as tc:
        assert tc.options("/api/v1/auth/me", headers={"Origin": ORIGIN, **PREFLIGHT}).status_code == 405
