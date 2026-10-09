"""Test harness. PostgreSQL 16 only (CLAUDE.md: never SQLite).

Database (needs TEST_DATABASE_URL = an OWNER login, e.g. the docker compose `radial` user):
* built ONCE per run by the REAL baseline migration (db/schema-v15.sql as-is);
* the API under test logs in as `radial_app_test`: NOT the owner, member of `radial_app` and
  `radial_service`, so every access rule (row-level security) applies exactly as in AWS;
* tests arrange data with the OWNER session (`db`), which skips the rules;
* after each test every table is emptied.

Auth: real JWT verification with a test RSA key pair. Only the key source is swapped.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.core.config import Settings
from app.core.security import CognitoTokenVerifier
from app.db.base import Base
from app.db.session import get_engine
from app.dependencies.adapters import (
    get_identity_directory,
    get_oauth_client,
    get_optional_storage,
    get_secret_store,
    get_storage,
    settings_dependency,
)
from app.dependencies.auth import get_token_verifier, get_userinfo_client
from app.dependencies.db import get_db
from app.integrations.cognito import UserInfo
from app.integrations.identity_directory import AlreadySignedUpError, InvitedAccount
from app.integrations.oauth import OAuthError, OAuthProvider, TokenSet
from app.integrations.storage import ObjectInfo
from app.main import create_app

API_ROOT = Path(__file__).resolve().parents[1]
ISSUER = "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_TEST"
WEB_CLIENT_ID = "test-web-client"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
APP_TEST_USER = "radial_app_test"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="needs PostgreSQL: set TEST_DATABASE_URL")
    for item in items:
        if "integration" in item.keywords or "client" in getattr(item, "fixturenames", ()):
            item.add_marker(skip)


# ------------------------------------------------------------------ keys & tokens
@pytest.fixture(scope="session")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticKeyResolver:
    def __init__(self, public_key: Any) -> None:
        self._key = public_key

    def get_signing_key(self, token: str) -> Any:
        return self._key


@pytest.fixture(scope="session")
def verifier(rsa_key: rsa.RSAPrivateKey) -> CognitoTokenVerifier:
    return CognitoTokenVerifier(
        issuer=ISSUER,
        allowed_client_ids=[WEB_CLIENT_ID],
        key_resolver=StaticKeyResolver(rsa_key.public_key()),
    )


@pytest.fixture(scope="session")
def make_token(rsa_key: rsa.RSAPrivateKey):  # type: ignore[no-untyped-def]
    def _make(sub: str, **overrides: Any) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": sub,
            "iss": ISSUER,
            "client_id": WEB_CLIENT_ID,
            "token_use": "access",
            "scope": "openid email",
            "iat": now,
            "exp": now + 600,
            "username": f"user_{sub}",
        }
        claims.update(overrides)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, rsa_key, algorithm="RS256", headers={"kid": "test"})

    return _make


# ------------------------------------------------------------------------ fakes
@dataclass
class FakeUserInfo:
    """Stands in for Cognito's /oauth2/userInfo (tests configure what it returns)."""

    by_token_sub: dict[str, UserInfo] = field(default_factory=dict)

    def fetch(self, access_token: str) -> UserInfo:
        sub = jwt.decode(access_token, options={"verify_signature": False})["sub"]
        return self.by_token_sub.get(sub, UserInfo(email=None, email_verified=False, name=None))


@dataclass
class InMemoryStorage:
    """Test double for S3. Tests 'upload' by writing into ``objects``."""

    objects: dict[str, ObjectInfo] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)

    #: content_length signed into each presigned PUT, by key (None = not signed).
    signed_lengths: dict[str, int | None] = field(default_factory=dict)

    def presign_put(
        self, key: str, content_type: str, ttl_seconds: int, content_length: int | None = None
    ) -> tuple[str, dict[str, str]]:
        self.signed_lengths[key] = content_length
        return f"https://test-bucket.s3.amazonaws.com/{key}?signature=fake", {"Content-Type": content_type}

    def presign_get(self, key: str, ttl_seconds: int, download_name: str | None = None) -> str:
        return f"https://test-bucket.s3.amazonaws.com/{key}?download=1"

    def head(self, key: str) -> ObjectInfo | None:
        return self.objects.get(key)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)
        self.deleted.append(key)


@dataclass
class InviteCall:
    email: str
    full_name: str | None
    resend: bool


