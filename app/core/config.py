"""Application settings.

All configuration comes from environment variables (12-factor). Nothing
environment-specific is hard-coded. In AWS, the ECS task definition injects:

* plain values (APP_ENV, COGNITO_*, S3_ASSETS_BUCKET, ...) as environment variables
* API: DB_USER=radial_api_iam with DB_IAM_AUTH=true —
  no database password at all (short-lived IAM tokens, see app/db/session.py)
* the one-off MIGRATE task only: DB_USER/DB_PASSWORD from the Aurora-managed master secret

Locally, values come from ``.env`` in the repo root (git-ignored; copy ``.env.example``).
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

AppEnv = Literal["local", "test", "dev", "prod"]
#: A service's name in audit rows and logs, e.g. "seo-agent".
SERVICE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- runtime --------------------------------------------------------------
    app_env: AppEnv = "local"
    debug: bool = False
    log_level: str = "INFO"
    service_name: str = "radial-pulse-api"
    service_version: str = Field(default="0.1.0", description="Set to the git SHA by CI/CD.")
    #: Show /docs and /openapi.json. Defaults to on for local/dev, off for prod.
    docs_enabled: bool | None = None

    # ---- database -------------------------------------------------------------
    #: Full URL wins if set (local/test). Otherwise built from DB_* parts (AWS).
    #: This is the APPLICATION login (member of the non-owner `radial_app` role, subject to RLS).
    database_url: SecretStr | None = None
    #: Owner login used ONLY by Alembic (local dev). Falls back to database_url / DB_* parts.
    migration_database_url: SecretStr | None = None
    #: Use AWS IAM database authentication (Aurora) instead of a password.
    db_iam_auth: bool = False
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "radial_pulse"
    db_user: str | None = None
    db_password: SecretStr | None = None
    db_sslmode: Literal["disable", "prefer", "require", "verify-full"] = "prefer"
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_recycle_seconds: int = 1800
    db_echo: bool = False

    # ---- HTTP -----------------------------------------------------------------
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # ---- auth (Cognito) -------------------------------------------------------
    cognito_region: str | None = None
    cognito_user_pool_id: str | None = None
    #: USER app client ids allowed to call the API (web + mobile; public clients, Managed Login +
    #: PKCE). Comma-separated in env. Never a service client.
    cognito_app_client_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    #: Managed Login domain (https://...). Used to call /oauth2/userInfo on first sign-in.
    cognito_domain: str | None = None
    #: Zero-NAT Lambda (no internet): read the pool's JWKS from a copy in S3 (``s3://<bucket>/<key>``)
    #: kept fresh by a scheduled Lambda outside the VPC (central-jwks-sync-dev.yaml). Empty = fetch
    #: the JWKS from Cognito directly (needs internet). The token checks are the same either way.
    cognito_jwks_s3_uri: str | None = None
    jwks_cache_seconds: int = 3600
    #: Clock skew allowance when checking exp/iat.
    jwt_leeway_seconds: int = 30

    # ---- backend services on /api/v1/internal (AWS IAM, see app/core/iam_caller.py) ----
    #: Other teams' backends allowed on /api/v1/internal, by IAM ROLE (copy the exact ARN from IAM,
    #: including any path). JSON: {"arn:aws:iam::<account>:role/<name>": {"name": "seo-agent",
    #: "scopes": ["clinics.read"]}}. API Gateway (AWS_IAM + Central's resource policy) lets only
    #: signed calls from allowed roles through; this list decides which routes each role may use.
    internal_service_roles: Annotated[dict[str, dict[str, object]], NoDecode] = Field(default_factory=dict)
    #: Id of the separate REST API that serves /api/v1/internal (requests from any other API,
    #: e.g. the people's HTTP API, are refused).
    internal_api_id: str | None = None
    #: Read the caller from the Lambda Web Adapter's x-amzn-request-context header. Set to true
    #: ONLY on the Lambda function (behind the adapter); anywhere else the header could be faked.
    internal_trust_lambda_context: bool = False

    # ---- storage (S3) ---------------------------------------------------------
    aws_region: str = "ap-south-1"
    s3_assets_bucket: str | None = None
    s3_kms_key_id: str | None = None
    s3_presign_ttl_seconds: int = 300
    # ---------------------------------------------------------------- invites
    #: Where sign-in accounts live (app/integrations/identity_directory.py).
    #: "log" = change nothing (local/tests); "cognito" = create/disable Cognito users (AWS).
    #: Cognito itself emails the invite (temporary password) — its message is set in the console.
    identity_directory_backend: Literal["log", "cognito"] = "log"

    # ------------------------------------------------------- connected accounts (OAuth)
    #: Frontend addresses the platforms may send the clinic back to after "Connect"
    #: (comma-separated; each must also be registered with the platform). Anything else is refused.
    oauth_redirect_uris: Annotated[list[str], NoDecode] = Field(default_factory=list)
    #: How long a started "Connect" stays valid.
    oauth_state_ttl_seconds: int = Field(default=600, ge=60, le=3600)
    #: Each platform's app credentials. Empty = that platform shows "not set up yet".
    #: The secrets come from Secrets Manager (ECS injects them); never put them in .env files you share.
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: SecretStr | None = None
    meta_app_id: str | None = None
    meta_app_secret: SecretStr | None = None
    linkedin_client_id: str | None = None
    linkedin_client_secret: SecretStr | None = None
    x_client_id: str | None = None
    x_client_secret: SecretStr | None = None
    #: Tokens are saved as Secrets Manager secrets named <prefix>/<env>/connections/<clinic>/<platform>.
    connection_secrets_prefix: str = "radial-pulse"
    connection_secrets_kms_key_id: str | None = None

    # --------------------------------------------------------------- validators
    @field_validator("cors_allowed_origins", "cognito_app_client_ids", "oauth_redirect_uris", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("internal_service_roles", mode="before")
    @classmethod
    def _parse_service_roles(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    'INTERNAL_SERVICE_ROLES must be JSON: {"<role ARN>": {"name": "...", "scopes": [...]}}'
                ) from exc
        return value

    @field_validator("cognito_jwks_s3_uri", mode="before")
    @classmethod
    def _check_jwks_s3_uri(cls, value: object) -> object:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            bucket, _, key = text.removeprefix("s3://").partition("/")
            if not text.startswith("s3://") or not bucket or not key:
                raise ValueError("COGNITO_JWKS_S3_URI must look like s3://<bucket>/<key>")
            return text
        return value

    @model_validator(mode="after")
    def _environment_rules(self) -> Settings:
        if self.app_env == "prod":
            if self.debug:
                raise ValueError("DEBUG must be false in prod")
            if "*" in self.cors_allowed_origins:
                raise ValueError("Wildcard CORS is not allowed in prod")
            if any(o.startswith("http://") for o in self.cors_allowed_origins):
                raise ValueError("Prod CORS origins must be https")
            if self.db_sslmode not in ("require", "verify-full"):
                raise ValueError("Prod database connections must use TLS (DB_SSLMODE=require|verify-full)")
            if any(uri.startswith("http://") for uri in self.oauth_redirect_uris):
                raise ValueError("Prod OAuth redirect addresses must be https (or the mobile app's scheme)")
        if self.app_env in ("dev", "prod") and not self.auth_configured:
            raise ValueError("COGNITO_REGION, COGNITO_USER_POOL_ID and COGNITO_APP_CLIENT_IDS are required")
        if self.identity_directory_backend == "cognito" and not (
            self.cognito_region and self.cognito_user_pool_id
        ):
            raise ValueError(
                "IDENTITY_DIRECTORY_BACKEND=cognito needs COGNITO_REGION and COGNITO_USER_POOL_ID"
            )
        if self.app_env == "prod" and self.identity_directory_backend != "cognito":
            raise ValueError(
                "IDENTITY_DIRECTORY_BACKEND must be cognito in prod (invites create Cognito users)"
            )
        if (
            self.app_env in ("dev", "prod")
            and self.internal_trust_lambda_context
            and not os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
        ):
            # The x-amzn-request-context header is only safe behind the Lambda Web Adapter.
            raise ValueError("INTERNAL_TRUST_LAMBDA_CONTEXT=true is only allowed on AWS Lambda")
        self._check_service_roles()
        return self

    def _check_service_roles(self) -> None:
        """Every entry: a real role ARN, a clean unique name, known scopes. Roles need the API id."""
        from app.core.iam_caller import role_key
        from app.core.rbac import ServiceScope

        if not self.internal_service_roles:
            return
        if not self.internal_api_id:
            raise ValueError("INTERNAL_SERVICE_ROLES needs INTERNAL_API_ID")
        known = {scope.value for scope in ServiceScope}
        names: list[str] = []
        keys: set[tuple[str, str]] = set()
        for role_arn, entry in self.internal_service_roles.items():
            try:
                key = role_key(role_arn)
            except ValueError as exc:
                raise ValueError(f"INTERNAL_SERVICE_ROLES: {exc}") from exc
            if key in keys:
                raise ValueError("INTERNAL_SERVICE_ROLES lists the same role twice")
            keys.add(key)
            name, scopes = entry.get("name"), entry.get("scopes", [])
            if not isinstance(name, str) or not SERVICE_NAME.match(name):
                raise ValueError("INTERNAL_SERVICE_ROLES names use lower-case letters, digits and '-'")
            if not isinstance(scopes, list) or not all(isinstance(s, str) and s in known for s in scopes):
                raise ValueError(f"INTERNAL_SERVICE_ROLES scopes must be from: {sorted(known)}")
            names.append(name)
        if len(set(names)) != len(names):
            raise ValueError("Each role in INTERNAL_SERVICE_ROLES needs its own name")

    # ------------------------------------------------------------ derived values
    @property
    def auth_configured(self) -> bool:
        return bool(self.cognito_region and self.cognito_user_pool_id and self.cognito_app_client_ids)

    @property
    def internal_auth_configured(self) -> bool:
        """/api/v1/internal works only behind the adapter, with roles and our API id set."""
        return bool(
            self.internal_trust_lambda_context and self.internal_api_id and self.internal_service_roles
        )

    @property
    def cognito_issuer(self) -> str | None:
        if not (self.cognito_region and self.cognito_user_pool_id):
            return None
        return f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"

    @property
    def cognito_jwks_url(self) -> str | None:
        issuer = self.cognito_issuer
        return f"{issuer}/.well-known/jwks.json" if issuer else None

    @property
    def cognito_jwks_s3(self) -> tuple[str, str] | None:
        """(bucket, key) of the S3 copy of the JWKS, or None to read Cognito directly."""
        if not self.cognito_jwks_s3_uri:
            return None
        bucket, _, key = self.cognito_jwks_s3_uri.removeprefix("s3://").partition("/")
        return bucket, key

    @property
    def show_docs(self) -> bool:
        if self.docs_enabled is not None:
            return self.docs_enabled
        return self.app_env in ("local", "test", "dev")

    @property
    def sqlalchemy_url(self) -> URL:
        """Database URL. Never log this — it contains the password."""
        if self.database_url is not None:
            return make_url(self.database_url.get_secret_value())
        if not (self.db_host and self.db_user and (self.db_password or self.db_iam_auth)):
            raise RuntimeError(
                "Database is not configured: set DATABASE_URL, or DB_HOST + DB_USER + "
                "DB_PASSWORD (or DB_IAM_AUTH=true)"
            )
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.db_user,
            # With IAM auth the password is a short-lived token injected per connection.
            password=self.db_password.get_secret_value() if self.db_password else None,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"sslmode": self.db_sslmode},
        )

    @property
    def sqlalchemy_migration_url(self) -> URL:
        """Owner connection for Alembic. Never used by the running API."""
        if self.migration_database_url is not None:
            return make_url(self.migration_database_url.get_secret_value())
        return self.sqlalchemy_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
