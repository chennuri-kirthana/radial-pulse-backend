from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, exists, not_, or_, select

from app.core.enums import ApprovalState, AssetKind, AssetStatus, MediaTaxonomyDimension, PublicationState
from app.models import Asset, MediaTaxonomyValue, ReportArtifact
from app.repositories.base import Repository


def _visible_to_clinic_people() -> ColumnElement[bool]:
    """Files clinic people may see: report files only once PUBLISHED (the same rule as reports).

    A file is hidden when it is a ``report`` file with no published report, or when it belongs
    to a report that is not published. Migration 0013 applies the same rule in the database.
    """
    published = exists().where(
        ReportArtifact.asset_id == Asset.id,
        ReportArtifact.clinic_id == Asset.clinic_id,
        ReportArtifact.publication_state == PublicationState.PUBLISHED,
    )
    any_report = exists().where(
        ReportArtifact.asset_id == Asset.id, ReportArtifact.clinic_id == Asset.clinic_id
    )
    return or_(published, and_(Asset.kind != AssetKind.REPORT, not_(any_report)))


class AssetRepository(Repository):
    def get_in_clinic(self, clinic_id: UUID, asset_id: UUID, *, clients_only: bool = False) -> Asset | None:
        stmt = select(Asset).where(Asset.clinic_id == clinic_id, Asset.id == asset_id)
        if clients_only:
            stmt = stmt.where(_visible_to_clinic_people())
        return self.session.scalar(stmt)

    def list_for_clinic(
        self,
        clinic_id: UUID,
        *,
        kind: AssetKind | None = None,
        status: AssetStatus | None = None,
        approval_state: ApprovalState | None = None,
        practitioner_id: UUID | None = None,
        category_id: UUID | None = None,
        clients_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        stmt = select(Asset).where(Asset.clinic_id == clinic_id)
        if kind is not None:
            stmt = stmt.where(Asset.kind == kind)
        if status is not None:
            stmt = stmt.where(Asset.status == status)
        if approval_state is not None:
            stmt = stmt.where(Asset.approval_state == approval_state)
        if practitioner_id is not None:
            stmt = stmt.where(Asset.practitioner_id == practitioner_id)
        if category_id is not None:
            stmt = stmt.where(Asset.category_id == category_id)
        if clients_only:
            stmt = stmt.where(_visible_to_clinic_people())
        return self.paginate(stmt.order_by(Asset.created_at.desc(), Asset.id), limit, offset)

    def kinds_in_clinic(self, clinic_id: UUID, asset_ids: Collection[UUID]) -> dict[UUID, AssetKind]:
        if not asset_ids:
            return {}
        rows = self.session.execute(
            select(Asset.id, Asset.kind).where(Asset.clinic_id == clinic_id, Asset.id.in_(list(asset_ids)))
        )
        return {asset_id: kind for asset_id, kind in rows}

    def stale_pending_uploads(self, older_than: datetime, limit: int) -> list[Asset]:
        """Uploads that were never confirmed (every clinic in the caller's scope), oldest first."""
        stmt = (
            select(Asset)
            .where(Asset.status == AssetStatus.PENDING_UPLOAD, Asset.created_at < older_than)
            .order_by(Asset.created_at, Asset.id)
            .limit(limit)
        )
        return list(self.session.scalars(stmt))


class MediaTaxonomyRepository(Repository):
    def list(self, *, active_only: bool = True) -> list[MediaTaxonomyValue]:
        stmt = select(MediaTaxonomyValue)
        if active_only:
            stmt = stmt.where(MediaTaxonomyValue.is_active.is_(True))
        stmt = stmt.order_by(
            MediaTaxonomyValue.dimension, MediaTaxonomyValue.sort_order, MediaTaxonomyValue.code
        )
        return list(self.session.scalars(stmt))

    def get_by_code(self, dimension: MediaTaxonomyDimension, code: str) -> MediaTaxonomyValue | None:
        return self.session.scalar(
            select(MediaTaxonomyValue).where(
                MediaTaxonomyValue.dimension == dimension, MediaTaxonomyValue.code == code
            )
        )

    def by_ids(self, ids: set[UUID]) -> dict[UUID, MediaTaxonomyValue]:
        if not ids:
            return {}
        rows = self.session.scalars(select(MediaTaxonomyValue).where(MediaTaxonomyValue.id.in_(ids)))
        return {row.id: row for row in rows}
