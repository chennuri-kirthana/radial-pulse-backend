"""Audit trail writer. Called by every service that changes state.

APPLICATION audit records (who did what to which clinic's data) live in the `audit_events`
table: append-only (trigger + the app DB role has no UPDATE/DELETE on it), row-level
security per clinic, readable through the API. INFRASTRUCTURE/SYSTEM logs (requests,
errors, stack traces) go to CloudWatch via stdout and are never used as the audit trail.
actor_type is one of: user (a human), service (e.g. the worker), system (CLI/migrations).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.logging import redact, request_id_ctx
from app.core.rbac import Actor
from app.models import AuditEvent


def record(
    session: Session,
    *,
    actor: Actor | None,
    action: str,
    resource_type: str,
    resource_id: UUID | str | None,
    clinic_id: UUID | None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    """Add an audit event to the current transaction (it commits or rolls back with the change)."""
    extra: dict[str, Any] = {}
    if actor is not None and actor.actor_type == "service":
        extra["service"] = getattr(actor, "name", "unknown")
    event = AuditEvent(
        actor_user_id=actor.user_id if actor else None,
        actor_type=actor.actor_type if actor else "system",
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        clinic_id=clinic_id,
        request_id=request_id_ctx.get(),
        details=redact({**(details or {}), **extra}),
    )
    session.add(event)
    return event
