from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, Limit, Offset
from app.core.enums import DataSource
from app.core.rbac import ClinicContext, Permission
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.schemas.common import Page
from app.schemas.reporting import MetricSnapshotBatch, MetricSnapshotRead
from app.services import reporting as service

router = APIRouter(prefix="/clinics/{clinic_id}/snapshots", tags=["data-ingestion"], responses=ERRORS)


@router.post(
    "",
    response_model=list[MetricSnapshotRead],
    status_code=status.HTTP_201_CREATED,
    summary="Ingest normalized metric snapshots (source, freshness, error/retry state)",
)
def ingest(
    body: MetricSnapshotBatch,
    ctx: ClinicContext = Depends(clinic_access(Permission.SNAPSHOTS_WRITE)),
    db: Session = Depends(get_db),
) -> list[MetricSnapshotRead]:
    return [MetricSnapshotRead.model_validate(s) for s in service.ingest_snapshots(db, ctx, body)]


@router.get("", response_model=Page[MetricSnapshotRead])
def list_snapshots(
    metric_key: str | None = Query(default=None, max_length=128),
    source: DataSource | None = Query(default=None),
    latest: bool = Query(default=False, description="Only the newest value of each metric"),
    limit: Limit = 50,
    offset: Offset = 0,
    ctx: ClinicContext = Depends(clinic_access(Permission.SNAPSHOTS_READ)),
    db: Session = Depends(get_db),
) -> Page[MetricSnapshotRead]:
    items, total = service.list_snapshots(db, ctx, metric_key, source, limit, offset, latest=latest)
    return Page[MetricSnapshotRead](items=items, total=total, limit=limit, offset=offset)
