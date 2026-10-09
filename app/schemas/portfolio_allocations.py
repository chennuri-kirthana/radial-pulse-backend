from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.schemas.common import ApiModel


class PortfolioAllocationRead(ApiModel):
    client_organization_id: UUID
    client_organization_name: str
    #: the Digital Success Manager
    user_id: UUID
    user_full_name: str | None
    user_email: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PortfolioAllocationSet(ApiModel):
    """Give the whole Client Organization (all its clinics) to this Digital Success Manager."""

    user_id: UUID
