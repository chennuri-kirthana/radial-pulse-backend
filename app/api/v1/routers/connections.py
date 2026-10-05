"""Connected accounts: "Connect Your Accounts" (mobile onboarding) and "Connected Accounts" (profile).

How the app uses it:
  1. ``GET …/connections`` — every platform with its status (show all cards).
  2. Connect: ``POST …/connections/{platform}/start`` with the app's redirect address → open
     ``authorization_url``. The platform sends the clinic back to that address with ``code`` and
     ``state`` → ``POST …/connections/{platform}/complete`` with both.
  3. ``POST …/connections/{platform}/disconnect``.

The website is not here: it needs no sign-in (edit it on the clinic or its presence profiles).
Numbers for the Social Media screen come from ``GET …/snapshots?source=instagram&latest=true``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, ErrorResponses
from app.core.config import Settings
from app.core.enums import ConnectionPlatform
from app.core.errors import ProblemDetails
from app.core.rbac import ClinicContext, Permission
from app.dependencies.adapters import get_oauth_client, get_secret_store, settings_dependency
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.integrations.oauth import OAuthClient
from app.integrations.secrets import SecretStore
from app.schemas.connections import (
    ConnectionCompleteRequest,
    ConnectionRead,
    ConnectionStartRequest,
    ConnectionStartResponse,
)
from app.services import connections as service

router = APIRouter(prefix="/clinics/{clinic_id}/connections", tags=["connections"], responses=ERRORS)

_NOT_SET_UP: ErrorResponses = {
    503: {"model": ProblemDetails, "description": "This platform is not set up yet"}
}
_STATE: ErrorResponses = {
    409: {"model": ProblemDetails, "description": "No sign-in in progress, or it took too long"}
}
_UPSTREAM: ErrorResponses = {
    502: {"model": ProblemDetails, "description": "The platform refused the sign-in"}
}


@router.get("", response_model=list[ConnectionRead], summary="Every platform with its connection status")
def list_connections(
    ctx: ClinicContext = Depends(clinic_access(Permission.CONNECTIONS_READ)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
) -> list[ConnectionRead]:
    return service.list_connections(db, ctx, settings)


@router.get("/{platform}", response_model=ConnectionRead)
def get_connection(
    platform: ConnectionPlatform,
    ctx: ClinicContext = Depends(clinic_access(Permission.CONNECTIONS_READ)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
) -> ConnectionRead:
    return service.get_connection(db, ctx, platform, settings)


@router.post(
    "/{platform}/start",
    response_model=ConnectionStartResponse,
    responses=_NOT_SET_UP,
    summary="Start Connect: returns the platform's sign-in address",
)
def start(
    platform: ConnectionPlatform,
    body: ConnectionStartRequest,
    ctx: ClinicContext = Depends(clinic_access(Permission.CONNECTIONS_MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
) -> ConnectionStartResponse:
    return service.start(db, ctx, platform, body, settings)


@router.post(
    "/{platform}/complete",
    response_model=ConnectionRead,
    responses={**_NOT_SET_UP, **_STATE, **_UPSTREAM},
    summary="Finish Connect with the code + state the platform returned",
)
def complete(
    platform: ConnectionPlatform,
    body: ConnectionCompleteRequest,
    ctx: ClinicContext = Depends(clinic_access(Permission.CONNECTIONS_MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
    oauth: OAuthClient = Depends(get_oauth_client),
    store: SecretStore = Depends(get_secret_store),
) -> ConnectionRead:
    return service.complete(db, ctx, platform, body, settings, oauth, store)


@router.post(
    "/{platform}/disconnect", response_model=ConnectionRead, summary="Disconnect and delete the stored tokens"
)
def disconnect(
    platform: ConnectionPlatform,
    ctx: ClinicContext = Depends(clinic_access(Permission.CONNECTIONS_MANAGE)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
    store: SecretStore = Depends(get_secret_store),
) -> ConnectionRead:
    return service.disconnect(db, ctx, platform, settings, store)
