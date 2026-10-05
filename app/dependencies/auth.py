"""Authentication dependency: Bearer token → verified claims → ``Principal``."""

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
from app.core.security import CognitoTokenVerifier, JwksSigningKeyResolver, TokenVerificationError
from app.db.tenant import set_tenant_scope
from app.dependencies.db import get_db
from app.integrations.cognito import CognitoUserInfoClient, UserInfoClient
from app.services import identity

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False, description="Cognito access token (Authorization Code + PKCE)")


@lru_cache
def get_token_verifier() -> CognitoTokenVerifier:
    settings = get_settings()
    if not settings.auth_configured or not settings.cognito_issuer or not settings.cognito_jwks_url:
        # No fallback, no fake auth: without Cognito settings, protected endpoints are unavailable.
        raise ServiceUnavailableError("Authentication is not configured for this environment")
    return CognitoTokenVerifier(
        issuer=settings.cognito_issuer,
        allowed_client_ids=settings.cognito_app_client_ids,
        key_resolver=JwksSigningKeyResolver(settings.cognito_jwks_url, settings.jwks_cache_seconds),
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
    principal = identity.resolve_principal(db, token, credentials.credentials, userinfo)
    user_id_ctx.set(str(principal.user_id))
    # Database row-level security: this request may only see the caller's clinics.
    # (clinic_access() narrows it further to the ONE clinic in the URL.)
    set_tenant_scope(db, principal.accessible_clinic_ids())
    return principal
