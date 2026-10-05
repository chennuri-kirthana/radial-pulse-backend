from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from app.models import ClinicProfile, ConsentRecord
from app.repositories.base import Repository


class ProfileRepository(Repository):
    def get(self, clinic_id: UUID) -> ClinicProfile | None:
        return self.session.get(ClinicProfile, clinic_id)

    def consents_for_clinic(self, clinic_id: UUID) -> list[ConsentRecord]:
        stmt = (
            select(ConsentRecord)
            .where(ConsentRecord.clinic_id == clinic_id)
            .order_by(ConsentRecord.consent_type, ConsentRecord.created_at)
        )
        return list(self.session.scalars(stmt))
