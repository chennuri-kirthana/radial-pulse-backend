from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.core.enums import AssessmentComponentKey, AssessmentStatus, PublicationState
from app.models import Assessment, AssessmentComponent, AssessmentFinding, Clinic
from app.repositories.base import Repository


class AssessmentRepository(Repository):
    def get_in_clinic(self, clinic_id: UUID, assessment_id: UUID) -> Assessment | None:
        return self.session.scalar(
            select(Assessment).where(Assessment.clinic_id == clinic_id, Assessment.id == assessment_id)
        )

    def in_progress(self, clinic_id: UUID) -> Assessment | None:
        return self.session.scalar(
            select(Assessment).where(
                Assessment.clinic_id == clinic_id,
                Assessment.status.in_([AssessmentStatus.QUEUED, AssessmentStatus.RUNNING]),
            )
        )

    def next_sequence(self, clinic_id: UUID) -> int:
        current = self.session.scalar(
            select(func.max(Assessment.sequence)).where(Assessment.clinic_id == clinic_id)
        )
        return int(current or 0) + 1

    def list_for_clinic(
        self, clinic_id: UUID, *, published_only: bool, limit: int, offset: int
    ) -> tuple[list[Any], int]:
        stmt = select(Assessment).where(Assessment.clinic_id == clinic_id)
        if published_only:
            stmt = stmt.where(Assessment.publication_state == PublicationState.PUBLISHED)
        return self.paginate(stmt.order_by(Assessment.sequence.desc()), limit, offset)

    def list_accessible(
        self,
        clinic_ids: Iterable[UUID] | None,
        *,
        published_only: bool,
        status: AssessmentStatus | None,
        publication_state: PublicationState | None,
        clinic_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[list[tuple[Assessment, str]], int]:
        """Assessments across clinics, each with its clinic's name, newest first.

        ``clinic_ids=None`` means all clinics (Platform Administrator). An empty set returns nothing.
        """
        base = select(Assessment, Clinic.name).join(Clinic, Clinic.id == Assessment.clinic_id)
        if clinic_ids is not None:
            ids = list(clinic_ids)
            if not ids:
                return [], 0
            base = base.where(Assessment.clinic_id.in_(ids))
        if clinic_id is not None:
            base = base.where(Assessment.clinic_id == clinic_id)
        if published_only:
            base = base.where(Assessment.publication_state == PublicationState.PUBLISHED)
        if status is not None:
            base = base.where(Assessment.status == status)
        if publication_state is not None:
            base = base.where(Assessment.publication_state == publication_state)
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.session.execute(
            base.order_by(Assessment.created_at.desc(), Assessment.id).limit(limit).offset(offset)
        )
        return [(assessment, name) for assessment, name in rows], int(total)

    def components(self, clinic_id: UUID, assessment_id: UUID) -> list[AssessmentComponent]:
        return list(
            self.session.scalars(
                select(AssessmentComponent).where(
                    AssessmentComponent.clinic_id == clinic_id,
                    AssessmentComponent.assessment_id == assessment_id,
                )
            )
        )

    def component(
        self, clinic_id: UUID, assessment_id: UUID, key: AssessmentComponentKey
    ) -> AssessmentComponent | None:
        return self.session.scalar(
            select(AssessmentComponent).where(
                AssessmentComponent.clinic_id == clinic_id,
                AssessmentComponent.assessment_id == assessment_id,
                AssessmentComponent.key == key,
            )
        )

    def findings(self, clinic_id: UUID, assessment_id: UUID) -> list[AssessmentFinding]:
        return list(
            self.session.scalars(
                select(AssessmentFinding).where(
                    AssessmentFinding.clinic_id == clinic_id, AssessmentFinding.assessment_id == assessment_id
                )
            )
        )

    def delete_findings_of_component(self, clinic_id: UUID, component_id: UUID) -> None:
        for old in self.session.scalars(
            select(AssessmentFinding).where(
                AssessmentFinding.clinic_id == clinic_id, AssessmentFinding.component_id == component_id
            )
        ):
            self.session.delete(old)
        # Delete NOW: the replacement findings reuse the same codes, and (component_id, code) is
        # unique. Without this flush the new rows would be inserted before the old ones are gone.
        self.session.flush()

    def finding_with_key(
        self, clinic_id: UUID, finding_id: UUID
    ) -> tuple[AssessmentFinding, AssessmentComponentKey] | None:
        """A finding of this clinic plus the section (component key) it belongs to."""
        row = self.session.execute(
            select(AssessmentFinding, AssessmentComponent.key)
            .join(AssessmentComponent, AssessmentComponent.id == AssessmentFinding.component_id)
            .where(AssessmentFinding.clinic_id == clinic_id, AssessmentFinding.id == finding_id)
        ).first()
        return (row[0], row[1]) if row is not None else None
