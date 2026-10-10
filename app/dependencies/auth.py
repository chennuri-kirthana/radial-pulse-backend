"""Authentication dependency: Bearer token → verified claims → ``Principal`` (CLAUDE.md rule 6)."""

from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ServiceUnavailableError, UnauthorizedError
from app.core.logging import user_id_ctx
from app.core.rbac import Principal
from app.core.security import (
    CognitoTokenVerifier,
    JwksSigningKeyResolver,
    S3JwksSigningKeyResolver,
    SigningKeyResolver,
    TokenVerificationError,
)
from app.dependencies.db import get_db
from app.integrations.cognito import CognitoUserInfoClient, UserInfoClient
from app.services import identity

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False, description="Cognito access token")


@lru_cache
def get_token_verifier() -> CognitoTokenVerifier:
    settings = get_settings()
    if not settings.auth_configured or not settings.cognito_issuer or not settings.cognito_jwks_url:
        # No fallback, no fake auth: without Cognito settings, protected endpoints are unavailable.
        raise ServiceUnavailableError("Authentication is not configured for this environment")
    resolver: SigningKeyResolver
    if settings.cognito_jwks_s3:
        # Zero-NAT Lambda: the JWKS copy in S3 (see S3JwksSigningKeyResolver). Same checks after that.
        bucket, key = settings.cognito_jwks_s3
        resolver = S3JwksSigningKeyResolver(bucket, key, settings.aws_region, settings.jwks_cache_seconds)
    else:
        resolver = JwksSigningKeyResolver(settings.cognito_jwks_url, settings.jwks_cache_seconds)
    return CognitoTokenVerifier(
        issuer=settings.cognito_issuer,
        allowed_client_ids=settings.cognito_app_client_ids,
        key_resolver=resolver,
        leeway_seconds=settings.jwt_leeway_seconds,
    )


@lru_cache
def get_userinfo_client() -> UserInfoClient | None:
    domain = get_settings().cognito_domain
    return CognitoUserInfoClient(domain) if domain else None


def get_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    verifier: CognitoTokenVerifier = Depends(get_token_verifier),
    userinfo: UserInfoClient | None = Depends(get_userinfo_client),
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()
    try:
        token = verifier.verify(credentials.credentials)
    except TokenVerificationError as exc:
        logger.info("token rejected", extra={"reason": str(exc)})
        raise UnauthorizedError("Invalid or expired token") from exc
    if not token.username:
        # A person's access token always names a user. Anything else is refused here. (Other teams'
        # backends don't use Cognito at all: they call /api/v1/internal with AWS IAM, see
        # app/dependencies/service_auth.py.)
        logger.info("token rejected", extra={"reason": "not a user token"})
        raise UnauthorizedError("Invalid or expired token")
    # From here on, every transaction of this request runs as this person (rp.user_id).
    principal = identity.resolve_principal(db, token, credentials.credentials, userinfo)
    user_id_ctx.set(str(principal.user_id))
    return principal
