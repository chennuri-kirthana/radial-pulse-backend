from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.errors import ServiceUnavailableError
from app.integrations.invites import InviteSender, LoggingInviteSender, SesInviteSender
from app.integrations.oauth import HttpxOAuthClient, OAuthClient
from app.integrations.secrets import AwsSecretStore, SecretStore
from app.integrations.storage import ObjectStorage, S3ObjectStorage
from app.jobs.queue import DatabaseJobQueue, JobQueue, SqsJobQueue


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
def get_job_queue() -> JobQueue:
    settings = get_settings()
    if settings.job_queue_backend == "sqs" and settings.job_queue_url:
        return SqsJobQueue(settings.job_queue_url, settings.aws_region)
    if settings.job_queue_backend == "database":
        return DatabaseJobQueue()
    raise ServiceUnavailableError("Background jobs are not configured (JOB_QUEUE_BACKEND)")


@lru_cache
def get_invite_sender() -> InviteSender:
    settings = get_settings()
    if settings.invite_email_backend == "ses" and settings.invite_from_email:
        return SesInviteSender(settings.invite_from_email, settings.aws_region)
    return LoggingInviteSender()


@lru_cache
def get_secret_store() -> SecretStore:
    settings = get_settings()
    return AwsSecretStore(settings.aws_region, settings.connection_secrets_kms_key_id)


@lru_cache
def get_oauth_client() -> OAuthClient:
    return HttpxOAuthClient()
