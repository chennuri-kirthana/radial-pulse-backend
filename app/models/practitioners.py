"""Practitioners: ONE shared record per person, and the per-clinic link (db/schema-v15.sql section 2)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    false,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TextArray, Timestamps, uuid_pk


class Practitioner(Timestamps, Base):
    """Shared across businesses. A clinic links an EXISTING one through
    ``rp_find_practitioner_by_registration()`` instead of creating a copy.

    Years of experience is never stored: current year - ``practice_start_year``.
    """

    __tablename__ = "practitioners"

    id: Mapped[uuid.UUID] = uuid_pk()
    full_name: Mapped[str] = mapped_column(String(200))
    specialty: Mapped[str | None] = mapped_column(String(120))
    qualifications: Mapped[str | None] = mapped_column(String(300))
    #: stored upper-case and trimmed ("ka-1234 " → "KA-1234")
    registration_number: Mapped[str | None] = mapped_column(String(64))
    bio: Mapped[str | None] = mapped_column(Text)
    practice_start_year: Mapped[int | None] = mapped_column(SmallInteger)
    services_and_conditions: Mapped[list[str]] = mapped_column(TextArray, server_default=text("'{}'"))
    approx_patients_treated: Mapped[int | None] = mapped_column(Integer)
    highlights: Mapped[str | None] = mapped_column(Text)
    #: the practitioner's own login (optional; platform_role must be 'practitioner')
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ClinicPractitioner(Timestamps, Base):
    """What one clinic says about a practitioner: schedule, holiday, fee, time zone, notes."""

    __tablename__ = "clinic_practitioners"

    clinic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clinics.id", ondelete="CASCADE"), primary_key=True
    )
    practitioner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practitioners.id", ondelete="CASCADE"), primary_key=True
    )
    designation: Mapped[str | None] = mapped_column(String(120))
    #: {"mon": [{"from": "10:00", "to": "14:00"}], ...}; missing day / [] = no consultation
    consultation_hours: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
    weekly_off_days: Mapped[list[str]] = mapped_column(TextArray, server_default=text("'{}'"))
    consultation_fee: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    consultation_fee_currency: Mapped[str] = mapped_column(CHAR(3), server_default=text("'INR'"))
    consultation_time_zone: Mapped[str] = mapped_column(String(64), server_default=text("'Asia/Kolkata'"))
    schedule_notes: Mapped[str | None] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=false())
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
