"""S3JwksSigningKeyResolver: JWKS from a copy in S3 (zero-NAT Lambda). Same verifier, same checks."""

from __future__ import annotations

import io
import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.security import CognitoTokenVerifier, S3JwksSigningKeyResolver, TokenVerificationError
from tests.conftest import ISSUER, WEB_CLIENT_ID


def jwks_for(**keys: rsa.RSAPrivateKey) -> bytes:
    """A Cognito-shaped JWKS: one RS256 RSA public key per kid."""
    entries = []
    for kid, private_key in keys.items():
        entry = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
        entry.update({"kid": kid, "alg": "RS256", "use": "sig"})
        entries.append(entry)
    return json.dumps({"keys": entries}).encode()


class FakeS3:
    """Only ``get_object``; counts reads; ``fail=True`` simulates S3 being unreachable."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.reads = 0
        self.fail = False

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803  (boto3 argument names)
        self.reads += 1
        if self.fail:
            raise ConnectionError("no route to S3")
        assert (Bucket, Key) == ("jwks-bucket", "cognito/pool/jwks.json")
        return {"Body": io.BytesIO(self.body)}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_token(private_key: rsa.RSAPrivateKey, kid: str, **overrides: Any) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": "person-1",
        "iss": ISSUER,
        "client_id": WEB_CLIENT_ID,
        "token_use": "access",
        "username": "person-1",
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def keys() -> dict[str, rsa.RSAPrivateKey]:
    return {"k1": rsa.generate_private_key(65537, 2048), "k2": rsa.generate_private_key(65537, 2048)}


def build(s3: FakeS3, clock: Clock) -> tuple[S3JwksSigningKeyResolver, CognitoTokenVerifier]:
    resolver = S3JwksSigningKeyResolver(
        "jwks-bucket", "cognito/pool/jwks.json", "ap-south-1", cache_seconds=3600, client=s3, clock=clock
    )
    return resolver, CognitoTokenVerifier(ISSUER, [WEB_CLIENT_ID], resolver)


def test_valid_token_verifies_with_keys_from_s3_and_the_copy_is_cached(keys) -> None:  # type: ignore[no-untyped-def]
    s3, clock = FakeS3(jwks_for(k1=keys["k1"])), Clock()
    _, verifier = build(s3, clock)
    for _ in range(3):
        assert verifier.verify(make_token(keys["k1"], "k1")).subject == "person-1"
    assert s3.reads == 1  # one read of S3 for many tokens
    clock.now += 3601
    verifier.verify(make_token(keys["k1"], "k1"))
    assert s3.reads == 2  # refreshed after the cache lifetime


def test_all_other_checks_still_apply(keys) -> None:  # type: ignore[no-untyped-def]
    s3, clock = FakeS3(jwks_for(k1=keys["k1"])), Clock()
    _, verifier = build(s3, clock)
    bad = {
        "wrong issuer": {"iss": "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_OTHER"},
        "not an access token": {"token_use": "id"},
        "unknown app client": {"client_id": "someone-else"},
        "token expired": {"exp": int(time.time()) - 120},  # beyond the 30 s leeway
    }
    for reason, overrides in bad.items():
        with pytest.raises(TokenVerificationError, match=reason):
            verifier.verify(make_token(keys["k1"], "k1", **overrides))
    # Signed by a key that is NOT in the S3 copy, but claiming the kid that is: signature fails.
    with pytest.raises(TokenVerificationError, match="InvalidSignatureError"):
        verifier.verify(make_token(keys["k2"], "k1"))


def test_rotated_key_is_picked_up_by_one_extra_read(keys) -> None:  # type: ignore[no-untyped-def]
    s3, clock = FakeS3(jwks_for(k1=keys["k1"])), Clock()
    resolver, verifier = build(s3, clock)
    verifier.verify(make_token(keys["k1"], "k1"))
    # Cognito rotated to k2 and the sync Lambda updated the copy. A k2 token arrives.
    s3.body = jwks_for(k1=keys["k1"], k2=keys["k2"])
    with pytest.raises(TokenVerificationError, match="unknown kid"):
        verifier.verify(make_token(keys["k2"], "k2"))  # within min_refresh_seconds: no re-read yet
    clock.now += 61
    assert verifier.verify(make_token(keys["k2"], "k2")).subject == "person-1"
    assert s3.reads == 2
    # An unknown kid does not cause a read storm.
    for _ in range(5):
        with pytest.raises(TokenVerificationError, match="unknown kid"):
            resolver.get_signing_key(make_token(keys["k2"], "nope"))
    assert s3.reads == 2


def test_s3_outage_keeps_the_cached_keys_but_never_opens_the_door(keys) -> None:  # type: ignore[no-untyped-def]
    s3, clock = FakeS3(jwks_for(k1=keys["k1"])), Clock()
    _, verifier = build(s3, clock)
    verifier.verify(make_token(keys["k1"], "k1"))
    s3.fail = True
    clock.now += 7200
    assert verifier.verify(make_token(keys["k1"], "k1")).subject == "person-1"  # stale copy still works
    with pytest.raises(TokenVerificationError):
        verifier.verify(make_token(keys["k2"], "k2"))  # still refused: no key for it
    # No cache at all + S3 down = every token refused (fail closed).
    cold, _ = build(FakeS3(b""), Clock())
    cold._s3.fail = True  # type: ignore[attr-defined]
    with pytest.raises(TokenVerificationError, match="signing key lookup failed"):
        cold.get_signing_key(make_token(keys["k1"], "k1"))


def test_bad_documents_are_refused(keys) -> None:  # type: ignore[no-untyped-def]
    for body in (b"not json", b"{}", b'{"keys": []}', b'{"keys": "x"}'):
        resolver, _ = build(FakeS3(body), Clock())
        with pytest.raises(TokenVerificationError, match="signing key lookup failed"):
            resolver.get_signing_key(make_token(keys["k1"], "k1"))
    resolver, _ = build(FakeS3(jwks_for(k1=keys["k1"])), Clock())
    with pytest.raises(TokenVerificationError, match="no kid"):
        resolver.get_signing_key(jwt.encode({"sub": "x"}, keys["k1"], algorithm="RS256"))
    with pytest.raises(TokenVerificationError, match="malformed"):
        resolver.get_signing_key("not.a.token")
