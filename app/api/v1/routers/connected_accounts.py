"""Connected accounts: the clinic's own Google / Instagram / Facebook / LinkedIn / X logins."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.config import Settings
from app.core.rbac import ClinicContext, Permission
from app.dependencies.adapters import get_secret_store, settings_dependency
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.integrations.secrets import SecretStore
from app.schemas.connected_accounts import (
    ConnectedAccountRead,
    ConnectedAccountResourceRead,
    ConnectedAccountResourceSelect,
    ProviderRead,
)
from app.services import connected_accounts as service

router = APIRouter(
    prefix="/clinics/{clinic_id}/connected-accounts", tags=["connected accounts"], responses=ERRORS
)
_read = clinic_access(Permission.CONNECTED_ACCOUNTS_READ)
_manage = clinic_access(Permission.CONNECTED_ACCOUNTS_MANAGE)


@router.get("", response_model=list[ConnectedAccountRead])
def list_accounts(
    ctx: ClinicContext = Depends(_read), db: Session = Depends(get_db)
) -> list[ConnectedAccountRead]:
    """Admin, DSM, Clinic Administrator, Team Member (practitioners don't see them). No tokens, ever."""
    return service.list_accounts(db, ctx)


@router.get("/providers", response_model=list[ProviderRead], summary="Platforms and whether they are set up")
def providers(
    _: ClinicContext = Depends(_read), settings: Settings = Depends(settings_dependency)
) -> list[ProviderRead]:
    return service.providers(settings)


@router.post("/{account_id}/disconnect", response_model=ConnectedAccountRead)
def disconnect(
    account_id: UUID,
    ctx: ClinicContext = Depends(_manage),
    db: Session = Depends(get_db),
    store: SecretStore = Depends(get_secret_store),
) -> ConnectedAccountRead:
    """The token is deleted from Secrets Manager; the account's locations become free again."""
    return service.disconnect(db, ctx, account_id, store)


@router.get("/{account_id}/resources", response_model=list[ConnectedAccountResourceRead])
def list_resources(
    account_id: UUID, ctx: ClinicContext = Depends(_read), db: Session = Depends(get_db)
) -> list[ConnectedAccountResourceRead]:
    """Locations / sites / pages this login can manage."""
    return service.list_resources(db, ctx, account_id)


@router.put("/{account_id}/resources/{resource_id}", response_model=ConnectedAccountResourceRead)
def select_resource(
    account_id: UUID,
    resource_id: UUID,
    body: ConnectedAccountResourceSelect,
    ctx: ClinicContext = Depends(_manage),
    db: Session = Depends(get_db),
) -> ConnectedAccountResourceRead:
    """Choose (or un-choose) the location this clinic uses. Each one can be chosen by ONE clinic (409)."""
    return service.select_resource(db, ctx, account_id, resource_id, body)
