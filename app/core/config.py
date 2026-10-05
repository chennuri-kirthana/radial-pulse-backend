"""Application settings.

All configuration comes from environment variables (12-factor). Nothing
environment-specific is hard-coded. In AWS, the ECS task definition injects:

* plain values (APP_ENV, COGNITO_*, S3_ASSETS_BUCKET, JOB_QUEUE_URL, ...) as environment variables
* API and worker: DB_USER=radial_api_iam / radial_worker_iam with DB_IAM_AUTH=true —
  no database password at all (short-lived IAM tokens, see app/db/session.py)
* the one-off MIGRATE task only: DB_USER/DB_PASSWORD from the Aurora-managed master secret

Locally, values come from ``.env`` in the repo root (git-ignored; copy ``.env.example``).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

AppEnv = Literal["local", "test", "dev", "prod"]


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
    #: App client ids allowed to call the API (web + mobile). Comma-separated in env.
    cognito_app_client_ids: Annotated[list[str], NoDecode] = Field(default_factory=list)
    #: Hosted UI domain (https://...). Used to call /oauth2/userInfo on first sign-in.
    cognito_domain: str | None = None
    jwks_cache_seconds: int = 3600
    #: Clock skew allowance when checking exp/iat.
    jwt_leeway_seconds: int = 30

    # ---- storage (S3) ---------------------------------------------------------
    aws_region: str = "ap-south-1"
    s3_assets_bucket: str | None = None
    s3_kms_key_id: str | None = None
    s3_presign_ttl_seconds: int = 300
    #: The largest file of ANY type (videos use this one). The limits below are per file type
    #: and can only make it smaller.
    max_upload_bytes: int = 200 * 1024 * 1024  # 200 MB
    max_image_upload_bytes: int = 25 * 1024 * 1024  # 25 MB: photos, logos
    max_audio_upload_bytes: int = 50 * 1024 * 1024  # 50 MB: voice samples
    max_document_upload_bytes: int = 50 * 1024 * 1024  # 50 MB: PDF / HTML / JSON
    #: Uploads never confirmed after this many hours are cleaned up (``app.cli cleanup-stale-uploads``).
    stale_upload_hours: int = 24

    # ---- background jobs ------------------------------------------------------
    #: "sqs" in AWS; "database" locally (the worker polls background_jobs); "memory" in tests.
    job_queue_backend: Literal["sqs", "database", "memory"] = "database"
    job_queue_url: str | None = None
    #: SQS long-poll wait and how long a received message stays invisible while we work on it.
    job_queue_wait_seconds: int = 20
    job_visibility_timeout_seconds: int = 900
    #: Version label of the assessment METHODOLOGY (component set + scoring). Product-owned.
    assessment_methodology_version: str = "2026.09-v0"

    # ---------------------------------------------------------------- invites
    #: "log" = do not send (local/tests/until SES is ready); "ses" = Amazon SES v2.
    invite_email_backend: Literal["log", "ses"] = "log"
    #: Verified SES sender, e.g. "Radial Pulse <no-reply@radialpulse.com>". Required for "ses".
    invite_from_email: str | None = None
    #: Where invited people sign in (the web app). Mobile users use the app itself.
    app_sign_in_url: str = "http://localhost:4200/sign-in"

    # ---------------------------------------------------------------- archiving
    #: S3 bucket for archived rows (old metric snapshots and audit events). Empty = local folder.
    archive_bucket: str | None = None
    #: Folder used instead of S3 when ``archive_bucket`` is empty (local development only).
    archive_local_dir: str = ".archive"
    #: Keep this many days in the database; older rows move to the archive.
    archive_metrics_after_days: int = Field(default=180, ge=30)
    archive_audit_after_days: int = Field(default=365, ge=90)

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
        if self.job_queue_backend == "sqs" and not self.job_queue_url:
            raise ValueError("JOB_QUEUE_URL is required when JOB_QUEUE_BACKEND=sqs")
        if self.invite_email_backend == "ses" and not self.invite_from_email:
            raise ValueError("INVITE_FROM_EMAIL is required when INVITE_EMAIL_BACKEND=ses")
        return self

    # ------------------------------------------------------------ derived values
    @property
    def auth_configured(self) -> bool:
        return bool(self.cognito_region and self.cognito_user_pool_id and self.cognito_app_client_ids)

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
