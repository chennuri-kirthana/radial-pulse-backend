"""Clinics and what hangs directly off them (db/schema-v15.sql sections 2, 3 and 4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, SmallInteger, String, Text, func, text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ClinicMemberRole, ClinicStage, OnlineProfilePlatform, OnlineProfileVerification
from app.db.base import Base, Timestamps, str_enum, uuid_pk


class Clinic(Timestamps, Base):
    """One branch of a Client Organization: the tenant.

    Never write ``stage`` history yourself: ``SET LOCAL rp.stage_note`` then UPDATE ``stage``;
    a trigger writes ``clinic_stage_changes`` (CLAUDE.md rule 7).
    """

    __tablename__ = "clinics"

    id: Mapped[uuid.UUID] = uuid_pk()
    client_organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("client_organizations.id", ondelete="RESTRICT")
    )
    name: Mapped[str] = mapped_column(String(200))
    specialty: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    website_url: Mapped[str | None] = mapped_column(String(500))
    address_line: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str] = mapped_column(String(2), server_default=text("'IN'"))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    established_year: Mapped[int | None] = mapped_column(SmallInteger)
    stage: Mapped[ClinicStage] = mapped_column(
        str_enum(ClinicStage), server_default=text("'prospective_client'")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())
    archived_reason: Mapped[str | None] = mapped_column(Text)


class ClinicStageChange(Base):
    """Stage history. Written ONLY by the trigger rp_record_stage_change (the app can't insert)."""

    __tablename__ = "clinic_stage_changes"

    id: Mapped[uuid.UUID] = uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    from_stage: Mapped[ClinicStage | None] = mapped_column(str_enum(ClinicStage))
    to_stage: Mapped[ClinicStage] = mapped_column(str_enum(ClinicStage))
    note: Mapped[str | None] = mapped_column(Text)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ClinicProfile(Timestamps, Base):
    """1 : 1 extra details of a clinic. ``version`` stops two people overwriting each other."""

    __tablename__ = "clinic_profiles"

    clinic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clinics.id", ondelete="CASCADE"), primary_key=True
    )
    brand: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
    audience: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
    services: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
    schedule: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class ClinicMember(Timestamps, Base):
    """A Clinic Administrator or Clinic Team Member of one clinic (login role ``clinic_member``)."""

    __tablename__ = "clinic_members"

    clinic_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clinics.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    role: Mapped[ClinicMemberRole] = mapped_column(str_enum(ClinicMemberRole))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true())


class ClinicOnlineProfile(Timestamps, Base):
    """Where the clinic is online (found by the Digital Presence Intelligence Agent or typed in)."""

    __tablename__ = "clinic_online_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    clinic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clinics.id", ondelete="CASCADE"))
    platform: Mapped[OnlineProfilePlatform] = mapped_column(str_enum(OnlineProfilePlatform, 40))
    #: cleaned by the trigger rp_clean_url
    url: Mapped[str] = mapped_column(String(1000))
    external_id: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(255))
    verification: Mapped[OnlineProfileVerification] = mapped_column(
        str_enum(OnlineProfileVerification), server_default=text("'unverified'")
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    #: which agent (or person) found it
    discovered_by: Mapped[str] = mapped_column(String(128))