@dataclass
class FakeIdentityDirectory:
    """Test double for the Cognito admin API.

    ``fail = True`` simulates an outage; ``signed_up`` holds emails that already chose a password.
    """

    sent: list[InviteCall] = field(default_factory=list)
    subs: dict[str, str] = field(default_factory=dict)
    disabled: list[str] = field(default_factory=list)
    enabled: list[str] = field(default_factory=list)
    signed_up: set[str] = field(default_factory=set)
    fail: bool = False

    def _check(self) -> None:
        if self.fail:
            raise RuntimeError("cognito down")

    def invite(self, email: str, full_name: str | None) -> InvitedAccount:
        self._check()
        if email in self.subs:
            return InvitedAccount(sub=self.subs[email], created=False)
        self.subs[email] = str(uuid.uuid4())
        self.sent.append(InviteCall(email, full_name, resend=False))
        return InvitedAccount(sub=self.subs[email], created=True)

    def resend_invite(self, email: str, full_name: str | None) -> InvitedAccount:
        self._check()
        if email in self.signed_up:
            raise AlreadySignedUpError("already chose a password")
        if email not in self.subs:
            return self.invite(email, full_name)
        self.sent.append(InviteCall(email, full_name, resend=True))
        return InvitedAccount(sub=self.subs[email], created=True)

    def disable(self, email: str) -> None:
        self._check()
        self.disabled.append(email)

    def enable(self, email: str) -> None:
        self._check()
        self.enabled.append(email)


OAUTH_REDIRECT = "http://localhost:5173/connections/callback"


@dataclass
class InMemorySecretStore:
    """Test double for AWS Secrets Manager."""

    secrets: dict[str, dict[str, Any]] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)

    def save(self, name: str, value: dict[str, Any]) -> str:
        self.secrets[name] = value
        return f"arn:aws:secretsmanager:ap-south-1:000000000000:secret:{name}"

    def delete(self, ref: str) -> None:
        self.deleted.append(ref)
        self.secrets.pop(ref.split(":secret:", 1)[-1], None)


