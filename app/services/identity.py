"""Verified token → ``Principal`` (CLAUDE.md rule 6), and "who am I".

1. ``rp_user_for_login(sub, email)`` finds the account for the token's Cognito ``sub``. It runs
   before the database knows who is asking (no ``rp.user_id`` yet), which is why it exists.
2. Access tokens carry no email. If the ``sub`` is new, we ask Cognito's userInfo for the
   VERIFIED email and call it again: on the very first sign-in it links the invited account.
3. No account, or ``is_active = false`` → 403 ``account_disabled``. Radial Pulse is invite-only.
4. Then every query of the request runs as this user (``rp.user_id``), and the links that give
   access (clinic membership, portfolio allocation, practitioner link) are read.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.enums import ClinicMemberRole, PlatformRole
from app.core.errors import AccountDisabledError, UnauthorizedError
from app.core.rbac import Principal
from app.core.security import VerifiedToken
from app.db.base import utcnow
from app.db.tenant import act_as_user
from app.integrations.cognito import UserInfoClient
from app.models import Clinic, ClinicMember, ClinicPractitioner, PortfolioAllocation, Practitioner, User
from app.services import audit

logger = logging.getLogger(__name__)

#: last_login_at is refreshed at most this often (it is "last sign-in", not "last request").
LAST_LOGIN_RESOLUTION = timedelta(minutes=15)

_LOGIN = text("SELECT id, platform_role, is_active FROM rp_user_for_login(:sub, :email)")


def _login_row(session: Session, sub: str, email: str | None) -> tuple[UUID, str, bool] | None:
    row = session.execute(_LOGIN, {"sub": sub, "email": email or ""}).first()
    return (row.id, row.platform_role, row.is_active) if row is not None else None


def resolve_principal(
    session: Session, token: VerifiedToken, raw_token: str, userinfo: UserInfoClient | None
) -> Principal:
    found = _login_row(session, token.subject, None)
    linked_now = False
    if found is None and userinfo is not None:
        try:
            info = userinfo.fetch(raw_token)
        except Exception as exc:
            logger.warning("userinfo lookup failed", extra={"exc_class": exc.__class__.__name__})
            raise UnauthorizedError("Could not confirm your identity. Please sign in again.") from exc
        if info.email and info.email_verified:
            found = _login_row(session, token.subject, info.email)
            linked_now = found is not None
    if found is None or not found[2]:
        raise AccountDisabledError("This account is not active in Radial Pulse.")

    user_id = found[0]
    act_as_user(session, user_id)
    user = session.get(User, user_id)
    if user is None:  # pragma: no cover - the login function just returned it
        raise AccountDisabledError()

    if linked_now:
        audit.record(
            session,
            actor_user_id=user.id,
            action="user.sign_in_linked",
            resource_type="user",
            resource_id=user.id,
            clinic_id=None,
            details={"client_id": token.client_id},
        )
    now = utcnow()
    if user.last_login_at is None or now - _aware(user.last_login_at) > LAST_LOGIN_RESOLUTION:
        user.last_login_at = now
    if session.new or session.dirty:
        session.commit()  # keep the sign-in record even if the rest of the request fails
    return build_principal(session, user)


def build_principal(session: Session, user: User) -> Principal:
    """The access links of ``user``. Each role only counts with its own kind of link."""
    role = user.platform_role
    clinic_roles: dict[UUID, ClinicMemberRole] = {}
    org_ids: frozenset[UUID] = frozenset()
    dsm_clinic_ids: frozenset[UUID] = frozenset()
    practitioner_id: UUID | None = None
    practitioner_clinic_ids: frozenset[UUID] = frozenset()

    if role is PlatformRole.CLINIC_MEMBER:
        rows = session.execute(
            select(ClinicMember.clinic_id, ClinicMember.role).where(
                ClinicMember.user_id == user.id, ClinicMember.is_active.is_(True)
            )
        )
        clinic_roles = {r.clinic_id: r.role for r in rows}
    elif role is PlatformRole.DIGITAL_SUCCESS_MANAGER:
        org_ids = frozenset(
            session.scalars(
                select(PortfolioAllocation.client_organization_id).where(
                    PortfolioAllocation.user_id == user.id, PortfolioAllocation.is_active.is_(True)
                )
            )
        )
        if org_ids:
            dsm_clinic_ids = frozenset(
                session.scalars(select(Clinic.id).where(Clinic.client_organization_id.in_(org_ids)))
            )
    elif role is PlatformRole.PRACTITIONER:
        practitioner_id = session.scalar(select(Practitioner.id).where(Practitioner.user_id == user.id))
        if practitioner_id is not None:
            practitioner_clinic_ids = frozenset(
                session.scalars(
                    select(ClinicPractitioner.clinic_id).where(
                        ClinicPractitioner.practitioner_id == practitioner_id,
                        ClinicPractitioner.is_active.is_(True),
                    )
                )
            )

    return Principal(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        platform_role=role,
        clinic_roles=clinic_roles,
        dsm_client_organization_ids=org_ids,
        dsm_clinic_ids=dsm_clinic_ids,
        practitioner_id=practitioner_id,
        practitioner_clinic_ids=practitioner_clinic_ids,
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
