"""Platform settings, the clinic audit log, and the dashboard counts."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import ClinicStage, PhotoReviewState, ReviewState, WorkItemStatus
from app.core.errors import ConflictError
from app.core.rbac import ClinicContext, Principal
from app.models import (
    AuditEvent,
    Clinic,
    DigitalPresenceAssessment,
    ImprovementWorkItem,
    Photo,
    PlatformSettings,
)
from app.schemas.common import Page
from app.schemas.settings import (
    AuditEventRead,
    DashboardSummary,
    PlatformSettingsRead,
    PlatformSettingsUpdate,
)
from app.services import audit

_DEFAULTS = PlatformSettingsRead(
    support_email=None,
    support_phone=None,
    timezone="Asia/Kolkata",
    date_format="DD MMM YYYY",
    updated_at=None,
)


# ------------------------------------------------------------------------------ platform settings
def get_platform_settings(session: Session) -> PlatformSettingsRead:
    row = session.get(PlatformSettings, 1)
    return PlatformSettingsRead.model_validate(row) if row is not None else _DEFAULTS


def update_platform_settings(
    session: Session, principal: Principal, body: PlatformSettingsUpdate
) -> PlatformSettingsRead:
    row = session.get(PlatformSettings, 1)
    if row is None:
        # The app may not create the one settings row (the schema revokes INSERT); see the open point
        # "platform_settings row" in the Step E notes.
        raise ConflictError("Platform settings are not set up yet. Ask the platform team to create them.")
    changes = body.model_dump(exclude_unset=True)
    for name, value in changes.items():
        setattr(row, name, value)
    session.flush()
    if changes:
        audit.record(
            session,
            actor_user_id=principal.user_id,
            action="platform_settings.updated",
            resource_type="platform_settings",
            resource_id="1",
            clinic_id=None,
            details={"fields": sorted(changes)},
        )
    session.commit()
    session.refresh(row)
    return PlatformSettingsRead.model_validate(row)


# ------------------------------------------------------------------------------ audit log
def list_audit_events(
    session: Session, ctx: ClinicContext, *, action: str | None, limit: int, offset: int
) -> Page[AuditEventRead]:
    query = select(AuditEvent).where(AuditEvent.clinic_id == ctx.clinic_id)
    if action:
        query = query.where(AuditEvent.action == action)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id).limit(limit).offset(offset)
    )
    return Page(
        items=[AuditEventRead.model_validate(e) for e in rows], total=total, limit=limit, offset=offset
    )


# ------------------------------------------------------------------------------ dashboard
def dashboard(session: Session, principal: Principal) -> DashboardSummary:
    """Counts over what the caller may see. The database rules decide which rows count."""
    by_stage = dict(
        session.execute(
            select(Clinic.stage, func.count()).where(Clinic.is_active.is_(True)).group_by(Clinic.stage)
        ).all()
    )
    archived = (
        session.scalar(select(func.count()).select_from(Clinic).where(Clinic.is_active.is_(False))) or 0
    )
    open_items = (
        session.scalar(
            select(func.count())
            .select_from(ImprovementWorkItem)
            .where(ImprovementWorkItem.status.not_in([WorkItemStatus.DONE, WorkItemStatus.CANCELLED]))
        )
        or 0
    )
    is_staff = principal.is_platform_administrator or principal.is_digital_success_manager
    photos_waiting = reports_waiting = 0
    if is_staff:
        photos_waiting = (
            session.scalar(
                select(func.count()).select_from(Photo).where(Photo.review_state == PhotoReviewState.PENDING)
            )
            or 0
        )
        reports_waiting = (
            session.scalar(
                select(func.count())
                .select_from(DigitalPresenceAssessment)
                .where(DigitalPresenceAssessment.review_state == ReviewState.SUBMITTED)
            )
            or 0
        )
    return DashboardSummary(
        clinics_by_stage={stage: int(by_stage.get(stage, 0)) for stage in ClinicStage},
        archived_clinics=archived,
        open_improvement_work_items=open_items,
        photos_waiting_for_review=photos_waiting,
        digital_presence_assessments_to_review=reports_waiting,
    )
