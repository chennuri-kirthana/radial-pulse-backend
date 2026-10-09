"""Practitioners: the SHARED record and each clinic's link (docs/01-decisions.md sections 5 and 14)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BeforeValidator, Field, model_validator

from app.core.enums import WEEKDAYS, Weekday
from app.schemas.common import ApiModel, CurrencyCode, PatchModel

_CLOCK = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


def check_consultation_hours(value: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """The ONE shape (docs/01 section 14): ``{"mon": [{"from": "10:00", "to": "14:00"}], ..., "sun": []}``.

    Keys mon..sun only; each value a list of slots; each slot exactly ``from`` and ``to`` as
    24-hour HH:MM with ``from`` < ``to``. A missing day or ``[]`` = no consultation. The database
    refuses anything else too.
    """
    if not isinstance(value, dict):
        raise ValueError("must be an object with days mon..sun")
    out: dict[str, list[dict[str, str]]] = {}
    for day, slots in value.items():
        if day not in {d.value for d in Weekday}:
            raise ValueError(f"unknown day {day!r}: use mon, tue, wed, thu, fri, sat, sun")
        if not isinstance(slots, list):
            raise ValueError(f"{day}: must be a list of time slots")
        clean = []
        for slot in slots:
            if not isinstance(slot, dict) or set(slot) != {"from", "to"}:
                raise ValueError(f"{day}: each slot needs exactly 'from' and 'to'")
            start, end = slot["from"], slot["to"]
            if not (
                isinstance(start, str) and isinstance(end, str) and _CLOCK.match(start) and _CLOCK.match(end)
            ):
                raise ValueError(f"{day}: times must be HH:MM (24-hour)")
            if not start < end:
                raise ValueError(f"{day}: 'from' must be before 'to'")
            clean.append({"from": start, "to": end})
        out[day] = clean
    return out


def check_time_zone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("not a known time zone (e.g. Asia/Kolkata)") from exc
    return value


def not_in_future(year: int) -> int:
    if year > datetime.now(UTC).year:
        raise ValueError("cannot be in the future")
    return year


def _registration(value: object) -> object:
    """'ka-1234 ' and 'KA-1234' are the same number: store upper-case, trimmed; empty = none."""
    if isinstance(value, str):
        value = value.strip().upper()
        return value or None
    return value


def _unique_days(days: list[Weekday]) -> list[Weekday]:
    return [d for d in WEEKDAYS if d in set(days)]


ConsultationHours = Annotated[dict[str, Any], AfterValidator(check_consultation_hours)]
TimeZone = Annotated[str, Field(max_length=64), AfterValidator(check_time_zone)]
StartYear = Annotated[int, Field(ge=1940), AfterValidator(not_in_future)]
RegistrationNumber = Annotated[str | None, BeforeValidator(_registration), Field(default=None, max_length=64)]
ServiceItem = Annotated[str, Field(min_length=1, max_length=200)]
WeeklyOffDays = Annotated[list[Weekday], Field(max_length=7), AfterValidator(_unique_days)]
Fee = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2)]


def years_of_experience(practice_start_year: int | None) -> int | None:
    """Never stored (CLAUDE.md rule 14): this year - practice_start_year."""
    if practice_start_year is None:
        return None
    return max(datetime.now(UTC).year - practice_start_year, 0)


# ------------------------------------------------------------------------------ shared record
class _PractitionerFields(PatchModel):
    """Fields the practitioner himself, the DSM or the admin may change."""

    specialty: str | None = Field(default=None, max_length=120)
    qualifications: str | None = Field(default=None, max_length=300)
    bio: str | None = Field(default=None, max_length=10_000)
    practice_start_year: StartYear | None = None
    services_and_conditions: list[ServiceItem] | None = Field(default=None, max_length=100)
    approx_patients_treated: int | None = Field(default=None, ge=0)
    highlights: str | None = Field(default=None, max_length=10_000)


class PractitionerCreate(_PractitionerFields):
    full_name: str = Field(min_length=1, max_length=200)
    registration_number: RegistrationNumber = None


class PractitionerUpdate(_PractitionerFields):
    """Name, registration number and login (``user_id``): Platform Administrator or DSM only."""

    not_null_fields: ClassVar[tuple[str, ...]] = ("full_name", "services_and_conditions")

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    registration_number: RegistrationNumber = None
    #: link the practitioner's own login (a user with platform_role 'practitioner'); null unlinks
    user_id: UUID | None = None

    #: fields only staff may change
    STAFF_ONLY: ClassVar[frozenset[str]] = frozenset({"full_name", "registration_number", "user_id"})


class PractitionerRead(ApiModel):
    id: UUID
    full_name: str
    specialty: str | None
    qualifications: str | None
    registration_number: str | None
    bio: str | None
    practice_start_year: int | None
    #: computed: this year - practice_start_year (never stored)
    years_of_experience: int | None
    services_and_conditions: list[str]
    approx_patients_treated: int | None
    highlights: str | None
    user_id: UUID | None
    created_at: datetime
    updated_at: datetime


class PractitionerLookup(ApiModel):
    """A practitioner found by registration number (minimal fields: they may work for another business)."""

    id: UUID
    full_name: str
    specialty: str | None


# ------------------------------------------------------------------------------ clinic link
class _LinkFields(PatchModel):
    """What THIS clinic says about the practitioner.

    Changed by the admin, the DSM or a Clinic Administrator (not the practitioner)."""

    designation: str | None = Field(default=None, max_length=120)
    consultation_hours: ConsultationHours | None = None
    weekly_off_days: WeeklyOffDays | None = None
    consultation_fee: Fee | None = None
    consultation_fee_currency: CurrencyCode | None = None
    consultation_time_zone: TimeZone | None = None
    schedule_notes: str | None = Field(default=None, max_length=2000)
    is_primary: bool | None = None


class ClinicPractitionerCreate(_LinkFields):
    """Link a practitioner to this clinic: an EXISTING one (``practitioner_id``, found with the
    registration-number lookup) or a NEW one (``practitioner``)."""

    practitioner_id: UUID | None = None
    practitioner: PractitionerCreate | None = None

    @model_validator(mode="after")
    def _one_of(self) -> Self:
        if (self.practitioner_id is None) == (self.practitioner is None):
            raise ValueError("give practitioner_id (existing) OR practitioner (new), not both")
        return self


class ClinicPractitionerUpdate(_LinkFields):
    not_null_fields: ClassVar[tuple[str, ...]] = (
        "consultation_hours",
        "weekly_off_days",
        "consultation_fee_currency",
        "consultation_time_zone",
        "is_primary",
        "is_active",
    )

    is_active: bool | None = None


class ClinicPractitionerRead(ApiModel):
    clinic_id: UUID
    practitioner_id: UUID
    practitioner: PractitionerRead
    designation: str | None
    consultation_hours: dict[str, list[dict[str, str]]]
    weekly_off_days: list[str]
    consultation_fee: Decimal | None
    consultation_fee_currency: str
    consultation_time_zone: str
    schedule_notes: str | None
    is_primary: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
