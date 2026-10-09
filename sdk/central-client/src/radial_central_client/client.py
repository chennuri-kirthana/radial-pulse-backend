"""Authenticated calls to the Central API's internal routes (/api/v1/internal/...)."""

from __future__ import annotations

import json as _json
from types import TracebackType
from typing import Any
from urllib.parse import quote, urlencode
from uuid import UUID

import httpx

from radial_central_client.config import CentralClientConfig
from radial_central_client.errors import CentralApiError, CentralError
from radial_central_client.signing import RequestSigner, SigV4Signer


class CentralClient:
    """One client per service process. Reuse it: it keeps the connection pool.

    Every request is signed with this service's own IAM role (SigV4, ``execute-api``). The routes
    are READ ONLY. Each call needs the matching scope, which the Central team gives your IAM role:
    ``clinics.read`` (clinics, clinic profile, practitioners, online profiles, approved photos,
    active clinics, clinic NAP) or ``connected_accounts.read`` (connected accounts and their
    locations / pages).
    """

    def __init__(
        self,
        config: CentralClientConfig,
        *,
        http: httpx.Client | None = None,
        signer: RequestSigner | None = None,
    ) -> None:
        self._config = config
        self._owns_http = http is None
        self._http = http or httpx.Client(timeout=config.timeout_seconds)
        self._signer = signer or SigV4Signer(config.region)

    # ------------------------------------------------------------------ lifecycle
    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> CentralClient:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    # ------------------------------------------------------------------ core
    def request(
        self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None
    ) -> Any:
        """Call ``<api base>/<path>``, signed. The URL (with its query) and the body are signed
        exactly as they are sent."""
        # SigV4 wants spaces as %20 (httpx would write "+"), so the query is built here and the
        # same string is signed and sent.
        query = urlencode(params or {}, quote_via=quote)
        url = httpx.URL(f"{self._config.api_base_url}/{path.lstrip('/')}" + (f"?{query}" if query else ""))
        body = b"" if json is None else _json.dumps(json, separators=(",", ":")).encode()
        headers = {"Accept": "application/json"}
        if body:
            headers["Content-Type"] = "application/json"
        signed = self._signer.sign(method, str(url), headers, body)
        try:
            response = self._http.request(
                method, url, content=body or None, headers=signed, timeout=self._config.timeout_seconds
            )
        except httpx.HTTPError as exc:
            raise CentralError(f"Central API call failed: {exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise _api_error(response)
        return response.json() if response.content else None

    # ------------------------------------------------------------------ internal routes (read only)
    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def list_clinics(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """GET /internal/clinics (one page: items, total, limit, offset). Scope clinics.read."""
        result: dict[str, Any] = self._get("/internal/clinics", {"limit": limit, "offset": offset})
        return result

    def list_active_clinics(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """GET /internal/active-clinics: active client clinics (items: clinic_id, name; total)."""
        result: dict[str, Any] = self._get("/internal/active-clinics", {"limit": limit, "offset": offset})
        return result

    def get_clinic_nap(self, clinic_id: UUID | str) -> dict[str, Any]:
        """GET /internal/clinic-nap/{clinic_id}: name, address, phone, website_url (404 if not active)."""
        result: dict[str, Any] = self._get(f"/internal/clinic-nap/{clinic_id}")
        return result

    def get_clinic(self, clinic_id: UUID | str) -> dict[str, Any]:
        """GET /internal/clinics/{clinic_id}: the clinic and its Client Organization's name."""
        result: dict[str, Any] = self._get(f"/internal/clinics/{clinic_id}")
        return result

    def get_clinic_profile(self, clinic_id: UUID | str) -> dict[str, Any]:
        """GET /internal/clinics/{clinic_id}/clinic-profile (brand, audience, services, schedule)."""
        result: dict[str, Any] = self._get(f"/internal/clinics/{clinic_id}/clinic-profile")
        return result

    def list_clinic_practitioners(self, clinic_id: UUID | str) -> list[dict[str, Any]]:
        """GET /internal/clinics/{clinic_id}/clinic-practitioners (active links, with the practitioner)."""
        result: list[dict[str, Any]] = self._get(f"/internal/clinics/{clinic_id}/clinic-practitioners")
        return result

    def list_clinic_online_profiles(self, clinic_id: UUID | str) -> list[dict[str, Any]]:
        """GET /internal/clinics/{clinic_id}/clinic-online-profiles."""
        result: list[dict[str, Any]] = self._get(f"/internal/clinics/{clinic_id}/clinic-online-profiles")
        return result

    def list_approved_photos(self, clinic_id: UUID | str) -> list[dict[str, Any]]:
        """GET /internal/clinics/{clinic_id}/photos (approved photos only; details, no file links)."""
        result: list[dict[str, Any]] = self._get(f"/internal/clinics/{clinic_id}/photos")
        return result

    def list_connected_accounts(self, clinic_id: UUID | str) -> list[dict[str, Any]]:
        """GET /internal/clinics/{clinic_id}/connected-accounts (no tokens). Scope connected_accounts.read."""
        result: list[dict[str, Any]] = self._get(f"/internal/clinics/{clinic_id}/connected-accounts")
        return result

    def list_connected_account_resources(self, clinic_id: UUID | str) -> list[dict[str, Any]]:
        """GET /internal/clinics/{clinic_id}/connected-account-resources (locations / sites / pages)."""
        result: list[dict[str, Any]] = self._get(f"/internal/clinics/{clinic_id}/connected-account-resources")
        return result


def _api_error(response: httpx.Response) -> CentralApiError:
    problem: dict[str, Any] = {}
    try:
        data = response.json()
        if isinstance(data, dict):
            problem = data
    except ValueError:
        pass
    return CentralApiError(
        status_code=response.status_code,
        problem_type=problem.get("type"),
        title=problem.get("title"),
        detail=problem.get("detail"),
        request_id=response.headers.get("x-request-id") or problem.get("request_id"),
    )
