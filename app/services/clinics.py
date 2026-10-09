"""Client Organizations and clinics (docs/01-decisions.md section 2).

* New leads (and businesses) are created by the Platform Administrator only. A new lead has no DSM
  yet, so only the admin sees it until a portfolio allocation is made.
* Stage moves: ``SET LOCAL rp.stage_note`` then UPDATE; a trigger writes the history (rule 7).
* Archive needs a reason; restore clears it and keeps the stage.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.enums import ClinicStage
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.rbac import ClinicContext, Permission, Principal
from app.models import ClientOrganization, Clinic, ClinicStageChange
from app.schemas.clinics import (
    ClientOrganizationCreate,
    ClientOrganizationRead,
    ClientOrganizationUpdate,
    ClinicArchive,
    ClinicCreate,
    ClinicRead,
    ClinicStageChangeRead,
    ClinicStageUpdate,
    ClinicUpdate,
)
from app.schemas.common import Page
from app.services import audit

_STAGE_NOTE = text("SELECT set_config('rp.stage_note', :note, true)")


# ------------------------------------------------------------------ Client Organizations
def list_client_organizations(
    session: Session, *, q: str | None, limit: int, offset: int
) -> Page[ClientOrganizationRead]:
    """The businesses the caller can see (row-level security decides)."""
    query = select(ClientOrganization)
    if q:
        query = query.where(ClientOrganization.name.ilike(f"%{q.strip()}%"))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(ClientOrganization.name).limit(limit).offset(offset))
    return Page(
        items=[ClientOrganizationRead.model_validate(o) for o in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_client_organization(session: Session, org_id: UUID) -> ClientOrganizationRead:
    return ClientOrganizationRead.model_validate(_org(session, org_id))


def create_client_organization(
    session: Session, principal: Principal, body: ClientOrganizationCreate
) -> ClientOrganizationRead:
    org = _new_org(session, principal, body.name)
    session.commit()
    return ClientOrganizationRead.model_validate(org)


def update_client_organization(
    session: Session, principal: Principal, org_id: UUID, body: ClientOrganizationUpdate
) -> ClientOrganizationRead:
    org = _org(session, org_id)
    org.name = body.name
    audit.record(
        session,
        actor_user_id=principal.user_id,
        action="client_organization.updated",
        resource_type="client_organization",
        resource_id=org.id,
        clinic_id=None,
        details={"fields": ["name"]},
    )
    session.commit()
    return ClientOrganizationRead.model_validate(org)


def _new_org(session: Session, principal: Principal, name: str) -> ClientOrganization:
    org = ClientOrganization(name=name)
    session.add(org)
    session.flush()
    audit.record(
        session,
        actor_user_id=principal.user_id,
        action="client_organization.created",
        resource_type="client_organization",
        resource_id=org.id,
        clinic_id=None,
    )
    return org


def _org(session: Session, org_id: UUID) -> ClientOrganization:
    org = session.get(ClientOrganization, org_id)
    if org is None:
        raise NotFoundError("Client Organization not found")
    return org


# ------------------------------------------------------------------------------ clinics
def list_clinics(
    session: Session,
    *,
    q: str | None,
    stage: ClinicStage | None,
    is_active: bool | None,
    client_organization_id: UUID | None,
    limit: int,
    offset: int,
) -> Page[ClinicRead]:
    """The clinics the caller can see. Row-level security already hides the others."""
    query = select(Clinic)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Clinic.name.ilike(like), Clinic.city.ilike(like)))
    if stage is not None:
        query = query.where(Clinic.stage == stage)
    if is_active is not None:
        query = query.where(Clinic.is_active.is_(is_active))
    if client_organization_id is not None:
        query = query.where(Clinic.client_organization_id == client_organization_id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(Clinic.name, Clinic.id).limit(limit).offset(offset))
    return Page(items=[ClinicRead.model_validate(c) for c in rows], total=total, limit=limit, offset=offset)


def get_clinic(session: Session, ctx: ClinicContext) -> ClinicRead:
    return ClinicRead.model_validate(_clinic(session, ctx.clinic_id))


def create_clinic(session: Session, principal: Principal, body: ClinicCreate) -> ClinicRead:
    if body.client_organization_id is not None:
        org = _org(session, body.client_organization_id)
    else:
        org = _new_org(session, principal, body.client_organization_name or body.name)
    fields = body.model_dump(
        exclude={"client_organization_id", "client_organization_name"}, exclude_unset=False
    )
    clinic = Clinic(client_organization_id=org.id, **fields)
    session.add(clinic)
    session.flush()
    audit.record(
        session,
        actor_user_id=principal.user_id,
        action="clinic.created",
        resource_type="clinic",
        resource_id=clinic.id,
        clinic_id=clinic.id,
        details={"client_organization_id": str(org.id)},
    )
    session.commit()
    return ClinicRead.model_validate(clinic)


def update_clinic(session: Session, ctx: ClinicContext, body: ClinicUpdate) -> ClinicRead:
    changes = body.model_dump(exclude_unset=True)
    if "client_organization_id" in changes:
        if not ctx.can(Permission.CLINICS_MANAGE):
            raise ForbiddenError(
                "Only the DSM or a Platform Administrator can move a clinic to another business."
            )
        _org(session, changes["client_organization_id"])  # must exist and be visible
    clinic = _clinic(session, ctx.clinic_id)
    for name, value in changes.items():
        setattr(clinic, name, value)
    session.flush()
    if changes:
        audit.record(
            session,
            actor_user_id=ctx.user_id,
            action="clinic.updated",
            resource_type="clinic",
            resource_id=clinic.id,
            clinic_id=clinic.id,
            details={"fields": sorted(changes)},
        )
    session.commit()
    return ClinicRead.model_validate(clinic)


def change_stage(session: Session, ctx: ClinicContext, body: ClinicStageUpdate) -> ClinicRead:
    clinic = _clinic(session, ctx.clinic_id)
    if clinic.stage == body.stage:
        raise ConflictError("The clinic is already in this stage.")
    previous = clinic.stage
    # The stage trigger reads rp.stage_note and rp.user_id to write the history row (rule 7).
    session.execute(_STAGE_NOTE, {"note": body.note or ""})
    clinic.stage = body.stage
    session.flush()
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="clinic.stage_changed",
        resource_type="clinic",
        resource_id=clinic.id,
        clinic_id=clinic.id,
        details={"from_stage": previous.value, "to_stage": body.stage.value},
    )
    session.commit()
    return ClinicRead.model_validate(clinic)


def stage_changes(session: Session, ctx: ClinicContext) -> list[ClinicStageChangeRead]:
    rows = session.scalars(
        select(ClinicStageChange)
        .where(ClinicStageChange.clinic_id == ctx.clinic_id)
        .order_by(ClinicStageChange.changed_at.desc(), ClinicStageChange.id)
    )
    return [ClinicStageChangeRead.model_validate(r) for r in rows]


def archive_clinic(session: Session, ctx: ClinicContext, body: ClinicArchive) -> ClinicRead:
    clinic = _clinic(session, ctx.clinic_id)
    if not clinic.is_active:
        raise ConflictError("The clinic is already archived.")
    clinic.is_active = False
    clinic.archived_reason = body.archived_reason
    return _saved(session, ctx, clinic, "clinic.archived", {"archived_reason": body.archived_reason})


def restore_clinic(session: Session, ctx: ClinicContext) -> ClinicRead:
    clinic = _clinic(session, ctx.clinic_id)
    if clinic.is_active:
        raise ConflictError("The clinic is not archived.")
    clinic.is_active = True
    clinic.archived_reason = None  # restore clears the reason and keeps the stage
    return _saved(session, ctx, clinic, "clinic.restored", {})


def _saved(
    session: Session, ctx: ClinicContext, clinic: Clinic, action: str, details: dict[str, str]
) -> ClinicRead:
    session.flush()
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action=action,
        resource_type="clinic",
        resource_id=clinic.id,
        clinic_id=clinic.id,
        details=details,
    )
    session.commit()
    return ClinicRead.model_validate(clinic)


def _clinic(session: Session, clinic_id: UUID) -> Clinic:
    clinic = session.get(Clinic, clinic_id)
    if clinic is None:
        raise NotFoundError("Clinic not found")
    return clinic
