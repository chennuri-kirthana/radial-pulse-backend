"""Test harness.

Database:
* default: a fresh in-memory SQLite per test (fast; used by `make test`)
* if TEST_DATABASE_URL is set (PostgreSQL): schema built with the REAL Alembic
  migrations once, tables truncated after each test (used by `make integration-test` and CI)

Auth: real JWT verification with a test RSA key pair — the verifier is the production
class; only its key source is swapped. There is no auth bypass.
"""

from __future__ import annotations

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
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import Settings
from app.core.security import CognitoTokenVerifier
from app.db.base import Base
from app.db.session import get_engine
from app.dependencies.adapters import (
    get_invite_sender,
    get_job_queue,
    get_oauth_client,
    get_optional_storage,
    get_secret_store,
    get_storage,
    settings_dependency,
)
from app.dependencies.auth import get_token_verifier, get_userinfo_client
from app.dependencies.db import get_db
from app.integrations.cognito import UserInfo
from app.integrations.invites import Invite
from app.integrations.oauth import OAuthError, OAuthProvider, TokenSet
from app.integrations.storage import ObjectInfo
from app.jobs.queue import InMemoryJobQueue
from app.main import create_app

API_ROOT = Path(__file__).resolve().parents[1]
ISSUER = "https://cognito-idp.ap-south-1.amazonaws.com/ap-south-1_TEST"
WEB_CLIENT_ID = "test-web-client"
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
APP_TEST_USER = "radial_app_test"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="needs PostgreSQL: set TEST_DATABASE_URL (make integration-test)")
    for item in items:
        if "integration" in item.keywords:
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
            "scope": "openid email profile",
            "iat": now,
            "exp": now + 600,
            "username": f"google_{sub}",
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
class RecordingInvites:
    """Test double for the invite email sender. Set ``fail = True`` to simulate an outage."""

    sent: list[Invite] = field(default_factory=list)
    fail: bool = False

    def send(self, invite: Invite) -> None:
        if self.fail:
            raise RuntimeError("email service down")
        self.sent.append(invite)


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
def _v1_media_taxonomy() -> list[tuple[str, str, str]]:
    """The V1 media labels, read from migration 0013 itself (the one source of the values)."""
    import importlib.util

    path = API_ROOT / "alembic" / "versions" / "20261005_0013_media_review_security.py"
    spec = importlib.util.spec_from_file_location("migration_0013", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.V1_TAXONOMY)


def seed_media_taxonomy(conn: Any) -> None:
    """Put the V1 media labels in (the migration does it on PostgreSQL; tests truncate tables)."""
    order: dict[str, int] = {}
    for dimension, code, label in _v1_media_taxonomy():
        order[dimension] = order.get(dimension, -1) + 1
        conn.execute(
            text(
                "INSERT INTO media_taxonomy (id, dimension, code, label, sort_order, is_active) "
                "VALUES (:id, :dimension, :code, :label, :sort_order, :active)"
            ),
            {"id": uuid.uuid4().hex if conn.dialect.name == "sqlite" else uuid.uuid4(),
             "dimension": dimension, "code": code, "label": label, "sort_order": order[dimension],
             "active": True},
        )  # fmt: skip


def _sqlite_engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):  # type: ignore[no-untyped-def]
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        seed_media_taxonomy(conn)
    return engine


@pytest.fixture(scope="session")
def postgres_engines() -> Iterator[tuple[Engine, Engine] | None]:
    """(owner_engine, app_engine) on PostgreSQL, or None on the SQLite fast path.

    The owner builds the schema with the REAL migrations (like production). The API under
    test connects as a NON-owner member of `radial_app`, so row-level security is enforced
    exactly as in AWS.
    """
    if not TEST_DATABASE_URL:
        yield None
        return
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.engine import make_url

    owner = create_engine(TEST_DATABASE_URL, future=True)
    with owner.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "alembic"))
    with owner.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")  # the real migrations build the test schema
    with owner.begin() as conn:
        conn.execute(
            text(
                f"""
                DO $$ BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_TEST_USER}') THEN
                    CREATE ROLE {APP_TEST_USER} LOGIN PASSWORD '{APP_TEST_USER}' IN ROLE radial_app;
                  END IF;
                END $$;
                """
            )
        )
    app_url = make_url(TEST_DATABASE_URL).set(username=APP_TEST_USER, password=APP_TEST_USER)
    app = create_engine(app_url, future=True)
    yield owner, app
    app.dispose()
    owner.dispose()


@pytest.fixture
def engines(postgres_engines: tuple[Engine, Engine] | None) -> Iterator[tuple[Engine, Engine]]:
    """(owner_engine, app_engine). On SQLite both are the same fresh in-memory database."""
    if postgres_engines is None:
        eng = _sqlite_engine()
        yield eng, eng
        eng.dispose()
        return
    owner, app = postgres_engines
    yield owner, app
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    with owner.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))
        # The one platform_settings row is created by migration 0010; put it back.
        conn.execute(
            text(
                "INSERT INTO platform_settings (id, organization_name, timezone, date_format) "
                "VALUES (1, 'Radial Pulse', 'Asia/Kolkata', 'DD MMM YYYY')"
            )
        )
        # The V1 media labels are created by migration 0013; put them back too.
        seed_media_taxonomy(conn)


@pytest.fixture
def engine(engines: tuple[Engine, Engine]) -> Engine:
    """The APPLICATION engine (non-owner on PostgreSQL → row-level security applies)."""
    return engines[1]


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Sessions as the application sees them (used by the API under test and the worker)."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(engines: tuple[Engine, Engine]) -> Iterator[Session]:
    """An OWNER session for arranging test data and asserting on results (bypasses RLS)."""
    session = sessionmaker(bind=engines[0], autoflush=False, expire_on_commit=False)()
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
        max_upload_bytes=10 * 1024 * 1024,
        cors_allowed_origins=["http://localhost:5173"],
        job_queue_backend="memory",
        # Connected accounts: Google and Meta "set up", LinkedIn and X not (fake credentials).
        oauth_redirect_uris=[OAUTH_REDIRECT],
        google_oauth_client_id="google-client",
        google_oauth_client_secret="google-secret",
        meta_app_id="meta-app",
        meta_app_secret="meta-secret",
    )


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def job_queue() -> InMemoryJobQueue:
    return InMemoryJobQueue()


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
def invites() -> RecordingInvites:
    return RecordingInvites()


@pytest.fixture
def client(
    settings: Settings,
    engine: Engine,
    session_factory: sessionmaker[Session],
    verifier: CognitoTokenVerifier,
    storage: InMemoryStorage,
    userinfo: FakeUserInfo,
    job_queue: InMemoryJobQueue,
    invites: RecordingInvites,
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
            get_job_queue: lambda: job_queue,
            get_invite_sender: lambda: invites,
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
