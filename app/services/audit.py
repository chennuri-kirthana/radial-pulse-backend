"""Audit trail writer (CLAUDE.md rule 8). Called by every service that changes something.

One ``audit_events`` row per change, added to the SAME transaction as the change, so both are
saved or neither. The table is insert-only (trigger + no UPDATE/DELETE grant).
Views of private files (photos, voice) are audited too (rule 11).

``actor_type``: ``user`` (a person), ``system`` (a background job or operator command),
``service`` (another team's backend).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import ActorType
from app.core.logging import redact, request_id_ctx
from app.models import AuditEvent


def record(
    session: Session,
    *,
    action: str,
    resource_type: str,
    resource_id: UUID | str | None,
    clinic_id: UUID | None,
    actor_user_id: UUID | None = None,
    actor_type: ActorType | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit event to the current transaction. No user → ``system``."""
    event = AuditEvent(
        actor_user_id=actor_user_id,
        actor_type=str(actor_type or (ActorType.USER if actor_user_id else ActorType.SYSTEM)),
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        clinic_id=clinic_id,
        request_id=request_id_ctx.get(),
        details=redact(details or {}),
    )
    session.add(event)
    return event
