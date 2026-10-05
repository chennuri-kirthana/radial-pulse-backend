"""Connected accounts: a clinic's own Instagram / Facebook / Google Business Profile / ... login.

One row per (clinic, platform), reused when the clinic reconnects (history is in the audit log).

**Tokens are NEVER stored in the database.** ``secret_ref`` points at an AWS Secrets Manager
secret that holds them; only the API (to save) and the data-sync jobs (to read) can open it.

While a sign-in with the platform is in progress (status ``pending``), the ``oauth_*`` columns
hold what is needed to finish it safely: a HASH of the one-time ``state`` value, the PKCE
verifier and the redirect address. They are cleared as soon as the sign-in finishes or fails.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ConnectionPlatform, ConnectionStatus
from app.db.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin, str_enum


class PlatformConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "platform_connections"
    __table_args__ = (UniqueConstraint("clinic_id", "platform"),)

    #: No separate index: the unique key (clinic_id, platform) starts with clinic_id.
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    platform: Mapped[ConnectionPlatform] = mapped_column(str_enum(ConnectionPlatform, length=40))
    status: Mapped[ConnectionStatus] = mapped_column(str_enum(ConnectionStatus, length=24))
    #: The account on the platform, e.g. the Instagram handle or the Google location name.
    external_account_id: Mapped[str | None] = mapped_column(String(255))
    external_account_name: Mapped[str | None] = mapped_column(String(255))
    #: Permissions the clinic granted (as the platform reported them).
    scopes: Mapped[list[str]] = mapped_column(JSONType, default=list)
    #: ARN of the Secrets Manager secret with the tokens. Never the token itself.
    secret_ref: Mapped[str | None] = mapped_column(String(512))
    token_expires_at: Mapped[datetime | None]
    connected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    connected_at: Mapped[datetime | None]
    disconnected_at: Mapped[datetime | None]
    #: Set by the data-sync jobs (domain teams) after each successful pull.
    last_synced_at: Mapped[datetime | None]
    #: Plain-language reason shown on the screen when status is needs_reconnect.
    last_error: Mapped[str | None] = mapped_column(Text)
    # ---- only while status = pending (cleared afterwards) ----
    oauth_state_hash: Mapped[str | None] = mapped_column(String(64))
    oauth_code_verifier: Mapped[str | None] = mapped_column(String(128))
    oauth_redirect_uri: Mapped[str | None] = mapped_column(String(500))
    oauth_started_at: Mapped[datetime | None]
    oauth_started_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    #: Anything else the platform returned that is not secret (e.g. page ids). Small.
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)
