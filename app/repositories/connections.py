from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.core.enums import ConnectionPlatform
from app.models import PlatformConnection
from app.repositories.base import Repository


class ConnectionRepository(Repository):
    def list_for_clinic(self, clinic_id: UUID) -> list[PlatformConnection]:
        return list(
            self.session.scalars(select(PlatformConnection).where(PlatformConnection.clinic_id == clinic_id))
        )

    def get(
        self, clinic_id: UUID, platform: ConnectionPlatform, *, for_update: bool = False
    ) -> PlatformConnection | None:
        """``for_update`` locks the row until COMMIT (two "complete" calls cannot both use one state)."""
        stmt = select(PlatformConnection).where(
            PlatformConnection.clinic_id == clinic_id, PlatformConnection.platform == platform
        )
        return self.session.scalar(stmt.with_for_update() if for_update else stmt)
