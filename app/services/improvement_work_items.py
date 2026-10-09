"""Improvement Work Items (docs/01-decisions.md section 9).

* Staff (admin, the clinic's DSM) create and change them. The clinic team sees them; a
  practitioner sees only the items assigned to him (also enforced by the database).
* ``done`` ⇔ ``completed_at`` is set: the service keeps the two together.
* The assignee must belong to the clinic (trigger → 409) and is notified.
* One OPEN item per opportunity per clinic (→ 409).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import NotificationCategory, WorkItemStatus
from app.core.errors import NotFoundError
from app.core.rbac import ClinicContext
from app.db.base import utcnow
from app.models import ImprovementWorkItem
from app.schemas.improvement_work_items import (
    ImprovementWorkItemCreate,
    ImprovementWorkItemRead,
    ImprovementWorkItemUpdate,
)
from app.services import audit, notify

Read = ImprovementWorkItemRead


def list_work_items(
    session: Session, ctx: ClinicContext, *, status: WorkItemStatus | None, assignee_user_id: UUID | None
) -> list[Read]:
    query = select(ImprovementWorkItem).where(ImprovementWorkItem.clinic_id == ctx.clinic_id)
    if ctx.acting_practitioner_id is not None:  # a practitioner: his own items only
        query = query.where(ImprovementWorkItem.assignee_user_id == ctx.user_id)
    if status is not None:
        query = query.where(ImprovementWorkItem.status == status)
    if assignee_user_id is not None:
        query = query.where(ImprovementWorkItem.assignee_user_id == assignee_user_id)
    rows = session.scalars(
        query.order_by(ImprovementWorkItem.due_at.asc().nulls_last(), ImprovementWorkItem.created_at)
    )
    return [Read.model_validate(r) for r in rows]


def get_work_item(session: Session, ctx: ClinicContext, item_id: UUID) -> Read:
    return Read.model_validate(_get(session, ctx, item_id))


def create_work_item(session: Session, ctx: ClinicContext, body: ImprovementWorkItemCreate) -> Read:
    row = ImprovementWorkItem(clinic_id=ctx.clinic_id, **body.model_dump())
    if row.status == WorkItemStatus.DONE:
        row.completed_at = utcnow()
    session.add(row)
    session.flush()  # assignee outside the clinic, unknown report, or a second open item: 409
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="improvement_work_item.created",
        resource_type="improvement_work_item",
        resource_id=row.id,
        clinic_id=ctx.clinic_id,
    )
    _notify_assignee(session, ctx, row)
    session.commit()
    session.refresh(row)
    return Read.model_validate(row)


def update_work_item(
    session: Session, ctx: ClinicContext, item_id: UUID, body: ImprovementWorkItemUpdate
) -> Read:
    row = _get(session, ctx, item_id)
    changes = body.model_dump(exclude_unset=True)
    previous_assignee = row.assignee_user_id
    for name, value in changes.items():
        setattr(row, name, value)
    if "status" in changes:
        row.completed_at = (row.completed_at or utcnow()) if row.status == WorkItemStatus.DONE else None
    session.flush()
    if changes:
        audit.record(
            session,
            actor_user_id=ctx.user_id,
            action="improvement_work_item.updated",
            resource_type="improvement_work_item",
            resource_id=row.id,
            clinic_id=ctx.clinic_id,
            details={"fields": sorted(changes)},
        )
    if row.assignee_user_id != previous_assignee:
        _notify_assignee(session, ctx, row)
    session.commit()
    session.refresh(row)
    return Read.model_validate(row)


def _notify_assignee(session: Session, ctx: ClinicContext, row: ImprovementWorkItem) -> None:
    if row.assignee_user_id is None or row.assignee_user_id == ctx.user_id:
        return
    notify.send(
        session,
        user_id=row.assignee_user_id,
        category=NotificationCategory.WORK_ITEM_ASSIGNED,
        title=f"New work item: {row.title}",
        clinic_id=ctx.clinic_id,
        link=f"/clinics/{ctx.clinic_id}/improvement-work-items/{row.id}",
    )


def _get(session: Session, ctx: ClinicContext, item_id: UUID) -> ImprovementWorkItem:
    row = session.get(ImprovementWorkItem, item_id)
    hidden = row is None or row.clinic_id != ctx.clinic_id
    if (
        row is None
        or hidden
        or (ctx.acting_practitioner_id is not None and row.assignee_user_id != ctx.user_id)
    ):
        raise NotFoundError("Improvement Work Item not found")
    return row
