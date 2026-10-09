"""Client Organizations and Portfolio Allocations (db/schema-v15.sql sections 1 and 3)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, uuid_pk


class ClientOrganization(Timestamps, Base):
    """The business (e.g. Shah Healthcare Pvt Ltd). Its branches are ``clinics``."""

    __tablename__ = "client_organizations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200))


class PortfolioAllocation(Timestamps, Base):
    """A whole Client Organization given to one Digital Success Manager.

    One ACTIVE row per organization; past DSMs stay as inactive rows.
    """

    __tablename__ = "portfolio_allocations"

    client_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("client_organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
