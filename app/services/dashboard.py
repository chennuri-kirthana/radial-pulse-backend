"""Dashboard numbers for Radial Pulse staff (Platform Administrator: all clinics; DSM: their own)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.enums import ClinicStage, ClinicStageGroup
from app.core.errors import ForbiddenError
from app.core.rbac import Principal
from app.db.base import utcnow
from app.repositories.dashboard import DashboardRepository
from app.schemas.dashboard import DashboardSummary, MonthCount, StageCount

MONTHS = 6


def _month_starts(now: datetime, count: int) -> list[datetime]:
    """First day of this month and the (count-1) months before it, oldest first."""
    year, month = now.year, now.month
    starts = []
    for _ in range(count):
        starts.append(datetime(year, month, 1, tzinfo=UTC))
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return list(reversed(starts))


def summary(session: Session, principal: Principal) -> DashboardSummary:
    if not principal.is_internal:
        raise ForbiddenError("The dashboard is for the Radial Pulse team")
    repo = DashboardRepository(session, principal.accessible_clinic_ids())
    months = _month_starts(utcnow(), MONTHS)
    if repo.empty:
        by_stage: dict[ClinicStage, int] = {}
        archived = awaiting = open_work = 0
        created: list[datetime] = []
    else:
        by_stage = repo.live_clinics_by_stage()
        archived = repo.archived_clinics()
        awaiting = repo.assessments_awaiting_review()
        open_work = repo.open_work_items()
        created = repo.clinic_created_times_since(months[0])
    per_month = {m.strftime("%Y-%m"): 0 for m in months}
    for created_at in created:
        key = created_at.strftime("%Y-%m")
        if key in per_month:
            per_month[key] += 1
    return DashboardSummary(
        total_clinics=sum(by_stage.values()),
        prospects=sum(by_stage.get(s, 0) for s in ClinicStageGroup.PROSPECTS.stages),
        in_progress=sum(by_stage.get(s, 0) for s in ClinicStageGroup.IN_PROGRESS.stages),
        active=by_stage.get(ClinicStage.ACTIVE_CLIENT, 0),
        archived=archived,
        by_stage=[StageCount(stage=s, count=by_stage.get(s, 0)) for s in ClinicStage],
        new_clinics_by_month=[MonthCount(month=k, count=v) for k, v in per_month.items()],
        assessments_awaiting_review=awaiting,
        open_work_items=open_work,
    )
