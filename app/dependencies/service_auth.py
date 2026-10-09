"""Service authentication for /api/v1/internal (CLAUDE.md source 5): other teams' backends.

Decided 9 Oct 2026: backend services authenticate with **AWS IAM**, not Cognito.
(Cognito stays for people on every other route.)

* The service signs each request with its own IAM role (SigV4). API Gateway (a separate REST API
  with ``AWS_IAM`` on every method + Central's resource policy) refuses unsigned or unknown callers.
* Here we read who called from the Lambda Web Adapter's ``x-amzn-request-context`` header
  (``app/core/iam_caller.py``) and look the role up in ``INTERNAL_SERVICE_ROLES``.
* Each route needs one scope (``ServiceScope``); a role holds its scopes in ``INTERNAL_SERVICE_ROLES``.
* Every request runs as the database's READ-ONLY role: ``SET LOCAL ROLE radial_service``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ForbiddenError, ServiceUnavailableError, UnauthorizedError
from app.core.iam_caller import REQUEST_CONTEXT_HEADER, CallerRejectedError, ServiceRole, identify, role_key
from app.core.logging import user_id_ctx
from app.core.rbac import ServiceScope
from app.db.tenant import act_as_service
from app.dependencies.adapters import settings_dependency
from app.dependencies.db import get_db

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServiceCaller:
    """A verified backend service (an IAM role)."""

    name: str
    role_arn: str
    scopes: frozenset[ServiceScope]


def _role_index(settings: Settings) -> dict[tuple[str, str], tuple[str, ServiceRole]]:
    index: dict[tuple[str, str], tuple[str, ServiceRole]] = {}
    for role_arn, entry in settings.internal_service_roles.items():
        scopes = entry.get("scopes", [])
        scope_list = scopes if isinstance(scopes, list) else []  # Settings already checked the shape
        index[role_key(role_arn)] = (
            role_arn,
            ServiceRole(name=str(entry["name"]), scopes=frozenset(str(s) for s in scope_list)),
        )
    return index


def get_service_caller(request: Request, settings: Settings = Depends(settings_dependency)) -> ServiceCaller:
    if not settings.internal_auth_configured or not settings.internal_api_id:
        # No fallback: without the IAM setup, /internal is unavailable (never open).
        raise ServiceUnavailableError("Service authentication is not configured for this environment")
    try:
        caller = identify(
            request.headers.get(REQUEST_CONTEXT_HEADER),
            internal_api_id=settings.internal_api_id,
            roles=_role_index(settings),
        )
    except CallerRejectedError as exc:
        logger.info("internal caller rejected", extra={"reason": str(exc)})
        raise UnauthorizedError() from exc
    return ServiceCaller(
        name=caller.name,
        role_arn=caller.role_arn,
        scopes=frozenset(ServiceScope(s) for s in caller.scopes),
    )


def service_access(scope: ServiceScope) -> Callable[..., ServiceCaller]:
    """Not an allowed role → 401; role without ``scope`` → 403. Then the request's database
    session runs as the read-only role ``radial_service``."""

    def dependency(
        caller: ServiceCaller = Depends(get_service_caller), db: Session = Depends(get_db)
    ) -> ServiceCaller:
        if scope not in caller.scopes:
            raise ForbiddenError(f"Missing scope {scope.value}")
        act_as_service(db)
        user_id_ctx.set(f"service:{caller.name}")
        return caller

    return dependency
