"""Settings for one backend service. Nothing is hard-coded: every value comes from the caller.

Environment variables (``CentralClientConfig.from_env``):

    CENTRAL_API_BASE_URL       the internal REST API's invoke URL + /api/v1, e.g.
                               https://<api id>.execute-api.ap-south-1.amazonaws.com/<stage>/api/v1
    CENTRAL_AWS_REGION         region of that API (default: AWS_REGION, then ap-south-1)
    CENTRAL_TIMEOUT_SECONDS    optional, default 10

There is no secret here. Requests are signed (SigV4) with the AWS credentials of the service's
own IAM role, found the usual AWS way (Lambda / ECS role, SSO profile, ...).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from radial_central_client.errors import ConfigurationError

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_REGION = "ap-south-1"


def _require_https(name: str, url: str) -> str:
    parsed = urlparse(url)
    local = parsed.hostname in _LOCAL_HOSTS
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ConfigurationError(f"{name} must be an https address")
    if not parsed.hostname:
        raise ConfigurationError(f"{name} is not a valid address")
    return url.rstrip("/")


@dataclass(frozen=True)
class CentralClientConfig:
    api_base_url: str
    region: str = DEFAULT_REGION
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "api_base_url", _require_https("CENTRAL_API_BASE_URL", self.api_base_url))
        if not self.region:
            raise ConfigurationError("CENTRAL_AWS_REGION is required")
        if self.timeout_seconds <= 0:
            raise ConfigurationError("Timeouts must be positive")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> CentralClientConfig:
        env = os.environ if environ is None else environ
        base_url = env.get("CENTRAL_API_BASE_URL", "").strip()
        if not base_url:
            raise ConfigurationError("CENTRAL_API_BASE_URL is required")
        region = (env.get("CENTRAL_AWS_REGION") or env.get("AWS_REGION") or DEFAULT_REGION).strip()
        return cls(
            api_base_url=base_url,
            region=region,
            timeout_seconds=float(env.get("CENTRAL_TIMEOUT_SECONDS", "10")),
        )
