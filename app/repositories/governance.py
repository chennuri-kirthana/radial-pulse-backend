from __future__ import annotations

from collections.abc import Collection
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.enums import ApprovalState
from app.models import Approval, ApprovalNote, AuditEvent
from app.repositories.base import Repository


class ApprovalRepository(Repository):
    def get_in_clinic(self, clinic_id: UUID, approval_id: UUID) -> Approval | None:
        return self.session.scalar(
            select(Approval).where(Approval.clinic_id == clinic_id, Approval.id == approval_id)
        )

    def get_for_resource(self, clinic_id: UUID, resource_type: str, resource_id: UUID) -> Approval | None:
        return self.session.scalar(
            select(Approval).where(
                Approval.clinic_id == clinic_id,
                Approval.resource_type == resource_type,
                Approval.resource_id == resource_id,
            )
        )

    def for_resources(
        self, clinic_id: UUID, resource_type: str, resource_ids: Collection[UUID]
    ) -> dict[UUID, Approval]:
        if not resource_ids:
            return {}
        rows = self.session.scalars(
            select(Approval).where(
                Approval.clinic_id == clinic_id,
                Approval.resource_type == resource_type,
                Approval.resource_id.in_(list(resource_ids)),
            )
        )
        return {row.resource_id: row for row in rows}

    def list_for_clinic(
        self,
        clinic_id: UUID,
        state: ApprovalState | None,
        limit: int,
        offset: int,
        *,
        resource_type: str | None = None,
        hidden_resource_types: Collection[str] = (),
    ) -> tuple[list[Any], int]:
        stmt = select(Approval).where(Approval.clinic_id == clinic_id)
        if state is not None:
            stmt = stmt.where(Approval.state == state)
        if resource_type is not None:
            stmt = stmt.where(Approval.resource_type == resource_type)
        if hidden_resource_types:
            stmt = stmt.where(Approval.resource_type.not_in(list(hidden_resource_types)))
        return self.paginate(stmt.order_by(Approval.updated_at.desc(), Approval.id), limit, offset)


class ApprovalNoteRepository(Repository):
    """Internal review notes. Callers must be Radial Pulse staff (the database enforces it too)."""

    def latest_for(self, clinic_id: UUID, approval_ids: Collection[UUID]) -> dict[UUID, str]:
        if not approval_ids:
            return {}
        rows = self.session.execute(
            select(ApprovalNote.approval_id, ApprovalNote.body)
            .where(ApprovalNote.clinic_id == clinic_id, ApprovalNote.approval_id.in_(list(approval_ids)))
            .order_by(ApprovalNote.created_at, ApprovalNote.id)
        )
        latest: dict[UUID, str] = {}
        for approval_id, body in rows:
            latest[approval_id] = body  # ordered oldest → newest: the last one wins
        return latest


class AuditEventRepository(Repository):
    def list_for_clinic(
        self, clinic_id: UUID, limit: int, offset: int, *, hide_internal_review: bool = False
    ) -> tuple[list[Any], int]:
        stmt = select(AuditEvent).where(AuditEvent.clinic_id == clinic_id)
        if hide_internal_review:
            # Review activity and assessment work stay internal (migration 0013 does the same).
            stmt = stmt.where(~AuditEvent.action.like("approval.%"), AuditEvent.resource_type != "assessment")
        return self.paginate(stmt.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id), limit, offset)
