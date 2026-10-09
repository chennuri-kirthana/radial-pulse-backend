"""Clinic members: the clinic's own people (docs/01-decisions.md section 4).

Several Clinic Administrators are allowed; at least ONE must stay active (trigger → 409).
Clinic Team Members are read-only. Members are switched off, not deleted (history stays).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import PlatformRole
from app.core.errors import ConflictError, NotFoundError, UpstreamError
from app.core.rbac import ClinicContext
from app.integrations.identity_directory import AlreadySignedUpError, IdentityDirectory
from app.models import ClinicMember, User
from app.schemas.clinic_members import ClinicMemberCreate, ClinicMemberRead, ClinicMemberUpdate
from app.services import audit
from app.services.users import create_invited


def _read(member: ClinicMember, user: User) -> ClinicMemberRead:
    return ClinicMemberRead(
        clinic_id=member.clinic_id,
        user_id=user.id,
        role=member.role,
        is_active=member.is_active,
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        has_signed_in=user.cognito_sub is not None,
        created_at=member.created_at,
    )


def list_members(session: Session, ctx: ClinicContext) -> list[ClinicMemberRead]:
    rows = session.execute(
        select(ClinicMember, User)
        .join(User, User.id == ClinicMember.user_id)
        .where(ClinicMember.clinic_id == ctx.clinic_id)
        .order_by(ClinicMember.role, User.email)
    )
    return [_read(m, u) for m, u in rows]


def add_member(
    session: Session, ctx: ClinicContext, body: ClinicMemberCreate, directory: IdentityDirectory
) -> ClinicMemberRead:
    user = session.scalar(select(User).where(User.email == body.email))
    if user is None:
        user = create_invited(
            session,
            actor_user_id=ctx.user_id,
            email=body.email,
            full_name=body.full_name,
            phone=body.phone,
            platform_role=PlatformRole.CLINIC_MEMBER,
            directory=directory,
            clinic_id=ctx.clinic_id,
        )
    elif session.get(ClinicMember, (ctx.clinic_id, user.id)) is not None:
        raise ConflictError("This person is already a member of this clinic.")
    member = ClinicMember(clinic_id=ctx.clinic_id, user_id=user.id, role=body.role)
    session.add(member)
    session.flush()  # a login that is not a clinic_member (e.g. a practitioner) fails here: 409
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="clinic_member.added",
        resource_type="clinic_member",
        resource_id=user.id,
        clinic_id=ctx.clinic_id,
        details={"role": body.role.value},
    )
    session.commit()
    return _read(member, user)


def update_member(
    session: Session, ctx: ClinicContext, user_id: UUID, body: ClinicMemberUpdate
) -> ClinicMemberRead:
    member, user = _get(session, ctx.clinic_id, user_id)
    changes = body.model_dump(exclude_unset=True)
    for name, value in changes.items():
        setattr(member, name, value)
    session.flush()  # removing the LAST active Clinic Administrator fails here: 409
    if changes:
        audit.record(
            session,
            actor_user_id=ctx.user_id,
            action="clinic_member.updated",
            resource_type="clinic_member",
            resource_id=user.id,
            clinic_id=ctx.clinic_id,
            details={k: (v.value if hasattr(v, "value") else v) for k, v in changes.items()},
        )
    session.commit()
    return _read(member, user)


def resend_invite(session: Session, ctx: ClinicContext, user_id: UUID, directory: IdentityDirectory) -> None:
    _, user = _get(session, ctx.clinic_id, user_id)
    if user.cognito_sub is not None:
        raise ConflictError("This person has already signed in.")
    try:
        directory.resend_invite(user.email, user.full_name)
    except AlreadySignedUpError as exc:
        raise ConflictError("This person has already chosen a password.") from exc
    except Exception as exc:
        raise UpstreamError("The invite could not be sent. Please try again.") from exc
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="user.invite_resent",
        resource_type="user",
        resource_id=user.id,
        clinic_id=ctx.clinic_id,
    )
    session.commit()


def _get(session: Session, clinic_id: UUID, user_id: UUID) -> tuple[ClinicMember, User]:
    member = session.get(ClinicMember, (clinic_id, user_id))
    user = session.get(User, user_id) if member is not None else None
    if member is None or user is None:
        raise NotFoundError("Clinic member not found")
    return member, user
