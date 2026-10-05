from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.core.enums import ConnectionPlatform, ConnectionStatus
from app.schemas.common import ApiModel


class ConnectionRead(ApiModel):
    """One card on "Connect Your Accounts" / "Connected Accounts". Every platform is always listed."""

    platform: ConnectionPlatform
    #: Display name, e.g. "Google Business Profile".
    label: str
    status: ConnectionStatus
    #: False = our team has not set up this platform yet: show the card, disable "Connect".
    available: bool
    external_account_name: str | None = None
    scopes: list[str] = Field(default_factory=list)
    connected_at: datetime | None = None
    connected_by_user_id: UUID | None = None
    token_expires_at: datetime | None = None
    last_synced_at: datetime | None = None
    #: Plain-language reason when status is needs_reconnect (or the last Connect failed).
    last_error: str | None = None


class ConnectionStartRequest(ApiModel):
    #: Where the platform should send the clinic back (must be on the server's allowed list).
    redirect_uri: str = Field(min_length=1, max_length=500)


class ConnectionStartResponse(ApiModel):
    platform: ConnectionPlatform
    #: Open this in the browser / an in-app browser tab.
    authorization_url: str
    #: Finish (``…/complete``) before this time, or press Connect again.
    expires_at: datetime


class ConnectionCompleteRequest(ApiModel):
    """The ``code`` and ``state`` the platform added to the redirect address."""

    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=512)
