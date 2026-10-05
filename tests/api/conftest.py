from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy.orm import Session

from app.core.enums import ClinicRole, PlatformRole
from app.models import Clinic, Practitioner, User
from tests.factories import add_member, assign, make_clinic, make_practitioner, make_user


@dataclass
class World:
    """Two clinics (tenants) and one person for every kind of access."""

    clinic_a: Clinic
    clinic_b: Clinic
    practitioner_a: Practitioner
    practitioner_b: Practitioner
    admin: User  # Platform Administrator
    dsm_a: User  # Digital Success Manager assigned to A
    unassigned_dsm: User  # Digital Success Manager with no clinics
    clinic_admin_a: User  # Clinic Administrator of A
    team_member_a: User  # reserved Clinic Team Member of A (no access yet)
    clinic_admin_b: User  # Clinic Administrator of B


@pytest.fixture
def world(db: Session) -> World:
    clinic_a = make_clinic(db, "Smile Dental A")
    clinic_b = make_clinic(db, "Bright Clinic B")
    w = World(
        clinic_a=clinic_a,
        clinic_b=clinic_b,
        practitioner_a=make_practitioner(db, clinic_a, "Dr. A", is_primary=True),
        practitioner_b=make_practitioner(db, clinic_b, "Dr. B", is_primary=True),
        admin=make_user(db, PlatformRole.PLATFORM_ADMINISTRATOR),
        dsm_a=make_user(db, PlatformRole.DIGITAL_SUCCESS_MANAGER),
        unassigned_dsm=make_user(db, PlatformRole.DIGITAL_SUCCESS_MANAGER),
        clinic_admin_a=make_user(db, PlatformRole.CLINIC_USER),
        team_member_a=make_user(db, PlatformRole.CLINIC_USER),
        clinic_admin_b=make_user(db, PlatformRole.CLINIC_USER),
    )
    assign(db, clinic_a, w.dsm_a)
    add_member(db, clinic_a, w.clinic_admin_a, ClinicRole.CLINIC_ADMINISTRATOR)
    add_member(db, clinic_a, w.team_member_a, ClinicRole.CLINIC_TEAM_MEMBER)
    add_member(db, clinic_b, w.clinic_admin_b, ClinicRole.CLINIC_ADMINISTRATOR)
    return w
