"""Tiny builders for test data. Plain functions — no factory library needed yet."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.enums import ClinicRole, PlatformRole
from app.models import (
    Clinic,
    ClinicAssignment,
    ClinicMembership,
    ClinicPractitioner,
    ClinicProfile,
    Organization,
    Practitioner,
    User,
)


def make_user(db: Session, role: PlatformRole, email: str | None = None, linked: bool = True) -> User:
    user = User(
        email=email or f"{uuid.uuid4().hex[:10]}@example.test",
        platform_role=role,
        cognito_sub=str(uuid.uuid4()) if linked else None,
    )
    db.add(user)
    db.commit()
    return user


def make_clinic(db: Session, name: str, organization: Organization | None = None) -> Clinic:
    org = organization or Organization(name=f"{name} Org")
    if organization is None:
        db.add(org)
        db.flush()
    clinic = Clinic(organization_id=org.id, name=name, city="Hyderabad", state="Telangana")
    db.add(clinic)
    db.flush()
    db.add(ClinicProfile(clinic_id=clinic.id))
    db.commit()
    return clinic


def add_member(db: Session, clinic: Clinic, user: User, role: ClinicRole) -> ClinicMembership:
    m = ClinicMembership(clinic_id=clinic.id, user_id=user.id, role=role)
    db.add(m)
    db.commit()
    return m


def assign(db: Session, clinic: Clinic, user: User) -> ClinicAssignment:
    """Assign a Digital Success Manager to a clinic."""
    a = ClinicAssignment(clinic_id=clinic.id, user_id=user.id)
    db.add(a)
    db.commit()
    return a


def make_practitioner(
    db: Session, clinic: Clinic, name: str = "Dr. Test", is_primary: bool = False
) -> Practitioner:
    """A practitioner (the person, in the clinic's business) working at ``clinic``."""
    p = Practitioner(organization_id=clinic.organization_id, full_name=name, specialty="Dentistry")
    db.add(p)
    db.flush()
    db.add(ClinicPractitioner(clinic_id=clinic.id, practitioner_id=p.id, is_primary=is_primary))
    db.commit()
    return p
