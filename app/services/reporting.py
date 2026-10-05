"""Data-ingestion (metric snapshots) and output (report artifacts) contracts."""

from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import AssetStatus, DataSource
from app.core.errors import DomainValidationError, NotFoundError
from app.core.rbac import ClinicContext, Permission
from app.models import MetricSnapshot, ReportArtifact
from app.repositories.assets import AssetRepository
from app.repositories.reporting import ReportRepository, SnapshotRepository
from app.schemas.reporting import MetricSnapshotBatch, ReportArtifactCreate
from app.services import audit


def number_of(value: dict[str, Any]) -> float | None:
    """The plain number inside a metric value ({"value": 5432} → 5432.0), else None.

    Booleans are not numbers here (True is not 1 follower).
    """
    raw = value.get("value")
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    number = float(raw)
    # NUMERIC(20, 6) holds values below 1e14; anything bigger (or inf/nan) stays JSON-only.
    if not math.isfinite(number) or abs(number) >= 1e14:
        return None
    return number


def ingest_snapshots(
    session: Session, ctx: ClinicContext, batch: MetricSnapshotBatch
) -> list[MetricSnapshot]:
    rows = [
        MetricSnapshot(
            clinic_id=ctx.clinic_id,
            ingested_by_user_id=ctx.principal.user_id,
            value_number=number_of(s.value),
            **s.model_dump(),
        )
        for s in batch.snapshots
    ]
    SnapshotRepository(session).add_many(rows)
    audit.record(
        session,
        actor=ctx.principal,
        action="snapshot.ingest",
        resource_type="metric_snapshot",
        resource_id=None,
        clinic_id=ctx.clinic_id,
        details={
            "count": len(rows),
            "sources": sorted({r.source.value for r in rows}),
            "errors": sum(1 for r in rows if r.status.value == "error"),
        },
    )
    session.commit()
    return rows


def list_snapshots(
    session: Session,
    ctx: ClinicContext,
    metric_key: str | None,
    source: DataSource | None,
    limit: int,
    offset: int,
    latest: bool = False,
) -> tuple[list[Any], int]:
    return SnapshotRepository(session).list_for_clinic(
        ctx.clinic_id, metric_key=metric_key, source=source, limit=limit, offset=offset, latest=latest
    )


def create_report(session: Session, ctx: ClinicContext, data: ReportArtifactCreate) -> ReportArtifact:
    if data.asset_id is not None:
        asset = AssetRepository(session).get_in_clinic(ctx.clinic_id, data.asset_id)
        if asset is None or asset.status is not AssetStatus.UPLOADED:
            raise DomainValidationError("asset_id must be an uploaded asset of this clinic")
    repo = ReportRepository(session)
    report = ReportArtifact(
        clinic_id=ctx.clinic_id,
        report_type=data.report_type,
        report_key=data.report_key,
        version=repo.next_version(ctx.clinic_id, data.report_key),
        title=data.title,
        provenance=data.provenance,
        owner_user_id=ctx.principal.user_id,
        asset_id=data.asset_id,
    )
    repo.add(report)
    audit.record(
        session,
        actor=ctx.principal,
        action="report.create",
        resource_type="report_artifact",
        resource_id=report.id,
        clinic_id=ctx.clinic_id,
        details={"report_type": report.report_type, "version": report.version},
    )
    session.commit()
    return report


def _clients_see_published_only(ctx: ClinicContext) -> bool:
    """People who cannot write reports (clinic users) only ever see PUBLISHED reports."""
    return not ctx.can(Permission.REPORTS_WRITE)


def list_reports(
    session: Session, ctx: ClinicContext, report_type: str | None, limit: int, offset: int
) -> tuple[list[Any], int]:
    return ReportRepository(session).list_for_clinic(
        ctx.clinic_id,
        published_only=_clients_see_published_only(ctx),
        report_type=report_type,
        limit=limit,
        offset=offset,
    )


def get_report(session: Session, ctx: ClinicContext, report_id: UUID) -> ReportArtifact:
    report = ReportRepository(session).get_in_clinic(ctx.clinic_id, report_id)
    if report is None:
        raise NotFoundError("Report not found")
    if _clients_see_published_only(ctx) and report.publication_state.value != "published":
        raise NotFoundError("Report not found")
    return report
