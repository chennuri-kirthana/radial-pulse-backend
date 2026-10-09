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

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient

ALLOWED_ALGORITHMS = ["RS256"]


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
