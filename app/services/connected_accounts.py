"""Connected accounts (docs/01-decisions.md section 11).

Built now: list the clinic's accounts and the platforms, disconnect, and choose which location /
site / page of an account this clinic uses (each can be selected by only ONE clinic → 409).

Not built yet: starting and finishing a new "Connect" (OAuth). It waits for open question Q3
(which Google / Meta products and permissions). The OAuth helpers stay in
app/integrations/oauth.py. When it is built: ``oauth_states`` keeps only the HASH of ``state``,
expires in 10 minutes, only the person who started may finish, tokens go to Secrets Manager and
the database keeps only ``secret_ref`` (CLAUDE.md rule 10).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import ConnectedAccountProvider, ConnectedAccountStatus
from app.core.errors import ConflictError, NotFoundError, UpstreamError
from app.core.rbac import ClinicContext
from app.db.base import utcnow
from app.integrations.oauth import PLATFORM_LABELS, PLATFORM_PROVIDER, configured_providers
from app.integrations.secrets import SecretStore
from app.models import ConnectedAccount, ConnectedAccountResource
from app.schemas.connected_accounts import (
    ConnectedAccountRead,
    ConnectedAccountResourceRead,
    ConnectedAccountResourceSelect,
    ProviderRead,
)
from app.services import audit


def providers(settings: Settings) -> list[ProviderRead]:
    ready = configured_providers(settings)
    return [
        ProviderRead(provider=p, label=PLATFORM_LABELS[p], available=PLATFORM_PROVIDER[p] in ready)
        for p in ConnectedAccountProvider
    ]


def list_accounts(session: Session, ctx: ClinicContext) -> list[ConnectedAccountRead]:
    rows = session.scalars(
        select(ConnectedAccount)
        .where(ConnectedAccount.clinic_id == ctx.clinic_id)
        .order_by(ConnectedAccount.provider, ConnectedAccount.created_at)
    )
    return [ConnectedAccountRead.model_validate(r) for r in rows]


def disconnect(
    session: Session, ctx: ClinicContext, account_id: UUID, store: SecretStore
) -> ConnectedAccountRead:
    account = _account(session, ctx, account_id)
    if account.status == ConnectedAccountStatus.DISCONNECTED:
        raise ConflictError("This account is already disconnected.")
    if account.secret_ref:
        try:
            store.delete(account.secret_ref)  # the token is removed from Secrets Manager
        except Exception as exc:
            raise UpstreamError("The saved sign-in could not be removed. Please try again.") from exc
    account.status = ConnectedAccountStatus.DISCONNECTED
    account.secret_ref = None
    account.token_expires_at = None
    account.disconnected_at = utcnow()
    for resource in session.scalars(
        select(ConnectedAccountResource).where(ConnectedAccountResource.connected_account_id == account.id)
    ):
        resource.is_selected = False  # a disconnected account's locations are free for other clinics
    session.flush()
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="connected_account.disconnected",
        resource_type="connected_account",
        resource_id=account.id,
        clinic_id=ctx.clinic_id,
        details={"provider": account.provider.value},
    )
    session.commit()
    session.refresh(account)
    return ConnectedAccountRead.model_validate(account)


def list_resources(
    session: Session, ctx: ClinicContext, account_id: UUID
) -> list[ConnectedAccountResourceRead]:
    _account(session, ctx, account_id)
    rows = session.scalars(
        select(ConnectedAccountResource)
        .where(ConnectedAccountResource.connected_account_id == account_id)
        .order_by(ConnectedAccountResource.resource_type, ConnectedAccountResource.display_name)
    )
    return [ConnectedAccountResourceRead.model_validate(r) for r in rows]


def select_resource(
    session: Session,
    ctx: ClinicContext,
    account_id: UUID,
    resource_id: UUID,
    body: ConnectedAccountResourceSelect,
) -> ConnectedAccountResourceRead:
    account = _account(session, ctx, account_id)
    resource = session.get(ConnectedAccountResource, resource_id)
    if resource is None or resource.connected_account_id != account.id:
        raise NotFoundError("Location / page not found")
    if body.is_selected and account.status != ConnectedAccountStatus.CONNECTED:
        raise ConflictError("Reconnect the account first.")
    resource.is_selected = body.is_selected
    session.flush()  # already chosen by another clinic, or another one of this type chosen here: 409
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="connected_account_resource.selected"
        if body.is_selected
        else "connected_account_resource.unselected",
        resource_type="connected_account_resource",
        resource_id=resource.id,
        clinic_id=ctx.clinic_id,
        details={"resource_type": resource.resource_type.value},
    )
    session.commit()
    session.refresh(resource)
    return ConnectedAccountResourceRead.model_validate(resource)


def _account(session: Session, ctx: ClinicContext, account_id: UUID) -> ConnectedAccount:
    account = session.get(ConnectedAccount, account_id)
    if account is None or account.clinic_id != ctx.clinic_id:
        raise NotFoundError("Connected account not found")
    return account
