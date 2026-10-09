"""The "Practitioner Profile" screen (docs/01-decisions.md section 14). Empty values are null
(the screen shows "Not provided")."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.core.enums import Weekday
from app.schemas.common import ApiModel
from app.schemas.practitioners import ClinicPractitionerUpdate, PractitionerUpdate


class ConsultationDay(ApiModel):
    day: Weekday
    #: [{"from": "10:00", "to": "14:00"}, ...]; empty = "No consultation"
    slots: list[dict[str, str]]


class ClientOrganizationInformation(ApiModel):
    """Label stays "Client organization information"; the data is the CLINIC's (section 14)."""

    name: str
    #: "Operating since"
    established_year: int | None
    address_line: str | None
    city: str | None
    state: str | None
    postal_code: str | None


class PractitionerProfileRead(ApiModel):
    clinic_id: UUID
    practitioner_id: UUID
    full_name: str
    #: "Specialization"
    specialty: str | None
    qualifications: str | None
    registration_number: str | None
    bio: str | None
    practice_start_year: int | None
    #: computed: this year - practice_start_year (never stored)
    years_of_experience: int | None
    services_and_conditions: list[str] | None
    approx_patients_treated: int | None
    highlights: str | None
    client_organization_information: ClientOrganizationInformation
    designation: str | None
    #: always the 7 days, Monday..Sunday
    consultation_schedule: list[ConsultationDay]
    consultation_time_zone: str
    schedule_notes: str | None
    #: "Weekly holiday"
    weekly_off_days: list[Weekday] | None
    consultation_fee: Decimal | None
    consultation_fee_currency: str


class PractitionerProfileUpdate(ApiModel):
    """The Edit button. Each part has its own rules:

    * ``practitioner``: the shared record (the practitioner himself, the DSM, the admin; name and
      registration number: DSM / admin only; NOT a Clinic Administrator)
    * ``clinic_practitioner``: this clinic's details (admin, DSM, Clinic Administrator; NOT the
      practitioner)
    """

    practitioner: PractitionerUpdate | None = None
    clinic_practitioner: ClinicPractitionerUpdate | None = None
