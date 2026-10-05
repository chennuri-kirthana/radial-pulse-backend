"""Clinics, their stages, practitioners, clinic team (memberships) and DSM allocation."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import (
    AssetKind,
    AssetStatus,
    ClinicRole,
    ClinicStage,
    ClinicStageGroup,
    NotificationCategory,
    PlatformRole,
)
from app.core.errors import (
    ConflictError,
    DomainValidationError,
    ForbiddenError,
    InvalidStateError,
    NotFoundError,
)
from app.core.rbac import GRANTABLE_CLINIC_ROLES, ClinicContext, Permission, Principal
from app.db.base import utcnow
from app.db.tenant import add_clinic_to_scope
from app.integrations.invites import InviteSender
from app.models import (
    Clinic,
    ClinicAssignment,
    ClinicMembership,
    ClinicPractitioner,
    ClinicProfile,
    ClinicStageHistory,
    Organization,
    Practitioner,
    User,
)
from app.repositories.assets import AssetRepository
from app.repositories.tenancy import (
    AssignmentRepository,
    ClinicRepository,
    MembershipRepository,
    OrganizationRepository,
    PractitionerRepository,
    StageHistoryRepository,
)
from app.repositories.users import UserRepository
from app.schemas.clinics import (
    AreaCount,
    AssignmentSet,
    ClinicCreate,
    ClinicListItem,
    ClinicRead,
    ClinicUpdate,
    PersonRef,
    PractitionerCreate,
    PractitionerRead,
    PractitionerUpdate,
    StageChange,
    TeamMemberCreate,
    TeamMemberRead,
)
from app.services import audit, notify
from app.services.invitations import send_invite


# ----------------------------------------------------------------------- clinics
def list_clinics(
    session: Session,
    principal: Principal,
    limit: int,
    offset: int,
    *,
    stages: Sequence[ClinicStage] | None = None,
    group: ClinicStageGroup | None = None,
    dsm_user_id: UUID | None = None,
    unassigned: bool = False,
    search: str | None = None,
    archived: bool = False,
) -> tuple[list[ClinicListItem], int]:
    if group is not None:
        # An Admin tab = its stages; narrowed further when `stages` was given as well.
        wanted = [s for s in group.stages if not stages or s in stages]
        if not wanted:
            return [], 0
        stages = wanted
    repo = ClinicRepository(session)
    clinics, total = repo.list_accessible(
        principal.accessible_clinic_ids(), limit, offset,
        stages=stages, dsm_user_id=dsm_user_id, unassigned=unassigned, search=search, archived=archived,
    )  # fmt: skip
    ids = [c.id for c in clinics]
    practitioners = repo.primary_practitioner_names(ids)
    dsms = repo.active_dsms(ids)
    work = repo.open_work_counts(ids)
    items = []
    for c in clinics:
        dsm = dsms.get(c.id)
        items.append(
            ClinicListItem.model_validate(
                {
                    **ClinicRead.model_validate(c).model_dump(),
                    "primary_practitioner_name": practitioners.get(c.id),
                    "dsm": PersonRef(id=dsm.id, full_name=dsm.full_name, email=dsm.email) if dsm else None,
                    "open_work": [AreaCount(area=a, open_count=n) for a, n in work.get(c.id, [])],
                }
            )
        )
    return items, total


def get_clinic(session: Session, ctx: ClinicContext) -> Clinic:
    clinic = ClinicRepository(session).get(ctx.clinic_id)
    if clinic is None:
        raise NotFoundError("Clinic not found")
    return clinic


def create_clinic(session: Session, principal: Principal, data: ClinicCreate) -> Clinic:
    """Add a clinic (a lead). A Digital Success Manager who adds it becomes its DSM automatically."""
    if data.organization_id is not None:
        org = OrganizationRepository(session).get(data.organization_id)
        # Adding a branch requires access to at least one clinic already in that organization.
        sibling_ids = ClinicRepository(session).ids_in_organization(data.organization_id) if org else []
        if org is None or not (
            principal.is_platform_administrator
            or any(principal.can_access_clinic(cid) for cid in sibling_ids)
        ):
            raise NotFoundError("Organization not found")
    else:
        org = Organization(name=data.name, created_by_user_id=principal.user_id)
        session.add(org)
        session.flush()

    # Authorization already passed (clinics:create). Widen the DB tenant scope to the new
    # clinic BEFORE inserting it, or row-level security would (correctly) refuse the insert.
    clinic_id = uuid.uuid4()
    add_clinic_to_scope(session, clinic_id)
    fields = data.model_dump(
        exclude={"organization_id", "primary_practitioner_name", "website_url", "country"}
    )
    clinic = Clinic(
        id=clinic_id,
        organization_id=org.id,
        country=data.country.upper(),
        website_url=str(data.website_url) if data.website_url else None,
        stage=ClinicStage.PROSPECTIVE_CLIENT,
        stage_changed_at=utcnow(),
        created_by_user_id=principal.user_id,
        **fields,
    )
    session.add(clinic)
    session.flush()
    session.add(ClinicProfile(clinic_id=clinic.id, updated_by_user_id=principal.user_id))
    session.add(
        ClinicStageHistory(
            clinic_id=clinic.id, from_stage=None, to_stage=ClinicStage.PROSPECTIVE_CLIENT,
            changed_by_user_id=principal.user_id,
        )
    )  # fmt: skip
    if data.primary_practitioner_name:
        person = Practitioner(organization_id=org.id, full_name=data.primary_practitioner_name)
        session.add(person)
        session.flush()
        session.add(ClinicPractitioner(clinic_id=clinic.id, practitioner_id=person.id, is_primary=True))
    if principal.platform_role is PlatformRole.DIGITAL_SUCCESS_MANAGER:
        session.add(
            ClinicAssignment(
                clinic_id=clinic.id, user_id=principal.user_id, assigned_by_user_id=principal.user_id
            )
        )

    audit.record(
        session,
        actor=principal,
        action="clinic.create",
        resource_type="clinic",
        resource_id=clinic.id,
        clinic_id=clinic.id,
        details={"organization_id": str(org.id), "new_organization": data.organization_id is None},
    )
    session.commit()
    return clinic


def update_clinic(session: Session, ctx: ClinicContext, data: ClinicUpdate) -> Clinic:
    clinic = get_clinic(session, ctx)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("cover_asset_id") is not None:
        asset = AssetRepository(session).get_in_clinic(ctx.clinic_id, changes["cover_asset_id"])
        if asset is None:
            raise NotFoundError("Asset not found in this clinic")
        if asset.kind is not AssetKind.CLINIC_PHOTO or asset.status is not AssetStatus.UPLOADED:
            raise DomainValidationError("The cover must be an uploaded clinic_photo")
    latitude = changes.get("latitude", clinic.latitude)
    longitude = changes.get("longitude", clinic.longitude)
    if (latitude is None) != (longitude is None):
        raise DomainValidationError("latitude and longitude must be set together")
    for field, value in changes.items():
        setattr(clinic, field, str(value) if field == "website_url" and value is not None else value)
    audit.record(
        session,
        actor=ctx.principal,
        action="clinic.update",
        resource_type="clinic",
        resource_id=clinic.id,
        clinic_id=clinic.id,
        details={"fields": sorted(changes)},
    )
    session.commit()
    return clinic


# ------------------------------------------------------------------------ stages
def change_stage(session: Session, ctx: ClinicContext, data: StageChange) -> Clinic:
    """Move the clinic to another step (the stepper). Radial Pulse staff only (clinics:manage)."""
    clinic = get_clinic(session, ctx)
    if not clinic.is_active:
        raise InvalidStateError("This clinic is archived. Restore it first")
    if clinic.stage is data.stage:
        raise InvalidStateError(f"The clinic is already at {data.stage.value}")
    if (
        data.stage is ClinicStage.ACTIVE_CLIENT
        and MembershipRepository(session).count_active_admins(clinic.id) == 0
    ):
        raise InvalidStateError("Add a Clinic Administrator (the doctor's login) before marking Customer")
    previous = clinic.stage
    clinic.stage = data.stage
    clinic.stage_changed_at = utcnow()
    session.add(
        ClinicStageHistory(
            clinic_id=clinic.id, from_stage=previous, to_stage=data.stage, note=data.note,
            changed_by_user_id=ctx.user_id,
        )
    )  # fmt: skip
    audit.record(
        session,
        actor=ctx.principal,
        action="clinic.stage_change",
        resource_type="clinic",
        resource_id=clinic.id,
        clinic_id=clinic.id,
        details={"from": previous.value, "to": data.stage.value, "has_note": data.note is not None},
    )
    session.commit()
    return clinic


def stage_history(session: Session, ctx: ClinicContext) -> list[ClinicStageHistory]:
    return StageHistoryRepository(session).list_for_clinic(ctx.clinic_id)


def archive_clinic(session: Session, ctx: ClinicContext, reason: str) -> Clinic:
    """The clinic said no (or is otherwise closed). Keeps its stage and history."""
    clinic = get_clinic(session, ctx)
    if not clinic.is_active:
        raise InvalidStateError("The clinic is already archived")
    clinic.is_active = False
    clinic.archived_reason = reason
    audit.record(
        session, actor=ctx.principal, action="clinic.archive", resource_type="clinic",
        resource_id=clinic.id, clinic_id=clinic.id, details={"stage": clinic.stage.value},
    )  # fmt: skip
    session.commit()
    return clinic


def restore_clinic(session: Session, ctx: ClinicContext) -> Clinic:
    clinic = get_clinic(session, ctx)
    if clinic.is_active:
        raise InvalidStateError("The clinic is not archived")
    clinic.is_active = True
    clinic.archived_reason = None
    audit.record(
        session, actor=ctx.principal, action="clinic.restore", resource_type="clinic",
        resource_id=clinic.id, clinic_id=clinic.id, details={"stage": clinic.stage.value},
    )  # fmt: skip
    session.commit()
    return clinic


# ----------------------------------------------------------------- practitioners
def _practitioner_read(link: ClinicPractitioner, person: Practitioner) -> PractitionerRead:
    return PractitionerRead(
        id=person.id,
        clinic_id=link.clinic_id,
        full_name=person.full_name,
        specialty=person.specialty,
        qualifications=person.qualifications,
        registration_number=person.registration_number,
        bio=person.bio,
        is_primary=link.is_primary,
        user_id=person.user_id,
        is_active=link.is_active,
        created_at=link.created_at,
    )


def list_practitioners(
    session: Session, ctx: ClinicContext, limit: int, offset: int
) -> tuple[list[PractitionerRead], int]:
    rows, total = PractitionerRepository(session).list_for_clinic(ctx.clinic_id, limit, offset)
    return [_practitioner_read(link, person) for link, person in rows], total


def _check_registration_free(
    repo: PractitionerRepository, organization_id: UUID, number: str | None, own_id: UUID | None = None
) -> None:
    """One doctor record per registration number inside a business (a database rule since 0011)."""
    if not number:
        return
    other = repo.find_by_registration(organization_id, number)
    if other is not None and other.id != own_id:
        raise ConflictError(
            f"A doctor with registration number {number} already exists in this business "
            f"({other.full_name}). Link them with practitioner_id={other.id} instead"
        )


def _commit_practitioner(session: Session) -> None:
    try:
        session.commit()
    except IntegrityError as exc:  # two people added the same doctor at the same moment
        session.rollback()
        raise ConflictError(
            "This doctor was just added or changed by someone else. Reload and try again"
        ) from exc


def create_practitioner(session: Session, ctx: ClinicContext, data: PractitionerCreate) -> PractitionerRead:
    """Add a NEW practitioner to this clinic, or link one who works at a sibling branch."""
    repo = PractitionerRepository(session)
    clinic = get_clinic(session, ctx)
    if data.practitioner_id is not None:
        person = repo.get_person(data.practitioner_id)
        # Only a doctor of the SAME business can be linked (never another client's record).
        if person is None or person.organization_id != clinic.organization_id:
            raise NotFoundError("Practitioner not found in this business")
        existing = repo.get_in_clinic(ctx.clinic_id, person.id)
        if existing is not None:
            raise ConflictError(
                "Already works at this clinic"
                if existing[0].is_active
                else "Was removed from this clinic. Reactivate them instead"
            )
        action = "practitioner.link"
    else:
        if data.user_id is not None:
            _require_clinic_member(session, ctx.clinic_id, data.user_id)
        _check_registration_free(repo, clinic.organization_id, data.registration_number)
        person = Practitioner(
            organization_id=clinic.organization_id,
            **data.model_dump(exclude={"practitioner_id", "is_primary"}),
        )
        session.add(person)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise ConflictError(
                "A doctor with this registration number already exists in this business"
            ) from exc
        action = "practitioner.create"
    if data.is_primary:
        repo.clear_primary(ctx.clinic_id)
    link = ClinicPractitioner(clinic_id=ctx.clinic_id, practitioner_id=person.id, is_primary=data.is_primary)
    session.add(link)
    session.flush()
    audit.record(
        session,
        actor=ctx.principal,
        action=action,
        resource_type="practitioner",
        resource_id=person.id,
        clinic_id=ctx.clinic_id,
        details={"is_primary": data.is_primary},
    )
    _commit_practitioner(session)
    return _practitioner_read(link, person)


PERSON_FIELDS = ("full_name", "specialty", "qualifications", "registration_number", "bio")
LINK_FIELDS = ("is_primary", "is_active")


def update_practitioner(
    session: Session, ctx: ClinicContext, practitioner_id: UUID, data: PractitionerUpdate
) -> PractitionerRead:
    repo = PractitionerRepository(session)
    found = repo.get_in_clinic(ctx.clinic_id, practitioner_id)
    if found is None:
        raise NotFoundError("Practitioner not found")
    link, person = found
    changes = data.model_dump(exclude_unset=True)
    if "registration_number" in changes:
        _check_registration_free(repo, person.organization_id, changes["registration_number"], person.id)
    if changes.get("is_primary") and not (link.is_primary and link.is_active):
        repo.clear_primary(ctx.clinic_id)  # explicitly made the main one
    elif changes.get("is_active") and not link.is_active and link.is_primary:
        # Coming back to the clinic: someone else may be the main practitioner by now.
        link.is_primary = False
    for field, value in changes.items():
        setattr(person if field in PERSON_FIELDS else link, field, value)
    audit.record(
        session,
        actor=ctx.principal,
        action="practitioner.update",
        resource_type="practitioner",
        resource_id=person.id,
        clinic_id=ctx.clinic_id,
        details={"fields": sorted(changes)},
    )
    _commit_practitioner(session)
    return _practitioner_read(link, person)


# -------------------------------------------------------------------------- team
def _team_read(m: ClinicMembership, u: User) -> TeamMemberRead:
    return TeamMemberRead(
        id=m.id,
        clinic_id=m.clinic_id,
        user_id=u.id,
        email=u.email,
        full_name=u.full_name,
        role=m.role,
        is_active=m.is_active,
        has_signed_in=u.cognito_sub is not None,
    )


def list_team(session: Session, ctx: ClinicContext) -> list[TeamMemberRead]:
    return [_team_read(m, u) for m, u in MembershipRepository(session).team_for_clinic(ctx.clinic_id)]


def add_team_member(
    session: Session, ctx: ClinicContext, data: TeamMemberCreate, invites: InviteSender, sign_in_url: str
) -> TeamMemberRead:
    """Add a Clinic Administrator or Clinic Team Member (by the DSM, Admin, or a Clinic
    Administrator of this clinic).

    Creates the (clinic_user) account if the email is new and sends an invite email.
    """
    if data.role not in GRANTABLE_CLINIC_ROLES:
        raise DomainValidationError(f"The {data.role.value} role is not available yet")
    users = UserRepository(session)
    # An existing account may belong to ANOTHER clinic we cannot see (row-level security on
    # users): look it up by email with the narrow lookup, and load it only once it is on our team.
    match = users.find_by_email(data.email)
    user: User | None = None
    if match is None:
        user = User(
            email=data.email,
            full_name=data.full_name,
            platform_role=PlatformRole.CLINIC_USER,
            created_by_user_id=ctx.principal.user_id,
        )
        session.add(user)
        session.flush()
        user_id = user.id
    elif match.platform_role is not PlatformRole.CLINIC_USER:
        raise ConflictError("That email belongs to a Radial Pulse staff account")
    else:
        user_id = match.id

    memberships = MembershipRepository(session)
    existing = memberships.get(ctx.clinic_id, user_id)
    if existing is not None:
        raise ConflictError(
            "This person is already on the clinic team"
            if existing.is_active
            else "This person was removed from the team. Reactivate them instead"
        )
    membership = ClinicMembership(
        clinic_id=ctx.clinic_id, user_id=user_id, role=data.role, invited_by_user_id=ctx.principal.user_id
    )
    session.add(membership)
    session.flush()
    if user is None:
        user = users.get(user_id)  # visible now: they are on this clinic's team
        if user is None:  # pragma: no cover - the membership row makes it visible
            raise NotFoundError("Account not found")
    audit.record(
        session,
        actor=ctx.principal,
        action="team.add",
        resource_type="clinic_membership",
        resource_id=membership.id,
        clinic_id=ctx.clinic_id,
        details={"role": data.role.value, "user_id": str(user_id)},
    )
    session.commit()
    if user.cognito_sub is None:
        clinic = ClinicRepository(session).get(ctx.clinic_id)
        send_invite(
            session, actor=ctx.principal, user=user, role=data.role, invites=invites, sign_in_url=sign_in_url,
            clinic_id=ctx.clinic_id, clinic_name=clinic.name if clinic else None,
        )  # fmt: skip
    return _team_read(membership, user)


def set_team_member_active(
    session: Session, ctx: ClinicContext, membership_id: UUID, is_active: bool
) -> TeamMemberRead:
    memberships = MembershipRepository(session)
    membership = memberships.get_in_clinic(ctx.clinic_id, membership_id)
    if membership is None:
        raise NotFoundError("Team member not found")
    user = UserRepository(session).get(membership.user_id)
    if user is None:  # pragma: no cover - FK guarantees it
        raise NotFoundError("Team member not found")
    if membership.is_active == is_active:
        return _team_read(membership, user)
    if not is_active and membership.role is ClinicRole.CLINIC_ADMINISTRATOR:
        clinic = get_clinic(session, ctx)
        # Removing someone whose login is already disabled does not reduce the real admin count.
        remaining = memberships.count_active_admins(clinic.id) - (1 if user.is_active else 0)
        if clinic.stage is ClinicStage.ACTIVE_CLIENT and remaining < 1:
            raise InvalidStateError("A Customer clinic must keep at least one Clinic Administrator")
    membership.is_active = is_active
    audit.record(
        session,
        actor=ctx.principal,
        action="team.reactivate" if is_active else "team.deactivate",
        resource_type="clinic_membership",
        resource_id=membership.id,
        clinic_id=ctx.clinic_id,
        details={"user_id": str(user.id)},
    )
    session.commit()
    return _team_read(membership, user)


def resend_team_invite(
    session: Session, ctx: ClinicContext, membership_id: UUID, invites: InviteSender, sign_in_url: str
) -> bool:
    membership = MembershipRepository(session).get_in_clinic(ctx.clinic_id, membership_id)
    if membership is None or not membership.is_active:
        raise NotFoundError("Team member not found")
    user = UserRepository(session).get(membership.user_id)
    if user is None:  # pragma: no cover
        raise NotFoundError("Team member not found")
    if user.cognito_sub is not None:
        raise InvalidStateError("This person has already signed in")
    clinic = get_clinic(session, ctx)
    return send_invite(
        session, actor=ctx.principal, user=user, role=membership.role, invites=invites,
        sign_in_url=sign_in_url, clinic_id=ctx.clinic_id, clinic_name=clinic.name,
    )  # fmt: skip


# ------------------------------------------------------ portfolio allocation (DSM)
def list_assignments(session: Session, ctx: ClinicContext) -> list[ClinicAssignment]:
    return AssignmentRepository(session).for_clinic(ctx.clinic_id)


def _require_assignment_manager(principal: Principal) -> None:
    if not principal.has(Permission.ASSIGNMENTS_MANAGE):
        raise ForbiddenError()


def set_assignment(
    session: Session, principal: Principal, clinic_id: UUID, data: AssignmentSet
) -> ClinicAssignment:
    """Make this DSM THE clinic's DSM ("Update Assignment"). The previous one is ended, not deleted."""
    _require_assignment_manager(principal)
    clinic = ClinicRepository(session).get(clinic_id)
    if clinic is None:
        raise NotFoundError("Clinic not found")
    target = UserRepository(session).get(data.user_id)
    if target is None or not target.is_active:
        raise NotFoundError("User not found")
    if target.platform_role is not PlatformRole.DIGITAL_SUCCESS_MANAGER:
        raise DomainValidationError("Only Digital Success Managers can be assigned to clinics")

    repo = AssignmentRepository(session)
    current = repo.active_for_clinic(clinic_id)
    if current is not None and current.user_id == target.id:
        return current
    previous_user_id = current.user_id if current else None
    if current is not None:
        current.is_active = False
        session.flush()  # end the old row first: only ONE active row per clinic is allowed
    existing = repo.find(clinic_id, target.id)
    if existing is not None:
        existing.is_active = True
        existing.assigned_by_user_id = principal.user_id
        assignment = existing
    else:
        assignment = ClinicAssignment(
            clinic_id=clinic_id, user_id=target.id, assigned_by_user_id=principal.user_id
        )
        session.add(assignment)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise ConflictError("The clinic's DSM was changed by someone else. Reload and try again") from exc
    notify.send(
        session,
        user_id=target.id,
        category=NotificationCategory.CLINIC_ASSIGNED,
        clinic_id=clinic_id,
        kind="assignment.new",
        title=f"New clinic in your portfolio: {clinic.name}",
        link=f"/clinics/{clinic_id}",
    )
    audit.record(
        session,
        actor=principal,
        action="assignment.change",
        resource_type="clinic_assignment",
        resource_id=assignment.id,
        clinic_id=clinic_id,
        details={
            "from_user_id": str(previous_user_id) if previous_user_id else None,
            "to_user_id": str(target.id),
        },
    )
    session.commit()
    return assignment


def end_assignment(session: Session, principal: Principal, clinic_id: UUID) -> None:
    """Leave the clinic without a DSM."""
    _require_assignment_manager(principal)
    current = AssignmentRepository(session).active_for_clinic(clinic_id)
    if current is None:
        raise NotFoundError("This clinic has no DSM")
    current.is_active = False
    audit.record(
        session,
        actor=principal,
        action="assignment.end",
        resource_type="clinic_assignment",
        resource_id=current.id,
        clinic_id=clinic_id,
        details={"user_id": str(current.user_id)},
    )
    session.commit()


# ----------------------------------------------------------------------- helpers
def _require_clinic_member(session: Session, clinic_id: UUID, user_id: UUID) -> None:
    membership = MembershipRepository(session).get(clinic_id, user_id)
    if membership is None or not membership.is_active:
        raise DomainValidationError("user_id must belong to a member of this clinic's team")
