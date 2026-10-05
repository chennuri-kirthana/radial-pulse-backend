from __future__ import annotations


def test_health_is_public_and_has_security_headers(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert len(r.headers["x-request-id"]) >= 8


def test_request_id_is_propagated_when_safe(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/health", headers={"X-Request-ID": "abc-12345-xyz"})
    assert r.headers["x-request-id"] == "abc-12345-xyz"
    r = client.get("/health", headers={"X-Request-ID": "bad id with spaces\n"})
    assert r.headers["x-request-id"] != "bad id with spaces\n"


def test_ready_checks_database(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_cors_allows_only_configured_origins(client) -> None:  # type: ignore[no-untyped-def]
    ok = client.options(
        "/api/v1/clinics",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options(
        "/api/v1/clinics",
        headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers


def test_openapi_exposes_platform_enums(client) -> None:  # type: ignore[no-untyped-def]
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in (
        "PlatformRole",
        "ClinicRole",
        "ApprovalAction",
        "SnapshotStatus",
        "AssetKind",
        "ProblemDetails",
    ):
        assert name in schemas, name


def test_health_and_openapi_carry_the_contract_version(client) -> None:  # type: ignore[no-untyped-def]
    from app.core.contract import CONTRACT_VERSION

    assert client.get("/health").json()["contract_version"] == CONTRACT_VERSION
    assert client.get("/openapi.json").json()["info"]["version"] == CONTRACT_VERSION


def test_committed_contract_file_is_up_to_date() -> None:
    """openapi/openapi.json must be exactly what the code produces (run `make openapi`)."""
    from app.openapi_export import check
    from tests.conftest import API_ROOT

    assert check(API_ROOT / "openapi" / "openapi.json"), "run `make openapi` and commit the result"
