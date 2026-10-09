"""Tiny builders for test data, written with the OWNER session (``db`` fixture). Plain functions.

Each builder flushes, so ids exist; tests commit when they are done arranging.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import ClinicMemberRole, PlatformRole
from app.db.base import utcnow
from app.models import (
    ClientOrganization,
    Clinic,
    ClinicMember,
    ClinicPractitioner,
    PortfolioAllocation,
    Practitioner,
    User,
)


def make_user(
    db: Session, role: PlatformRole, email: str | None = None, *, linked: bool = True, active: bool = True
) -> User:
    """``linked=True``: has a Cognito sign-in (cognito_sub set); False: invited, never signed in."""
    user = User(
        email=email or f"{uuid.uuid4().hex[:10]}@example.test",
        platform_role=role,
        cognito_sub=str(uuid.uuid4()) if linked else None,
        last_login_at=utcnow() if linked else None,
        is_active=active,
        full_name="Test Person",
    )
    db.add(user)
    db.flush()
    return user


def make_admin(db: Session) -> User:
    return make_user(db, PlatformRole.PLATFORM_ADMINISTRATOR)


def make_organization(db: Session, name: str = "Shah Healthcare Pvt Ltd") -> ClientOrganization:
    org = ClientOrganization(name=name)
    db.add(org)
    db.flush()
    return org


def make_clinic(db: Session, org: ClientOrganization | None = None, **fields: Any) -> Clinic:
    org = org or make_organization(db)
    clinic = Clinic(client_organization_id=org.id, name=fields.pop("name", "Family Dental Clinic"), **fields)
    db.add(clinic)
    db.flush()
    return clinic


def make_dsm(db: Session, org: ClientOrganization, *, active: bool = True) -> User:
    """A Digital Success Manager with a portfolio allocation for ``org``."""
    user = make_user(db, PlatformRole.DIGITAL_SUCCESS_MANAGER)
    db.add(PortfolioAllocation(client_organization_id=org.id, user_id=user.id, is_active=active))
    db.flush()
    return user


def make_member(
    db: Session, clinic: Clinic, role: ClinicMemberRole = ClinicMemberRole.CLINIC_ADMINISTRATOR, **user: Any
) -> User:
    """A Clinic Administrator (default) or Clinic Team Member of ``clinic``."""
    person = make_user(db, PlatformRole.CLINIC_MEMBER, **user)
    db.add(ClinicMember(clinic_id=clinic.id, user_id=person.id, role=role))
    db.flush()
    return person


def make_practitioner(
    db: Session, clinic: Clinic | None = None, *, with_login: bool = False, **fields: Any
) -> Practitioner:
    """A practitioner record, linked to ``clinic`` if given; ``with_login`` adds his own login."""
    login = make_user(db, PlatformRole.PRACTITIONER) if with_login else None
    practitioner = Practitioner(
        full_name=fields.pop("full_name", "Dr. Pooja Shah"), user_id=login.id if login else None, **fields
    )
    db.add(practitioner)
    db.flush()
    if clinic is not None:
        link(db, clinic, practitioner)
    return practitioner


def link(db: Session, clinic: Clinic, practitioner: Practitioner, **fields: Any) -> ClinicPractitioner:
    row = ClinicPractitioner(clinic_id=clinic.id, practitioner_id=practitioner.id, **fields)
    db.add(row)
    db.flush()
    return row


def login_of(db: Session, practitioner: Practitioner) -> User:
    assert practitioner.user_id is not None
    user = db.get(User, practitioner.user_id)
    assert user is not None
    return user


@dataclass
class World:
    """Two businesses. In clinic A: one person per role. Clinic B belongs to someone else."""

    admin: User
    org_a: ClientOrganization
    clinic_a: Clinic
    dsm_a: User
    clinic_admin_a: User
    team_member_a: User
    practitioner_a: Practitioner
    practitioner_login_a: User
    org_b: ClientOrganization
    clinic_b: Clinic
    dsm_b: User
    clinic_admin_b: User

    def people_a(self) -> dict[str, User]:
        """Everyone who may see clinic A, by role name (for parametrized tests)."""
        return {
            "admin": self.admin,
            "dsm": self.dsm_a,
            "clinic_admin": self.clinic_admin_a,
            "team_member": self.team_member_a,
            "practitioner": self.practitioner_login_a,
        }


def build_world(db: Session) -> World:
    admin = make_admin(db)
    org_a = make_organization(db, "Shah Healthcare Pvt Ltd")
    clinic_a = make_clinic(db, org_a, name="Family Dental Clinic")
    practitioner_a = make_practitioner(db, clinic_a, with_login=True)
    org_b = make_organization(db, "SmileCare LLP")
    clinic_b = make_clinic(db, org_b, name="SmileCare Andheri")
    world = World(
        admin=admin,
        org_a=org_a,
        clinic_a=clinic_a,
        dsm_a=make_dsm(db, org_a),
        clinic_admin_a=make_member(db, clinic_a),
        team_member_a=make_member(db, clinic_a, ClinicMemberRole.CLINIC_TEAM_MEMBER),
        practitioner_a=practitioner_a,
        practitioner_login_a=login_of(db, practitioner_a),
        org_b=org_b,
        clinic_b=clinic_b,
        dsm_b=make_dsm(db, org_b),
        clinic_admin_b=make_member(db, clinic_b),
    )
    db.commit()
    return world
