from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.core.enums import DataSource, PublicationState, SnapshotStatus
from app.models import MetricSnapshot, ReportArtifact
from app.repositories.base import Repository


class SnapshotRepository(Repository):
    def add_many(self, snapshots: list[MetricSnapshot]) -> list[MetricSnapshot]:
        self.session.add_all(snapshots)
        self.session.flush()
        return snapshots

    def list_for_clinic(
        self,
        clinic_id: UUID,
        *,
        metric_key: str | None,
        source: DataSource | None,
        limit: int,
        offset: int,
        latest: bool = False,
    ) -> tuple[list[Any], int]:
        stmt = select(MetricSnapshot).where(MetricSnapshot.clinic_id == clinic_id)
        if metric_key is not None:
            stmt = stmt.where(MetricSnapshot.metric_key == metric_key)
        if source is not None:
            stmt = stmt.where(MetricSnapshot.source == source)
        if latest:
            # Only the newest GOOD value of each metric per source (e.g. the Social Media cards).
            candidates = select(
                MetricSnapshot.id.label("snapshot_id"),
                func.row_number()
                .over(
                    partition_by=(MetricSnapshot.source, MetricSnapshot.metric_key),
                    order_by=(MetricSnapshot.fetched_at.desc(), MetricSnapshot.id.desc()),
                )
                .label("rn"),
            ).where(MetricSnapshot.clinic_id == clinic_id, MetricSnapshot.status == SnapshotStatus.OK)
            if metric_key is not None:
                candidates = candidates.where(MetricSnapshot.metric_key == metric_key)
            if source is not None:
                candidates = candidates.where(MetricSnapshot.source == source)
            newest = candidates.subquery()
            stmt = stmt.join(newest, (newest.c.snapshot_id == MetricSnapshot.id) & (newest.c.rn == 1))
        return self.paginate(
            stmt.order_by(MetricSnapshot.fetched_at.desc(), MetricSnapshot.id), limit, offset
        )


class ReportRepository(Repository):
    def get_in_clinic(self, clinic_id: UUID, report_id: UUID) -> ReportArtifact | None:
        return self.session.scalar(
            select(ReportArtifact).where(
                ReportArtifact.clinic_id == clinic_id, ReportArtifact.id == report_id
            )
        )

    def next_version(self, clinic_id: UUID, report_key: str) -> int:
        current = self.session.scalar(
            select(func.max(ReportArtifact.version)).where(
                ReportArtifact.clinic_id == clinic_id, ReportArtifact.report_key == report_key
            )
        )
        return int(current or 0) + 1

    def list_for_clinic(
        self, clinic_id: UUID, *, published_only: bool, report_type: str | None, limit: int, offset: int
    ) -> tuple[list[Any], int]:
        stmt = select(ReportArtifact).where(ReportArtifact.clinic_id == clinic_id)
        if published_only:
            stmt = stmt.where(ReportArtifact.publication_state == PublicationState.PUBLISHED)
        if report_type is not None:
            stmt = stmt.where(ReportArtifact.report_type == report_type)
        return self.paginate(
            stmt.order_by(ReportArtifact.created_at.desc(), ReportArtifact.id), limit, offset
        )
