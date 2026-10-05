"""Sending invite emails. Best-effort: a failed email never undoes what was created."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import ClinicRole, PlatformRole
from app.core.rbac import Actor
from app.db.base import utcnow
from app.integrations.invites import Invite, InviteSender
from app.models import User
from app.services import audit

logger = logging.getLogger(__name__)

ROLE_LABELS: dict[str, str] = {
    PlatformRole.PLATFORM_ADMINISTRATOR.value: "Platform Administrator",
    PlatformRole.DIGITAL_SUCCESS_MANAGER.value: "Digital Success Manager",
    ClinicRole.CLINIC_ADMINISTRATOR.value: "Clinic Administrator",
    ClinicRole.CLINIC_TEAM_MEMBER.value: "Clinic Team Member",
}


def send_invite(
    session: Session,
    *,
    actor: Actor,
    user: User,
    role: PlatformRole | ClinicRole,
    invites: InviteSender,
    sign_in_url: str,
    clinic_id: UUID | None = None,
    clinic_name: str | None = None,
) -> bool:
    """Send (or re-send) the invite email, record it, and commit. Returns False if sending failed."""
    try:
        invites.send(
            Invite(
                email=user.email,
                full_name=user.full_name,
                role_label=ROLE_LABELS.get(role.value, role.value),
                sign_in_url=sign_in_url,
                clinic_name=clinic_name,
            )
        )
    except Exception as exc:  # the email service must never break the request
        logger.warning("invite email failed", extra={"exc_class": exc.__class__.__name__})
        audit.record(
            session, actor=actor, action="invite.failed", resource_type="user", resource_id=user.id,
            clinic_id=clinic_id, details={"role": role.value},
        )  # fmt: skip
        session.commit()
        return False
    user.last_invited_at = utcnow()
    audit.record(
        session, actor=actor, action="invite.sent", resource_type="user", resource_id=user.id,
        clinic_id=clinic_id, details={"role": role.value},
    )  # fmt: skip
    session.commit()
    return True
