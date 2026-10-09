"""Practitioners (docs/01-decisions.md section 5).

* ONE shared record per practitioner across all businesses (``practitioners``); each clinic's own
  details live on the link (``clinic_practitioners``).
* Before creating one, look it up by registration number and link the existing record.
* Shared record: the practitioner himself, the DSM of a linked clinic, or the Platform
  Administrator edit it. Name, registration number and login: DSM or admin only. NOT a Clinic
  Administrator (the record is shared with other businesses).
* Link fields (schedule, holiday, fee, time zone, notes): admin, DSM, Clinic Administrator.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.rbac import ClinicContext, Principal
from app.models import ClinicPractitioner, Practitioner
from app.schemas.practitioners import (
    ClinicPractitionerCreate,
    ClinicPractitionerRead,
    ClinicPractitionerUpdate,
    PractitionerLookup,
    PractitionerRead,
    PractitionerUpdate,
    years_of_experience,
)
from app.services import audit

_LOOKUP = text("SELECT id, full_name, specialty FROM rp_find_practitioner_by_registration(:number)")
_LINK_FIELDS = (
    "designation",
    "consultation_hours",
    "weekly_off_days",
    "consultation_fee",
    "consultation_fee_currency",
    "consultation_time_zone",
    "schedule_notes",
    "is_primary",
)


def practitioner_read(p: Practitioner) -> PractitionerRead:
    return PractitionerRead(
        id=p.id,
        full_name=p.full_name,
        specialty=p.specialty,
        qualifications=p.qualifications,
        registration_number=p.registration_number,
        bio=p.bio,
        practice_start_year=p.practice_start_year,
        years_of_experience=years_of_experience(p.practice_start_year),
        services_and_conditions=list(p.services_and_conditions or []),
        approx_patients_treated=p.approx_patients_treated,
        highlights=p.highlights,
        user_id=p.user_id,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def link_read(link: ClinicPractitioner, p: Practitioner) -> ClinicPractitionerRead:
    return ClinicPractitionerRead(
        clinic_id=link.clinic_id,
        practitioner_id=p.id,
        practitioner=practitioner_read(p),
        designation=link.designation,
        consultation_hours=link.consultation_hours or {},
        weekly_off_days=list(link.weekly_off_days or []),
        consultation_fee=link.consultation_fee,
        consultation_fee_currency=link.consultation_fee_currency,
        consultation_time_zone=link.consultation_time_zone,
        schedule_notes=link.schedule_notes,
        is_primary=link.is_primary,
        is_active=link.is_active,
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


# ------------------------------------------------------------------------------ lookup
def lookup(session: Session, registration_number: str) -> PractitionerLookup | None:
    """Find an EXISTING practitioner by registration number (exact, after upper / trim), also one
    that works only for another business. Minimal fields only."""
    number = registration_number.strip().upper()
    row = session.execute(_LOOKUP, {"number": number}).first() if number else None
    return PractitionerLookup(id=row.id, full_name=row.full_name, specialty=row.specialty) if row else None


# ------------------------------------------------------------------------------ clinic links
def list_links(
    session: Session, ctx: ClinicContext, *, include_inactive: bool
) -> list[ClinicPractitionerRead]:
    query = (
        select(ClinicPractitioner, Practitioner)
        .join(Practitioner, Practitioner.id == ClinicPractitioner.practitioner_id)
        .where(ClinicPractitioner.clinic_id == ctx.clinic_id)
    )
    if not include_inactive:
        query = query.where(ClinicPractitioner.is_active.is_(True))
    rows = session.execute(query.order_by(ClinicPractitioner.is_primary.desc(), Practitioner.full_name))
    return [link_read(link, p) for link, p in rows]


def get_link(session: Session, ctx: ClinicContext, practitioner_id: UUID) -> ClinicPractitionerRead:
    link, p = _link(session, ctx.clinic_id, practitioner_id)
    session.refresh(link)  # show what the database stored (e.g. fee 500 -> 500.00)
    return link_read(link, p)


def add_link(session: Session, ctx: ClinicContext, body: ClinicPractitionerCreate) -> ClinicPractitionerRead:
    if body.practitioner is not None:
        new = Practitioner(**body.practitioner.model_dump(exclude_unset=True))
        session.add(new)
        session.flush()  # an existing registration number fails here: 409 (look it up first)
        practitioner_id, created = new.id, True
        audit.record(
            session,
            actor_user_id=ctx.user_id,
            action="practitioner.created",
            resource_type="practitioner",
            resource_id=new.id,
            clinic_id=ctx.clinic_id,
        )
    elif body.practitioner_id is not None:  # the schema requires exactly one of the two
        if session.get(ClinicPractitioner, (ctx.clinic_id, body.practitioner_id)) is not None:
            raise ConflictError("This practitioner is already linked to this clinic.")
        practitioner_id, created = body.practitioner_id, False
    else:  # pragma: no cover
        raise ConflictError("Give an existing practitioner or a new one.")
    fields = body.model_dump(include=set(_LINK_FIELDS), exclude_unset=True)
    if fields.get("is_primary"):
        _clear_primary(session, ctx.clinic_id)
    link = ClinicPractitioner(clinic_id=ctx.clinic_id, practitioner_id=practitioner_id, **fields)
    session.add(link)
    session.flush()  # an unknown practitioner_id fails here (409)
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="clinic_practitioner.linked",
        resource_type="clinic_practitioner",
        resource_id=practitioner_id,
        clinic_id=ctx.clinic_id,
        details={"new_practitioner": created},
    )
    session.commit()
    return get_link(session, ctx, practitioner_id)


def update_link(
    session: Session, ctx: ClinicContext, practitioner_id: UUID, body: ClinicPractitionerUpdate
) -> ClinicPractitionerRead:
    link, _ = _link(session, ctx.clinic_id, practitioner_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("is_primary"):
        _clear_primary(session, ctx.clinic_id, keep=practitioner_id)
    for name, value in changes.items():
        setattr(link, name, value)
    session.flush()  # the database checks the schedule shape and the time zone again
    if changes:
        audit.record(
            session,
            actor_user_id=ctx.user_id,
            action="clinic_practitioner.updated",
            resource_type="clinic_practitioner",
            resource_id=practitioner_id,
            clinic_id=ctx.clinic_id,
            details={"fields": sorted(changes)},
        )
    session.commit()
    return get_link(session, ctx, practitioner_id)


def _clear_primary(session: Session, clinic_id: UUID, keep: UUID | None = None) -> None:
    """Only one primary practitioner per clinic: the old one stops being primary first."""
    for other in session.scalars(
        select(ClinicPractitioner).where(
            ClinicPractitioner.clinic_id == clinic_id, ClinicPractitioner.is_primary.is_(True)
        )
    ):
        if other.practitioner_id != keep:
            other.is_primary = False
    session.flush()


def _link(
    session: Session, clinic_id: UUID, practitioner_id: UUID
) -> tuple[ClinicPractitioner, Practitioner]:
    link = session.get(ClinicPractitioner, (clinic_id, practitioner_id))
    practitioner = session.get(Practitioner, practitioner_id) if link is not None else None
    if link is None or practitioner is None:
        raise NotFoundError("Practitioner not found at this clinic")
    return link, practitioner


# ------------------------------------------------------------------------------ shared record
def get_practitioner(session: Session, principal: Principal, practitioner_id: UUID) -> PractitionerRead:
    return practitioner_read(_practitioner(session, practitioner_id))


def update_practitioner(
    session: Session, principal: Principal, practitioner_id: UUID, body: PractitionerUpdate
) -> PractitionerRead:
    practitioner = _practitioner(session, practitioner_id)
    changes = body.model_dump(exclude_unset=True)
    is_self = principal.practitioner_id == practitioner.id
    is_staff = principal.is_platform_administrator or bool(
        principal.dsm_clinic_ids & set(_linked_clinic_ids(session, practitioner.id))
    )
    if not (is_staff or is_self):
        raise ForbiddenError(
            "Only the practitioner, the DSM or a Platform Administrator can edit this record."
        )
    staff_only = set(changes) & PractitionerUpdate.STAFF_ONLY
    if staff_only and not is_staff:
        raise ForbiddenError(
            "Only the DSM or a Platform Administrator can change name, registration number or login."
        )
    for name, value in changes.items():
        setattr(practitioner, name, value)
    session.flush()  # a login that is not a 'practitioner' user fails here (trigger): 409
    if changes:
        audit.record(
            session,
            actor_user_id=principal.user_id,
            action="practitioner.updated",
            resource_type="practitioner",
            resource_id=practitioner.id,
            clinic_id=None,
            details={"fields": sorted(changes)},
        )
    session.commit()
    return practitioner_read(practitioner)


def _linked_clinic_ids(session: Session, practitioner_id: UUID) -> list[UUID]:
    return list(
        session.scalars(
            select(ClinicPractitioner.clinic_id).where(ClinicPractitioner.practitioner_id == practitioner_id)
        )
    )


def _practitioner(session: Session, practitioner_id: UUID) -> Practitioner:
    practitioner = session.get(Practitioner, practitioner_id)  # row-level security decides who sees it
    if practitioner is None:
        raise NotFoundError("Practitioner not found")
    return practitioner
