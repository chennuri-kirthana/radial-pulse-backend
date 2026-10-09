"""SDK behaviour against a fake Central API and a fake signer (no network, no AWS)."""

from __future__ import annotations

from collections.abc import Mapping

import httpx
import pytest
from radial_central_client import (
    CentralApiError,
    CentralClient,
    CentralClientConfig,
    ConfigurationError,
    SigningError,
)

API = "https://abc123.execute-api.ap-south-1.amazonaws.com/dev/api/v1"


class FakeSigner:
    """Records what it was asked to sign and adds a fake signature header."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, str, dict[str, str], bytes]] = []
        self.fail = fail

    def sign(self, method: str, url: str, headers: Mapping[str, str], body: bytes) -> dict[str, str]:
        if self.fail:
            raise SigningError("Could not sign the request: NoCredentialsError")
        self.calls.append((method, url, dict(headers), body))
        return {**headers, "Authorization": f"AWS4-HMAC-SHA256 fake-{len(self.calls)}"}


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.responses: list[httpx.Response] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.responses:
            return self.responses.pop(0)
        return httpx.Response(200, json={"ok": True})


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def signer() -> FakeSigner:
    return FakeSigner()


@pytest.fixture
def client(api: FakeApi, signer: FakeSigner) -> CentralClient:
    http = httpx.Client(transport=httpx.MockTransport(api.handler))
    return CentralClient(CentralClientConfig(api_base_url=API), http=http, signer=signer)


def test_every_call_is_signed_exactly_as_it_is_sent(
    client: CentralClient, api: FakeApi, signer: FakeSigner
) -> None:
    client.list_active_clinics(limit=10, offset=20)
    method, url, headers, body = signer.calls[0]
    sent = api.calls[0]
    assert (method, url, body) == ("GET", str(sent.url), b"")
    assert url == f"{API}/internal/active-clinics?limit=10&offset=20"
    assert sent.headers["authorization"] == "AWS4-HMAC-SHA256 fake-1"
    assert headers == {"Accept": "application/json"}


def test_query_spaces_are_signed_as_percent_20(
    client: CentralClient, api: FakeApi, signer: FakeSigner
) -> None:
    client.request("GET", "/internal/clinics", params={"q": "a b"})
    assert signer.calls[0][1] == f"{API}/internal/clinics?q=a%20b" == str(api.calls[0].url)


def test_phase1_routes(client: CentralClient, api: FakeApi) -> None:
    client.get_clinic_nap("2b1f3c1e-0000-4000-8000-000000000001")
    assert str(api.calls[0].url) == f"{API}/internal/clinic-nap/2b1f3c1e-0000-4000-8000-000000000001"


def test_a_401_is_not_retried(client: CentralClient, api: FakeApi) -> None:
    api.responses.append(httpx.Response(401, json={"type": "about:blank", "title": "Unauthorized"}))
    with pytest.raises(CentralApiError) as info:
        client.list_clinics()
    assert info.value.status_code == 401
    assert len(api.calls) == 1


def test_api_errors_carry_the_problem_and_request_id(client: CentralClient, api: FakeApi) -> None:
    api.responses.append(
        httpx.Response(
            403,
            json={"type": "about:forbidden", "title": "Forbidden", "detail": "Missing scope"},
            headers={"X-Request-Id": "req-123"},
        )
    )
    with pytest.raises(CentralApiError) as info:
        client.get_clinic("2b1f3c1e-0000-4000-8000-000000000001")
    error = info.value
    assert (error.status_code, error.request_id, error.detail) == (403, "req-123", "Missing scope")


def test_a_signing_failure_sends_nothing(api: FakeApi) -> None:
    http = httpx.Client(transport=httpx.MockTransport(api.handler))
    client = CentralClient(CentralClientConfig(api_base_url=API), http=http, signer=FakeSigner(fail=True))
    with pytest.raises(SigningError):
        client.list_active_clinics()
    assert api.calls == []


def test_config_needs_https_and_reads_the_region() -> None:
    with pytest.raises(ConfigurationError, match="https"):
        CentralClientConfig(api_base_url="http://api.example.test/api/v1")
    assert CentralClientConfig(api_base_url="http://localhost:8000/api/v1").api_base_url.startswith("http://")
    config = CentralClientConfig.from_env({"CENTRAL_API_BASE_URL": API + "/", "AWS_REGION": "eu-west-1"})
    assert (config.api_base_url, config.region) == (API, "eu-west-1")
    config = CentralClientConfig.from_env({"CENTRAL_API_BASE_URL": API, "CENTRAL_AWS_REGION": "ap-south-1"})
    assert config.region == "ap-south-1"
    with pytest.raises(ConfigurationError, match="CENTRAL_API_BASE_URL"):
        CentralClientConfig.from_env({})


def test_no_secret_settings_remain() -> None:
    fields = set(CentralClientConfig.__dataclass_fields__)
    assert fields == {"api_base_url", "region", "timeout_seconds"}
