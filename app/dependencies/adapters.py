from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.errors import ServiceUnavailableError
from app.integrations.identity_directory import (
    CognitoIdentityDirectory,
    IdentityDirectory,
    LoggingIdentityDirectory,
)
from app.integrations.oauth import HttpxOAuthClient, OAuthClient
from app.integrations.secrets import AwsSecretStore, SecretStore
from app.integrations.storage import ObjectStorage, S3ObjectStorage


def settings_dependency() -> Settings:
    return get_settings()


@lru_cache
def get_storage() -> ObjectStorage:
    settings = get_settings()
    if not settings.s3_assets_bucket:
        raise ServiceUnavailableError("Asset storage is not configured (S3_ASSETS_BUCKET)")
    return S3ObjectStorage(bucket=settings.s3_assets_bucket, region=settings.aws_region)


def get_optional_storage() -> ObjectStorage | None:
    """Storage when it is set up, else None (for screens that work without it, like /auth/me)."""
    if not get_settings().s3_assets_bucket:
        return None
    return get_storage()


@lru_cache
def get_identity_directory() -> IdentityDirectory:
    """Sign-in accounts (Cognito). Settings validation guarantees the pool for "cognito"."""
    settings = get_settings()
    if settings.identity_directory_backend == "cognito" and settings.cognito_user_pool_id:
        return CognitoIdentityDirectory(settings.cognito_user_pool_id, settings.cognito_region or "")
    return LoggingIdentityDirectory()


@lru_cache
def get_secret_store() -> SecretStore:
    settings = get_settings()
    return AwsSecretStore(settings.aws_region, settings.connection_secrets_kms_key_id)


@lru_cache
def get_oauth_client() -> OAuthClient:
    return HttpxOAuthClient()
