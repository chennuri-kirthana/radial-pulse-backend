"""Step F: the "Practitioner Profile" screen (docs/01-decisions.md section 14).

GET combines the shared practitioner record, the CLINIC's "Client organization information" and
that clinic's link (schedule Monday..Sunday, holiday, fee, time zone, notes). Empty → null.
PATCH (Edit) changes both parts, each with its own permission rule, in ONE transaction.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import WEEKDAYS
from app.core.errors import ForbiddenError, NotFoundError
from app.core.rbac import ClinicContext, Permission
from app.models import Clinic, ClinicPractitioner, Practitioner
from app.schemas.practitioner_profile import (
    ClientOrganizationInformation,
    ConsultationDay,
    PractitionerProfileRead,
    PractitionerProfileUpdate,
)
from app.schemas.practitioners import PractitionerUpdate, years_of_experience
from app.services import audit


def _blank(value: str | None) -> str | None:
    return value if value and value.strip() else None


def get_profile(
    session: Session, ctx: ClinicContext, practitioner_id: UUID | None
) -> PractitionerProfileRead:
    link, practitioner = _pick(session, ctx, practitioner_id)
    clinic = session.get(Clinic, ctx.clinic_id)
    if clinic is None:  # pragma: no cover - clinic_access checked it
        raise NotFoundError("Clinic not found")
    hours = link.consultation_hours or {}
    return PractitionerProfileRead(
        clinic_id=ctx.clinic_id,
        practitioner_id=practitioner.id,
        full_name=practitioner.full_name,
        specialty=_blank(practitioner.specialty),
        qualifications=_blank(practitioner.qualifications),
        registration_number=_blank(practitioner.registration_number),
        bio=_blank(practitioner.bio),
        practice_start_year=practitioner.practice_start_year,
        years_of_experience=years_of_experience(practitioner.practice_start_year),
        services_and_conditions=list(practitioner.services_and_conditions) or None,
        approx_patients_treated=practitioner.approx_patients_treated,
        highlights=_blank(practitioner.highlights),
        client_organization_information=ClientOrganizationInformation(
            name=clinic.name,
            established_year=clinic.established_year,
            address_line=_blank(clinic.address_line),
            city=_blank(clinic.city),
            state=_blank(clinic.state),
            postal_code=_blank(clinic.postal_code),
        ),
        designation=_blank(link.designation),
        consultation_schedule=[
            ConsultationDay(day=day, slots=list(hours.get(day.value, []))) for day in WEEKDAYS
        ],
        consultation_time_zone=link.consultation_time_zone,
        schedule_notes=_blank(link.schedule_notes),
        weekly_off_days=[d for d in WEEKDAYS if d.value in set(link.weekly_off_days or [])] or None,
        consultation_fee=link.consultation_fee,
        consultation_fee_currency=link.consultation_fee_currency,
    )


def update_profile(
    session: Session, ctx: ClinicContext, practitioner_id: UUID, body: PractitionerProfileUpdate
) -> PractitionerProfileRead:
    link, practitioner = _pick(session, ctx, practitioner_id)
    shared = body.practitioner.model_dump(exclude_unset=True) if body.practitioner else {}
    local = body.clinic_practitioner.model_dump(exclude_unset=True) if body.clinic_practitioner else {}

    if local and not ctx.can(Permission.CLINIC_PRACTITIONERS_MANAGE):
        raise ForbiddenError(
            "Only the Clinic Administrator, the DSM or a Platform Administrator change these details."
        )
    if shared:
        is_self = ctx.acting_practitioner_id == practitioner.id
        if not (ctx.is_staff or is_self):
            raise ForbiddenError(
                "Only the practitioner, the DSM or a Platform Administrator can edit this record."
            )
        if set(shared) & PractitionerUpdate.STAFF_ONLY and not ctx.is_staff:
            raise ForbiddenError(
                "Only the DSM or a Platform Administrator can change name, registration number or login."
            )

    for name, value in shared.items():
        setattr(practitioner, name, value)
    for name, value in local.items():
        setattr(link, name, value)
    session.flush()  # the database checks every value again (400 / 409 with its message)
    if shared:
        audit.record(
            session,
            actor_user_id=ctx.user_id,
            action="practitioner.updated",
            resource_type="practitioner",
            resource_id=practitioner.id,
            clinic_id=ctx.clinic_id,
            details={"fields": sorted(shared)},
        )
    if local:
        audit.record(
            session,
            actor_user_id=ctx.user_id,
            action="clinic_practitioner.updated",
            resource_type="clinic_practitioner",
            resource_id=practitioner.id,
            clinic_id=ctx.clinic_id,
            details={"fields": sorted(local)},
        )
    session.commit()
    session.refresh(link)
    session.refresh(practitioner)
    return get_profile(session, ctx, practitioner.id)


def _pick(
    session: Session, ctx: ClinicContext, practitioner_id: UUID | None
) -> tuple[ClinicPractitioner, Practitioner]:
    """The chosen practitioner, or the clinic's main one (primary first, then by name)."""
    query = (
        select(ClinicPractitioner, Practitioner)
        .join(Practitioner, Practitioner.id == ClinicPractitioner.practitioner_id)
        .where(ClinicPractitioner.clinic_id == ctx.clinic_id, ClinicPractitioner.is_active.is_(True))
    )
    if practitioner_id is not None:
        query = query.where(ClinicPractitioner.practitioner_id == practitioner_id)
    elif ctx.acting_practitioner_id is not None:  # a practitioner opens his own profile
        query = query.where(ClinicPractitioner.practitioner_id == ctx.acting_practitioner_id)
    row = session.execute(
        query.order_by(ClinicPractitioner.is_primary.desc(), Practitioner.full_name)
    ).first()
    if row is None:
        raise NotFoundError("Practitioner not found at this clinic")
    link, practitioner = row
    return link, practitioner
