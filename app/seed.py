"""Demo data that looks like the screen designs — for local/DEV testing and for Person 2's screens.

    uv run python -m app.cli seed-demo            (or: make seed-demo)

* Refuses to run in PROD.
* Safe to run twice: if the demo organization exists, nothing is added.
* Demo people use @demo.example.com addresses: they cannot sign in and no email is ever sent.
  To sign in yourself, create your own admin with `create-platform-admin`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ClinicRole, ClinicStage, PlatformRole, WorkArea, WorkItemStatus
from app.db.base import utcnow
from app.db.tenant import set_tenant_scope
from app.models import (
    Clinic,
    ClinicAssignment,
    ClinicMembership,
    ClinicPractitioner,
    ClinicProfile,
    ClinicStageHistory,
    Organization,
    Practitioner,
    User,
    WorkItem,
)
from app.services import audit

DEMO_ORG = "Demo — Radial Pulse sample clinics"
DOMAIN = "demo.example.com"

STAGE_PATH = list(ClinicStage)


@dataclass(frozen=True)
class DemoClinic:
    name: str
    practitioner: str
    specialty: str
    city: str
    website: str
    stage: ClinicStage
    dsm: str | None  # key into DSMS
    open_work: tuple[tuple[WorkArea, str], ...] = ()


DSMS = {
    "priya": "Priya Shah",
    "amit": "Amit Kumar",
    "sneha": "Sneha Iyer",
}

CLINICS = [
    DemoClinic(
        "Smile Dental Care",
        "Dr. Rahul Mehta",
        "General Dentistry, Implants",
        "Kakinada",
        "https://smiledentalcare.example.com",
        ClinicStage.CLIENT_DISCUSSION,
        "priya",
        (
            (WorkArea.SEARCH_READINESS, "Add a detailed services page"),
            (WorkArea.SEARCH_READINESS, "Add FAQs for AI answers"),
            (WorkArea.GOOGLE_BUSINESS_PROFILE, "Improve GBP description"),
            (WorkArea.SOCIAL_PRESENCE, "Post twice a week on Instagram"),
        ),
    ),
    DemoClinic(
        "Bright Smile Clinic",
        "Dr. Neha Gupta",
        "Orthodontics",
        "Hyderabad",
        "https://brightsmile.example.com",
        ClinicStage.PROSPECTIVE_CLIENT,
        "amit",
    ),
    DemoClinic(
        "CarePlus Dental",
        "Dr. Suresh Reddy",
        "Dental Surgery",
        "Vijayawada",
        "https://careplusdental.example.com",
        ClinicStage.ASSESSMENT_COMPLETED,
        "sneha",
        ((WorkArea.CLINIC_PROFILE, "Confirm opening hours"),),
    ),
    DemoClinic(
        "Elite Dental Clinic",
        "Dr. Kavya Sharma",
        "Cosmetic Dentistry",
        "Visakhapatnam",
        "https://elitedental.example.com",
        ClinicStage.ACTIVE_CLIENT,
        "priya",
        ((WorkArea.WEBSITE, "Add descriptive alt text to images"),),
    ),
    DemoClinic(
        "Happy Teeth",
        "Dr. Anil Kumar",
        "Pediatric Dentistry",
        "Guntur",
        "https://happyteeth.example.com",
        ClinicStage.PROFILE_ENRICHED,
        "priya",
    ),
    DemoClinic(
        "Dental Health Hub",
        "Dr. Meena Nair",
        "General Dentistry",
        "Rajahmundry",
        "https://dentalhealthhub.example.com",
        ClinicStage.PROSPECTIVE_CLIENT,
        None,
    ),
]


def _email(name: str) -> str:
    return f"{name.lower().replace('dr. ', '').replace(' ', '.')}@{DOMAIN}"


def seed_demo(session: Session) -> str:
    set_tenant_scope(session, None)  # operator command: may write every clinic
    if session.scalar(select(Organization).where(Organization.name == DEMO_ORG)) is not None:
        return "Demo data already exists — nothing added."

    admin = User(
        email=f"rohan.agarwal@{DOMAIN}",
        full_name="Rohan Agarwal",
        platform_role=PlatformRole.PLATFORM_ADMINISTRATOR,
    )
    dsms = {
        key: User(email=_email(name), full_name=name, platform_role=PlatformRole.DIGITAL_SUCCESS_MANAGER)
        for key, name in DSMS.items()
    }
    session.add_all([admin, *dsms.values()])
    org = Organization(name=DEMO_ORG)
    session.add(org)
    session.flush()

    for spec in CLINICS:
        clinic = Clinic(
            organization_id=org.id,
            name=spec.name,
            specialty=spec.specialty,
            city=spec.city,
            state="Andhra Pradesh" if spec.city != "Hyderabad" else "Telangana",
            country="IN",
            website_url=spec.website,
            stage=spec.stage,
            stage_changed_at=utcnow(),
            created_by_user_id=admin.id,
        )
        session.add(clinic)
        session.flush()
        session.add(ClinicProfile(clinic_id=clinic.id))
        doctor_record = Practitioner(organization_id=org.id, full_name=spec.practitioner)
        session.add(doctor_record)
        session.flush()
        session.add(
            ClinicPractitioner(clinic_id=clinic.id, practitioner_id=doctor_record.id, is_primary=True)
        )
        # Stage diary: every step up to the current one.
        previous: ClinicStage | None = None
        for stage in STAGE_PATH[: STAGE_PATH.index(spec.stage) + 1]:
            session.add(
                ClinicStageHistory(
                    clinic_id=clinic.id, from_stage=previous, to_stage=stage, changed_by_user_id=admin.id
                )
            )
            previous = stage
        if spec.dsm:
            session.add(
                ClinicAssignment(clinic_id=clinic.id, user_id=dsms[spec.dsm].id, assigned_by_user_id=admin.id)
            )
        if spec.stage is ClinicStage.ACTIVE_CLIENT:
            doctor = User(
                email=_email(spec.practitioner),
                full_name=spec.practitioner,
                platform_role=PlatformRole.CLINIC_USER,
            )
            session.add(doctor)
            session.flush()
            session.add(
                ClinicMembership(clinic_id=clinic.id, user_id=doctor.id, role=ClinicRole.CLINIC_ADMINISTRATOR)
            )
        for area, title in spec.open_work:
            session.add(
                WorkItem(
                    clinic_id=clinic.id,
                    kind="improvement",
                    title=title,
                    area=area,
                    status=WorkItemStatus.TODO,
                    source_team="central",
                )
            )
        audit.record(
            session,
            actor=None,
            action="clinic.create",
            resource_type="clinic",
            resource_id=clinic.id,
            clinic_id=clinic.id,
            details={"via": "seed-demo"},
        )
    session.commit()
    return f"Added demo data: 1 admin, {len(DSMS)} DSMs, {len(CLINICS)} clinics."
