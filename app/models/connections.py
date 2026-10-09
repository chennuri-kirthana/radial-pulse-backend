"""Connected accounts (Google, Instagram, ...) (db/schema-v15.sql section 8).

Tokens live in AWS Secrets Manager; only ``secret_ref`` is stored here (CLAUDE.md rule 10).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, ForeignKeyConstraint, String, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ConnectedAccountProvider, ConnectedAccountStatus, ConnectedResourceType
from app.db.base import Base, CreatedAt, TextArray, Timestamps, str_enum, uuid_pk


class ConnectedAccount(Timestamps, Base):
    __tablename__ = "connected_accounts"

    id: Mapped[uuid.UUID] = uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    provider: Mapped[ConnectedAccountProvider] = mapped_column(str_enum(ConnectedAccountProvider, 24))
    status: Mapped[ConnectedAccountStatus] = mapped_column(
        str_enum(ConnectedAccountStatus, 24), server_default=text("'connected'")
    )
    external_account_id: Mapped[str] = mapped_column(String(255))
    external_account_name: Mapped[str | None] = mapped_column(String(255))
    scopes: Mapped[list[str]] = mapped_column(TextArray, server_default=text("'{}'"))
    #: ARN of the Secrets Manager secret; never the token itself
    secret_ref: Mapped[str | None] = mapped_column(String(512))
    token_expires_at: Mapped[datetime | None]
    last_refreshed_at: Mapped[datetime | None]
    last_error: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime | None]
    disconnected_at: Mapped[datetime | None]


class ConnectedAccountResource(Timestamps, Base):
    """A location / site / page reachable through a connected account. Each can be selected by
    only ONE clinic."""

    __tablename__ = "connected_account_resources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["connected_account_id", "clinic_id"],
            ["connected_accounts.id", "connected_accounts.clinic_id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    connected_account_id: Mapped[uuid.UUID]
    clinic_id: Mapped[uuid.UUID]
    resource_type: Mapped[ConnectedResourceType] = mapped_column(str_enum(ConnectedResourceType, 40))
    external_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    is_selected: Mapped[bool] = mapped_column(Boolean, server_default=false())


class OAuthState(CreatedAt, Base):
    """One "Connect" click in progress. Only the HASH of ``state`` is stored; expires in 10 minutes."""

    __tablename__ = "oauth_states"

    id: Mapped[uuid.UUID] = uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    provider: Mapped[ConnectedAccountProvider] = mapped_column(str_enum(ConnectedAccountProvider, 24))
    state_hash: Mapped[str] = mapped_column(String(64))
    code_verifier: Mapped[str | None] = mapped_column(String(128))
    redirect_uri: Mapped[str] = mapped_column(String(500))
    #: the callback must come from the SAME person
    started_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime]
