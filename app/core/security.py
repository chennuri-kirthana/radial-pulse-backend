"""Verification of Cognito-issued JWT access tokens.

Defense in depth: in AWS, API Gateway's JWT authorizer already rejects bad tokens
at the edge. The API verifies again because (a) it must never trust a network
hop, (b) local/dev traffic may bypass the gateway, and (c) it needs the claims.

What is checked:
* signature (RS256 only) against the user pool's JWKS
* ``iss`` equals the user pool issuer
* ``exp`` / ``iat`` (with a small leeway)
* ``token_use == "access"`` — ID tokens are NOT accepted as API credentials
* ``client_id`` is one of our app clients (Cognito access tokens have no ``aud``)
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient

ALLOWED_ALGORITHMS = ["RS256"]
logger = logging.getLogger(__name__)


class TokenVerificationError(Exception):
    """Raised for ANY token problem. The message is safe to log, never includes the token."""


@dataclass(frozen=True)
class VerifiedToken:
    subject: str
    client_id: str
    username: str | None
    scopes: frozenset[str]
    groups: frozenset[str]
    claims: Mapping[str, Any]


class SigningKeyResolver(Protocol):
    def get_signing_key(self, token: str) -> Any: ...


class JwksSigningKeyResolver:
    """Fetches and caches the user pool's public keys (JWKS)."""

    def __init__(self, jwks_url: str, cache_seconds: int = 3600) -> None:
        self._client = PyJWKClient(jwks_url, cache_keys=True, lifespan=cache_seconds, timeout=5)

    def get_signing_key(self, token: str) -> Any:
        try:
            return self._client.get_signing_key_from_jwt(token).key
        except jwt.PyJWKClientError as exc:
            raise TokenVerificationError(f"signing key lookup failed: {exc.__class__.__name__}") from exc


class S3JwksSigningKeyResolver:
    """The user pool's public keys (JWKS) from a copy in S3, for a Lambda with no internet.

    Zero-NAT design: the API runs in private subnets that reach S3 through the free gateway
    endpoint but cannot reach ``cognito-idp.<region>.amazonaws.com``. A small scheduled Lambda
    OUTSIDE the VPC copies Cognito's JWKS document to ``s3://<bucket>/<key>`` every hour
    (infra/cloudformation/central-jwks-sync-dev.yaml). This class reads that copy.

    What stays the same: the keys are still Cognito's RSA public keys, so every signature check,
    issuer, expiry, ``token_use`` and client-id check in ``CognitoTokenVerifier`` is unchanged.
    A wrong or stale copy can only make valid tokens FAIL (401), never make a bad token pass.

    Freshness and rotation: the set is cached for ``cache_seconds``. A token with a ``kid`` that is
    not in the cache triggers one re-read of S3 (at most every ``min_refresh_seconds``), which is
    how a rotated key is picked up. If S3 cannot be read and a cached set exists, the cached set is
    kept (stale) and a warning is logged; with no cached set the token is refused.
    """

    def __init__(
        self,
        bucket: str,
        key: str,
        region: str,
        cache_seconds: int = 3600,
        client: Any | None = None,
        min_refresh_seconds: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if client is None:
            import boto3  # only the API needs it; tests pass a fake client

            client = boto3.client("s3", region_name=region)
        self._s3 = client
        self._bucket = bucket
        self._key = key
        self._cache_seconds = cache_seconds
        self._min_refresh = min_refresh_seconds
        self._clock = clock
        self._keys: dict[str, Any] = {}
        self._fetched_at: float | None = None

    def _fetch(self) -> dict[str, Any]:
        body = self._s3.get_object(Bucket=self._bucket, Key=self._key)["Body"].read()
        data = json.loads(body)
        keys = data.get("keys") if isinstance(data, dict) else None
        if not isinstance(keys, list) or not keys:
            raise ValueError("JWKS document has no keys")
        jwk_set = jwt.PyJWKSet.from_dict(data)
        return {jwk.key_id: jwk.key for jwk in jwk_set.keys if jwk.key_id}

    def _refresh(self) -> None:
        try:
            self._keys = self._fetch()
        except Exception as exc:
            if self._keys:
                # Keep serving the last good set; the sync Lambda or S3 is the thing to fix.
                logger.warning(
                    "JWKS refresh from S3 failed; keeping cached keys",
                    extra={"exc_class": exc.__class__.__name__},
                )
            else:
                raise TokenVerificationError(f"signing key lookup failed: {exc.__class__.__name__}") from exc
        self._fetched_at = self._clock()

    def get_signing_key(self, token: str) -> Any:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.DecodeError as exc:
            raise TokenVerificationError("malformed token") from exc
        if not kid:
            raise TokenVerificationError("signing key lookup failed: no kid")
        now = self._clock()
        if self._fetched_at is None or now - self._fetched_at >= self._cache_seconds:
            self._refresh()
        key = self._keys.get(kid)
        if key is None and self._fetched_at is not None and now - self._fetched_at >= self._min_refresh:
            self._refresh()  # maybe a rotated key: read S3 once more
            key = self._keys.get(kid)
        if key is None:
            raise TokenVerificationError("signing key lookup failed: unknown kid")
        return key


class CognitoTokenVerifier:
    def __init__(
        self,
        issuer: str,
        allowed_client_ids: list[str],
        key_resolver: SigningKeyResolver,
        leeway_seconds: int = 30,
    ) -> None:
        if not allowed_client_ids:
            raise ValueError("allowed_client_ids must not be empty")
        self._issuer = issuer
        self._client_ids = frozenset(allowed_client_ids)
        self._keys = key_resolver
        self._leeway = leeway_seconds

    def verify(self, token: str) -> VerifiedToken:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.DecodeError as exc:
            raise TokenVerificationError("malformed token") from exc
        if header.get("alg") not in ALLOWED_ALGORITHMS:
            raise TokenVerificationError("unsupported algorithm")

        key = self._keys.get_signing_key(token)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key,
                algorithms=ALLOWED_ALGORITHMS,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "iss", "sub", "token_use"], "verify_aud": False},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenVerificationError("token expired") from exc
        except jwt.InvalidIssuerError as exc:
            raise TokenVerificationError("wrong issuer") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenVerificationError(f"invalid token: {exc.__class__.__name__}") from exc

        if claims.get("token_use") != "access":
            raise TokenVerificationError("not an access token")
        client_id = claims.get("client_id")
        if client_id not in self._client_ids:
            raise TokenVerificationError("unknown app client")

        return VerifiedToken(
            subject=str(claims["sub"]),
            client_id=str(client_id),
            username=claims.get("username"),
            scopes=frozenset(str(claims.get("scope", "")).split()),
            groups=frozenset(claims.get("cognito:groups", []) or []),
            claims=claims,
        )