@dataclass
class FakeOAuthClient:
    """Test double for the platforms' token endpoints. Records calls; ``fail`` makes it refuse."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False

    def exchange_code(
        self,
        provider: OAuthProvider,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str | None,
        scopes: list[str],
    ) -> TokenSet:
        self.calls.append(
            {"provider": provider.key, "code": code, "redirect_uri": redirect_uri, "verifier": code_verifier}
        )
        if self.fail:
            raise OAuthError(f"{provider.key} refused the sign-in (HTTP 400)")
        return TokenSet(
            access_token=f"access-{code}",
            refresh_token=f"refresh-{code}",
            token_type="Bearer",
            scopes=scopes,
            expires_at=None,
        )


# --------------------------------------------------------------------- database
@pytest.fixture(scope="session")
def postgres_engines() -> Iterator[tuple[Engine, Engine]]:
    """(owner_engine, app_engine). The owner builds the schema with the REAL baseline migration."""
    if not TEST_DATABASE_URL:
        pytest.skip("needs PostgreSQL: set TEST_DATABASE_URL")
    from alembic import command
    from alembic.config import Config

    owner = create_engine(TEST_DATABASE_URL, future=True)
    with owner.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    with owner.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    with owner.begin() as conn:
        conn.execute(
            text(
                f"""
                DO $$ BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_TEST_USER}') THEN
                    CREATE ROLE {APP_TEST_USER} LOGIN PASSWORD '{APP_TEST_USER}';
                  END IF;
                END $$;
                GRANT radial_app TO {APP_TEST_USER};
                GRANT radial_service TO {APP_TEST_USER};
                """
            )
        )
    app_url = make_url(TEST_DATABASE_URL).set(username=APP_TEST_USER, password=APP_TEST_USER)
    app_engine = create_engine(app_url, future=True)
    yield owner, app_engine
    app_engine.dispose()
    owner.dispose()


#: Every table except platform_settings (one fixed row, reset instead).
_DATA_TABLES = ", ".join(
    t.name for t in reversed(Base.metadata.sorted_tables) if t.name != "platform_settings"
)


@pytest.fixture
def engines(postgres_engines: tuple[Engine, Engine]) -> Iterator[tuple[Engine, Engine]]:
    yield postgres_engines
    owner = postgres_engines[0]
    with owner.begin() as conn:
        # audit_events refuses TRUNCATE by trigger; skip triggers for this cleanup only.
        conn.execute(text("SET LOCAL session_replication_role = replica"))
        conn.execute(text(f"TRUNCATE {_DATA_TABLES} CASCADE"))
        conn.execute(text("DELETE FROM platform_settings"))


@pytest.fixture
def engine(engines: tuple[Engine, Engine]) -> Engine:
    """The APPLICATION engine (non-owner: access rules apply)."""
    return engines[1]


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(engines: tuple[Engine, Engine]) -> Iterator[Session]:
    """An OWNER session for arranging test data and checking results (skips the access rules)."""
    session = sessionmaker(bind=engines[0], autoflush=False, expire_on_commit=False)()
    session.info["rp_owner"] = True  # see app/db/tenant.py: the owner session sets no role
    yield session
    session.close()


# -------------------------------------------------------------------------- app
@pytest.fixture
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="test",
        docs_enabled=True,
        cognito_region="ap-south-1",
        cognito_user_pool_id="ap-south-1_TEST",
        cognito_app_client_ids=[WEB_CLIENT_ID],
        s3_assets_bucket="test-bucket",
        cors_allowed_origins=["http://localhost:5173"],
        oauth_redirect_uris=[OAUTH_REDIRECT],
        google_oauth_client_id="google-client",
        google_oauth_client_secret="google-secret",
        meta_app_id="meta-app",
        meta_app_secret="meta-secret",
        internal_service_roles=SERVICE_ROLES,
        internal_api_id=INTERNAL_API_ID,
        internal_trust_lambda_context=True,
    )


# ------------------------------------------------------------------ backend services (AWS IAM)
#: Test-only values. NOT a real account, API or role.
TEST_ACCOUNT = "111122223333"
INTERNAL_API_ID = "testinternalapi"
#: role name -> scopes. The SEO role reads clinics; "accounts" also reads connected accounts.
SERVICE_ROLES: dict[str, dict[str, object]] = {
    f"arn:aws:iam::{TEST_ACCOUNT}:role/test-seo-role": {"name": "seo-agent", "scopes": ["clinics.read"]},
    f"arn:aws:iam::{TEST_ACCOUNT}:role/service-role/test-accounts-role": {
        "name": "accounts-agent",
        "scopes": ["clinics.read", "connected_accounts.read"],
    },
    f"arn:aws:iam::{TEST_ACCOUNT}:role/test-noscope-role": {"name": "noscope-agent", "scopes": []},
}


@pytest.fixture
def service_auth():  # type: ignore[no-untyped-def]
    """``service_auth("test-seo-role")`` -> the header the AWS Lambda Web Adapter adds for a request
    that API Gateway (REST API, AWS_IAM) let through from that role. ``api_id`` / ``account`` /
    ``user_arn`` override parts of it to test refusals."""

    def _auth(
        role_name: str,
        *,
        account: str = TEST_ACCOUNT,
        api_id: str = INTERNAL_API_ID,
        user_arn: str | None = None,
        identity: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        arn = user_arn or f"arn:aws:sts::{account}:assumed-role/{role_name}/session-1"
        context: dict[str, Any] = {
            "apiId": api_id,
            "stage": "dev",
            "requestId": str(uuid.uuid4()),
            "identity": identity if identity is not None else {"accountId": account, "userArn": arn},
        }
        return {"x-amzn-request-context": json.dumps(context)}

    return _auth


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def secret_store() -> InMemorySecretStore:
    return InMemorySecretStore()


@pytest.fixture
def oauth_client() -> FakeOAuthClient:
    return FakeOAuthClient()


@pytest.fixture
def userinfo() -> FakeUserInfo:
    return FakeUserInfo()


@pytest.fixture
def directory() -> FakeIdentityDirectory:
    return FakeIdentityDirectory()


@pytest.fixture
def client(
    settings: Settings,
    engine: Engine,
    session_factory: sessionmaker[Session],
    verifier: CognitoTokenVerifier,
    storage: InMemoryStorage,
    userinfo: FakeUserInfo,
    directory: FakeIdentityDirectory,
    secret_store: InMemorySecretStore,
    oauth_client: FakeOAuthClient,
) -> Iterator[TestClient]:
    application = create_app(settings)

    def _db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    application.dependency_overrides.update(
        {
            get_db: _db,
            get_engine: lambda: engine,
            get_token_verifier: lambda: verifier,
            get_userinfo_client: lambda: userinfo,
            get_storage: lambda: storage,
            get_optional_storage: lambda: storage,
            get_secret_store: lambda: secret_store,
            get_oauth_client: lambda: oauth_client,
            get_identity_directory: lambda: directory,
            settings_dependency: lambda: settings,
        }
    )
    with TestClient(application) as tc:
        yield tc


@pytest.fixture
def auth(make_token):  # type: ignore[no-untyped-def]
    """``auth(user)`` -> Authorization header for that user (their cognito_sub must be set)."""

    def _auth(user: Any, **claims: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(user.cognito_sub, **claims)}"}

    return _auth


def new_sub() -> str:
    return str(uuid.uuid4())
