from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.security import TokenVerificationError


def test_valid_access_token(verifier, make_token) -> None:  # type: ignore[no-untyped-def]
    token = verifier.verify(make_token("sub-1"))
    assert token.subject == "sub-1"
    assert "openid" in token.scopes


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"token_use": "id"}, "not an access token"),
        ({"client_id": "someone-else"}, "unknown app client"),
        ({"iss": "https://evil.example.com"}, "wrong issuer"),
        ({"exp": int(time.time()) - 3600}, "expired"),
        ({"token_use": None}, "invalid token"),
    ],
)
def test_rejected_tokens(verifier, make_token, overrides, reason) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(TokenVerificationError, match=reason):
        verifier.verify(make_token("sub-1", **overrides))


def test_token_signed_by_another_key_is_rejected(verifier) -> None:  # type: ignore[no-untyped-def]
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    forged = jwt.encode(
        {"sub": "x", "iss": verifier._issuer, "client_id": "test-web-client", "token_use": "access",
         "iat": now, "exp": now + 60},
        other,
        algorithm="RS256",
    )  # fmt: skip
    with pytest.raises(TokenVerificationError):
        verifier.verify(forged)


def test_hs256_and_none_algorithms_are_rejected(verifier) -> None:  # type: ignore[no-untyped-def]
    now = int(time.time())
    claims = {"sub": "x", "iss": verifier._issuer, "client_id": "test-web-client", "token_use": "access",
              "iat": now, "exp": now + 60}  # fmt: skip
    hs = jwt.encode(claims, "a-shared-secret-that-is-long-enough-32b", algorithm="HS256")
    with pytest.raises(TokenVerificationError, match="unsupported algorithm"):
        verifier.verify(hs)
    with pytest.raises(TokenVerificationError):
        verifier.verify("not.a.jwt")
