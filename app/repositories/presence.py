from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.enums import PresencePlatform, PresenceVerification
from app.models import PresenceProfile
from app.repositories.base import Repository


class PresenceRepository(Repository):
    def get_in_clinic(self, clinic_id: UUID, profile_id: UUID) -> PresenceProfile | None:
        return self.session.scalar(
            select(PresenceProfile).where(
                PresenceProfile.clinic_id == clinic_id, PresenceProfile.id == profile_id
            )
        )

    def find(self, clinic_id: UUID, platform: PresencePlatform, url: str) -> PresenceProfile | None:
        return self.session.scalar(
            select(PresenceProfile).where(
                PresenceProfile.clinic_id == clinic_id,
                PresenceProfile.platform == platform,
                PresenceProfile.url == url,
            )
        )

    def list_for_clinic(self, clinic_id: UUID, limit: int, offset: int) -> tuple[list[Any], int]:
        stmt = (
            select(PresenceProfile)
            .where(PresenceProfile.clinic_id == clinic_id)
            .order_by(PresenceProfile.platform, PresenceProfile.url)
        )
        return self.paginate(stmt, limit, offset)

    def usable_for_clinic(self, clinic_id: UUID) -> list[PresenceProfile]:
        """Everything except profiles a person rejected."""
        return list(
            self.session.scalars(
                select(PresenceProfile).where(
                    PresenceProfile.clinic_id == clinic_id,
                    PresenceProfile.verification != PresenceVerification.REJECTED,
                )
            )
        )
