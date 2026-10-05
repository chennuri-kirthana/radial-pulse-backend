"""Counts for the Admin and DSM dashboards. Always limited to the caller's clinics."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import InstrumentedAttribute

from app.core.enums import AssessmentStatus, ClinicStage, PublicationState
from app.models import Assessment, Clinic, WorkItem
from app.repositories.base import Repository
from app.repositories.tenancy import OPEN_WORK_STATUSES


class DashboardRepository(Repository):
    def __init__(self, session: Any, clinic_ids: Iterable[UUID] | None) -> None:
        """``clinic_ids=None`` = all clinics (Platform Administrator)."""
        super().__init__(session)
        self._ids = None if clinic_ids is None else list(clinic_ids)

    def _scope(self, column: InstrumentedAttribute[UUID]) -> ColumnElement[bool]:
        return column.in_(self._ids) if self._ids is not None else column.is_not(None)

    @property
    def empty(self) -> bool:
        return self._ids is not None and not self._ids

    def live_clinics_by_stage(self) -> dict[ClinicStage, int]:
        rows = self.session.execute(
            select(Clinic.stage, func.count())
            .where(self._scope(Clinic.id), Clinic.is_active.is_(True))
            .group_by(Clinic.stage)
        )
        return {stage: int(n) for stage, n in rows}

    def archived_clinics(self) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(Clinic)
                .where(self._scope(Clinic.id), Clinic.is_active.is_(False))
            )
            or 0
        )

    def clinic_created_times_since(self, since: datetime) -> list[datetime]:
        return list(
            self.session.scalars(
                select(Clinic.created_at).where(self._scope(Clinic.id), Clinic.created_at >= since)
            )
        )

    def assessments_awaiting_review(self) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(Assessment)
                .where(
                    self._scope(Assessment.clinic_id),
                    Assessment.status.in_([AssessmentStatus.COMPLETED, AssessmentStatus.PARTIAL]),
                    Assessment.publication_state != PublicationState.PUBLISHED,
                )
            )
            or 0
        )

    def open_work_items(self) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(WorkItem)
                .where(self._scope(WorkItem.clinic_id), WorkItem.status.in_(OPEN_WORK_STATUSES))
            )
            or 0
        )
