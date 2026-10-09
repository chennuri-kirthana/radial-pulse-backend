"""Signing each request with the service's own IAM role (AWS Signature Version 4).

The Central internal REST API has ``AWS_IAM`` on every method, so an unsigned request is refused
by API Gateway. The signing service name is ``execute-api``.

``SigV4Signer`` uses botocore (``pip install "radial-central-client[aws]"``). Credentials come
from the usual AWS chain (the Lambda / ECS role, an SSO profile, ...); temporary credentials add
the ``X-Amz-Security-Token`` header. Nothing is stored or logged by this SDK.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from radial_central_client.errors import ConfigurationError, SigningError

SERVICE_NAME = "execute-api"


class RequestSigner(Protocol):
    """Returns the headers to send: the given ones plus the signature headers."""

    def sign(self, method: str, url: str, headers: Mapping[str, str], body: bytes) -> dict[str, str]: ...


class SigV4Signer:
    def __init__(self, region: str, credentials: Any = None) -> None:
        try:
            import botocore.session
            from botocore.auth import SigV4Auth
            from botocore.awsrequest import AWSRequest
        except ImportError as exc:  # pragma: no cover - depends on the install
            raise ConfigurationError('Install the "aws" extra to sign requests (botocore)') from exc
        self._request_class = AWSRequest
        creds = credentials if credentials is not None else botocore.session.Session().get_credentials()
        if creds is None:
            raise ConfigurationError("No AWS credentials found for this service's IAM role")
        self._auth = SigV4Auth(creds, SERVICE_NAME, region)

    def sign(self, method: str, url: str, headers: Mapping[str, str], body: bytes) -> dict[str, str]:
        request = self._request_class(method=method, url=url, data=body or None, headers=dict(headers))
        try:
            self._auth.add_auth(request)
        except Exception as exc:  # botocore raises its own errors (e.g. no credentials)
            raise SigningError(f"Could not sign the request: {exc.__class__.__name__}") from exc
        return dict(request.headers.items())
