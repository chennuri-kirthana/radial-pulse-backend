from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.core.enums import ConnectedAccountProvider, ConnectedAccountStatus, ConnectedResourceType
from app.schemas.common import ApiModel


class ConnectedAccountRead(ApiModel):
    """A clinic's login with a platform. The token itself is never returned (it is in Secrets Manager)."""

    id: UUID
    clinic_id: UUID
    provider: ConnectedAccountProvider
    status: ConnectedAccountStatus
    external_account_id: str
    external_account_name: str | None
    scopes: list[str]
    token_expires_at: datetime | None
    last_refreshed_at: datetime | None
    last_error: str | None
    connected_at: datetime | None
    disconnected_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProviderRead(ApiModel):
    provider: ConnectedAccountProvider
    label: str
    #: the platform app is set up on the server (credentials present)
    available: bool


class ConnectedAccountResourceRead(ApiModel):
    id: UUID
    connected_account_id: UUID
    clinic_id: UUID
    resource_type: ConnectedResourceType
    external_id: str
    display_name: str | None
    is_selected: bool
    created_at: datetime
    updated_at: datetime


class ConnectedAccountResourceSelect(ApiModel):
    is_selected: bool
