"""Turns a verified token into a ``Principal``, and answers "who am I".

First sign-in: Cognito's access token has a ``sub`` but no email. If we have
never seen this ``sub``, we ask Cognito's userInfo endpoint for the VERIFIED email
and link it to a pre-provisioned ``User`` (created by an admin or when a clinic
was onboarded). Unknown emails are refused: Radial Pulse is invite-only.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.enums import PlatformRole
from app.core.errors import NotProvisionedError, UnauthorizedError
from app.core.rbac import Principal
from app.core.security import VerifiedToken
from app.db.base import utcnow
from app.db.tenant import set_current_user
from app.integrations.cognito import UserInfoClient
from app.integrations.storage import ObjectStorage
from app.models import User
from app.repositories.tenancy import AssignmentRepository, MembershipRepository
from app.repositories.users import UserRepository
from app.schemas.auth import ClinicAccess, MeResponse
from app.services import audit

logger = logging.getLogger(__name__)

LAST_LOGIN_RESOLUTION = timedelta(minutes=15)
STAFF_ROLES = (PlatformRole.PLATFORM_ADMINISTRATOR, PlatformRole.DIGITAL_SUCCESS_MANAGER)
#: How long the profile-photo link in /auth/me works.
AVATAR_URL_TTL_SECONDS = 900


def build_principal(session: Session, user: User) -> Principal:
    memberships = MembershipRepository(session).active_for_user(user.id)
    assignments = AssignmentRepository(session).active_for_user(user.id)
    return Principal(
        user_id=user.id,
        email=user.email,
        platform_role=user.platform_role,
        clinic_roles={m.clinic_id: m.role for m in memberships},
        assigned_clinic_ids=frozenset(a.clinic_id for a in assignments),
    )


def resolve_principal(
    session: Session, token: VerifiedToken, raw_token: str, userinfo: UserInfoClient | None
) -> Principal:
    users = UserRepository(session)
    # The users table is under row-level security: find the account with the narrow lookup,
    # then tell the database who is asking, THEN load the row (a person can always see themselves).
    user_id = users.find_id_by_sub(token.subject)
    user = None
    if user_id is not None:
        set_current_user(session, user_id)
        user = users.get(user_id)

    if user is None:
        if userinfo is None:
            raise NotProvisionedError("This account is not linked to Radial Pulse yet.")
        try:
            info = userinfo.fetch(raw_token)
        except Exception as exc:
            logger.warning("userinfo lookup failed", extra={"exc_class": exc.__class__.__name__})
            raise UnauthorizedError("Could not confirm your identity. Please sign in again.") from exc
        if not info.email or not info.email_verified:
            raise NotProvisionedError("Your email address is not verified.")
        match = users.find_by_email(info.email)
        if match is not None:
            set_current_user(session, match.id)
            user = users.get(match.id)
        if user is None or user.cognito_sub is not None:
            # Unknown email, or the email is already linked to a DIFFERENT Cognito identity.
            raise NotProvisionedError("This account has not been invited to Radial Pulse.")
        user.cognito_sub = token.subject
        if not user.full_name and info.name:
            user.full_name = info.name
        audit.record(
            session,
            actor=None,
            action="user.identity_linked",
            resource_type="user",
            resource_id=user.id,
            clinic_id=None,
            details={"client_id": token.client_id},
        )

    if not user.is_active:
        raise NotProvisionedError("This account is disabled.")
    set_current_user(session, user.id, is_staff=user.platform_role in STAFF_ROLES)

    now = utcnow()
    if user.last_login_at is None or now - _aware(user.last_login_at) > LAST_LOGIN_RESOLUTION:
        user.last_login_at = now
    if session.dirty or session.new:
        session.commit()

    return build_principal(session, user)


def me(session: Session, principal: Principal, storage: ObjectStorage | None = None) -> MeResponse:
    user = UserRepository(session).get(principal.user_id)
    if user is None:  # pragma: no cover - principal was just built from this row
        raise UnauthorizedError()
    clinic_ids = principal.accessible_clinic_ids() or frozenset()
    clinics = [
        ClinicAccess(
            clinic_id=cid,
            clinic_role=principal.clinic_roles.get(cid),
            assigned=cid in principal.assigned_clinic_ids,
            permissions=sorted(principal.clinic_permissions(cid)),
        )
        for cid in sorted(clinic_ids, key=str)
    ]
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        platform_role=user.platform_role,
        permissions=sorted(principal.global_permissions()),
        clinics=clinics,
        all_clinics=principal.is_platform_administrator,
        avatar_url=(
            storage.presign_get(user.avatar_key, AVATAR_URL_TTL_SECONDS)
            if storage is not None and user.avatar_key
            else None
        ),
        last_login_at=user.last_login_at,
    )


def _aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; PostgreSQL returns aware ones. Normalize to UTC-aware."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
