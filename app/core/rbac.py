"""Roles → permissions: the API's own access check (docs/02-access-rules.md).

The database enforces the same rules (row-level security). The API checks them FIRST so the
caller gets a clear answer: a clinic they can't see → 404, an action they may not do → 403.

Who is who (built once per request in app/services/identity.py):

    Platform Administrator     users.platform_role = platform_administrator   every clinic
    Digital Success Manager    active portfolio_allocations row               clinics of that organization
    Clinic Administrator       active clinic_members row, role clinic_administrator
    Clinic Team Member         active clinic_members row, role clinic_team_member (read only)
    Practitioner               practitioners.user_id = the login, ACTIVELY linked to the clinic

"Own only" rules (a practitioner sees only HIS voice samples and work items, uploads only his
own photos) are applied in the services, and again by the database.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from app.core.enums import ClinicMemberRole, PlatformRole


class Permission(StrEnum):
    # ---- platform-level (not tied to one clinic) ----
    #: Create Client Organizations and clinics (new leads). Platform Administrator only.
    CLIENT_ORGANIZATIONS_MANAGE = "client_organizations:manage"
    #: Allocate a DSM to a Client Organization. Platform Administrator only.
    PORTFOLIO_ALLOCATIONS_MANAGE = "portfolio_allocations:manage"
    #: List every user; invite any role; change role, active flag, email.
    USERS_MANAGE = "users:manage"
    PLATFORM_SETTINGS_MANAGE = "platform_settings:manage"
    # ---- clinic-scoped ----
    CLINICS_READ = "clinics:read"
    CLINICS_WRITE = "clinics:write"
    #: Move the stage, archive / restore, change the Client Organization, see stage history.
    CLINICS_MANAGE = "clinics:manage"
    #: Invite a clinic_member or practitioner login for this clinic.
    USERS_INVITE = "users:invite"
    CLINIC_MEMBERS_READ = "clinic_members:read"
    CLINIC_MEMBERS_MANAGE = "clinic_members:manage"
    CLINIC_PRACTITIONERS_READ = "clinic_practitioners:read"
    #: Link practitioners and change THIS clinic's details for them (schedule, holiday, fee, ...).
    CLINIC_PRACTITIONERS_MANAGE = "clinic_practitioners:manage"
    #: Edit the SHARED practitioner record (bio, qualifications, ...) and name / registration / login.
    #: (The practitioner may edit his own record too: checked in the service.)
    PRACTITIONERS_EDIT = "practitioners:edit"
    CLINIC_PROFILE_READ = "clinic_profile:read"
    CLINIC_PROFILE_WRITE = "clinic_profile:write"
    CLINIC_ONLINE_PROFILES_READ = "clinic_online_profiles:read"
    CLINIC_ONLINE_PROFILES_ADD = "clinic_online_profiles:add"
    #: Confirm, reject or remove an online profile.
    CLINIC_ONLINE_PROFILES_REVIEW = "clinic_online_profiles:review"
    #: Staff see every report; everyone else sees only published ones (service + database).
    DIGITAL_PRESENCE_ASSESSMENTS_READ = "digital_presence_assessments:read"
    DIGITAL_PRESENCE_ASSESSMENTS_MANAGE = "digital_presence_assessments:manage"
    IMPROVEMENT_WORK_ITEMS_READ = "improvement_work_items:read"
    IMPROVEMENT_WORK_ITEMS_MANAGE = "improvement_work_items:manage"
    PHOTOS_READ = "photos:read"
    #: Clinic Administrator; the practitioner for his own photos.
    PHOTOS_UPLOAD = "photos:upload"
    #: Approve / reject / sort. Staff only.
    PHOTOS_REVIEW = "photos:review"
    VOICE_SAMPLES_READ = "voice_samples:read"
    VOICE_SAMPLES_UPLOAD = "voice_samples:upload"
    AUDIT_EVENTS_READ = "audit_events:read"
    COLLABORATION_MESSAGES_READ = "collaboration_messages:read"
    COLLABORATION_MESSAGES_SEND = "collaboration_messages:send"
    CONNECTED_ACCOUNTS_READ = "connected_accounts:read"
    CONNECTED_ACCOUNTS_MANAGE = "connected_accounts:manage"


P = Permission

GLOBAL_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        P.CLIENT_ORGANIZATIONS_MANAGE,
        P.PORTFOLIO_ALLOCATIONS_MANAGE,
        P.USERS_MANAGE,
        P.PLATFORM_SETTINGS_MANAGE,
    }
)
CLINIC_PERMISSIONS: frozenset[Permission] = frozenset(set(Permission) - GLOBAL_PERMISSIONS)

#: Only clinic people upload clinic media; Radial Pulse staff review it.
_UPLOADS = frozenset({P.PHOTOS_UPLOAD, P.VOICE_SAMPLES_UPLOAD})

#: Staff (Platform Administrator anywhere; a DSM in the clinics of his Client Organizations).
STAFF_CLINIC_PERMISSIONS: frozenset[Permission] = CLINIC_PERMISSIONS - _UPLOADS

CLINIC_MEMBER_PERMISSIONS: Mapping[ClinicMemberRole, frozenset[Permission]] = {
    ClinicMemberRole.CLINIC_ADMINISTRATOR: frozenset(
        {
            P.CLINICS_READ, P.CLINICS_WRITE, P.USERS_INVITE,
            P.CLINIC_MEMBERS_READ, P.CLINIC_MEMBERS_MANAGE,
            P.CLINIC_PRACTITIONERS_READ, P.CLINIC_PRACTITIONERS_MANAGE,
            P.CLINIC_PROFILE_READ, P.CLINIC_PROFILE_WRITE,
            P.CLINIC_ONLINE_PROFILES_READ, P.CLINIC_ONLINE_PROFILES_ADD,
            P.DIGITAL_PRESENCE_ASSESSMENTS_READ,
            P.IMPROVEMENT_WORK_ITEMS_READ,
            P.PHOTOS_READ, P.PHOTOS_UPLOAD,
            P.VOICE_SAMPLES_READ, P.VOICE_SAMPLES_UPLOAD,
            P.AUDIT_EVENTS_READ,
            P.COLLABORATION_MESSAGES_READ, P.COLLABORATION_MESSAGES_SEND,
            P.CONNECTED_ACCOUNTS_READ, P.CONNECTED_ACCOUNTS_MANAGE,
        }
    ),
    #: Read only. No voice samples, no audit log.
    ClinicMemberRole.CLINIC_TEAM_MEMBER: frozenset(
        {
            P.CLINICS_READ, P.CLINIC_MEMBERS_READ, P.CLINIC_PRACTITIONERS_READ, P.CLINIC_PROFILE_READ,
            P.CLINIC_ONLINE_PROFILES_READ, P.DIGITAL_PRESENCE_ASSESSMENTS_READ,
            P.IMPROVEMENT_WORK_ITEMS_READ, P.PHOTOS_READ, P.COLLABORATION_MESSAGES_READ,
            P.CONNECTED_ACCOUNTS_READ,
        }
    ),
}  # fmt: skip

#: A practitioner in a clinic he is ACTIVELY linked to. "Own only" limits are in the services.
#: No team list, no connected accounts, no audit log.
PRACTITIONER_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        P.CLINICS_READ, P.CLINIC_PRACTITIONERS_READ, P.CLINIC_PROFILE_READ, P.CLINIC_ONLINE_PROFILES_READ,
        P.DIGITAL_PRESENCE_ASSESSMENTS_READ, P.IMPROVEMENT_WORK_ITEMS_READ,
        P.PHOTOS_READ, P.PHOTOS_UPLOAD, P.VOICE_SAMPLES_READ, P.VOICE_SAMPLES_UPLOAD,
        P.COLLABORATION_MESSAGES_READ, P.COLLABORATION_MESSAGES_SEND,
    }
)  # fmt: skip

#: Logins a DSM or Clinic Administrator may invite (an admin may invite any role).
CLINIC_INVITABLE_ROLES: frozenset[PlatformRole] = frozenset(
    {PlatformRole.CLINIC_MEMBER, PlatformRole.PRACTITIONER}
)


@dataclass(frozen=True)
class Principal:
    """A signed-in PERSON, with everything needed to decide access. Built once per request."""

    user_id: UUID
    email: str
    full_name: str | None
    platform_role: PlatformRole
    #: clinic_id → role, from active clinic_members rows (Clinic Administrator / Team Member)
    clinic_roles: Mapping[UUID, ClinicMemberRole] = field(default_factory=dict)
    #: Client Organizations allocated to this DSM, and their clinics
    dsm_client_organization_ids: frozenset[UUID] = field(default_factory=frozenset)
    dsm_clinic_ids: frozenset[UUID] = field(default_factory=frozenset)
    #: The practitioner record of this login, and the clinics it is actively linked to
    practitioner_id: UUID | None = None
    practitioner_clinic_ids: frozenset[UUID] = field(default_factory=frozenset)

    @property
    def is_platform_administrator(self) -> bool:
        return self.platform_role is PlatformRole.PLATFORM_ADMINISTRATOR

    @property
    def is_digital_success_manager(self) -> bool:
        return self.platform_role is PlatformRole.DIGITAL_SUCCESS_MANAGER

    @property
    def is_practitioner(self) -> bool:
        return self.platform_role is PlatformRole.PRACTITIONER

    def is_staff_for(self, clinic_id: UUID) -> bool:
        """Platform Administrator, or the DSM of this clinic's Client Organization."""
        return self.is_platform_administrator or (
            self.is_digital_success_manager and clinic_id in self.dsm_clinic_ids
        )

    def global_permissions(self) -> frozenset[Permission]:
        return GLOBAL_PERMISSIONS if self.is_platform_administrator else frozenset()

    def clinic_permissions(self, clinic_id: UUID) -> frozenset[Permission]:
        """Permissions inside ``clinic_id``. Empty = may not see the clinic at all (→ 404).

        A role only counts with its own kind of link, even if bad data exists.
        """
        if self.is_staff_for(clinic_id):
            return STAFF_CLINIC_PERMISSIONS
        if self.platform_role is PlatformRole.CLINIC_MEMBER:
            role = self.clinic_roles.get(clinic_id)
            return CLINIC_MEMBER_PERMISSIONS[role] if role is not None else frozenset()
        if self.is_practitioner and clinic_id in self.practitioner_clinic_ids:
            return PRACTITIONER_PERMISSIONS
        return frozenset()

    def has(self, permission: Permission, clinic_id: UUID | None = None) -> bool:
        if permission in GLOBAL_PERMISSIONS:
            return permission in self.global_permissions()
        if clinic_id is None:
            raise ValueError(f"{permission} is clinic-scoped; pass clinic_id")
        return permission in self.clinic_permissions(clinic_id)

    def visible_clinic_ids(self) -> frozenset[UUID] | None:
        """Clinics this person may see. ``None`` = all (Platform Administrator)."""
        if self.is_platform_administrator:
            return None
        if self.is_digital_success_manager:
            return self.dsm_clinic_ids
        if self.platform_role is PlatformRole.CLINIC_MEMBER:
            return frozenset(self.clinic_roles)
        if self.is_practitioner:
            return self.practitioner_clinic_ids
        return frozenset()


@dataclass(frozen=True)
class ClinicContext:
    """A person acting inside ONE clinic, after the access check passed (app/dependencies/tenancy.py)."""

    principal: Principal
    clinic_id: UUID
    permissions: frozenset[Permission]

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    @property
    def user_id(self) -> UUID:
        return self.principal.user_id

    @property
    def is_staff(self) -> bool:
        return self.principal.is_staff_for(self.clinic_id)

    @property
    def member_role(self) -> ClinicMemberRole | None:
        return self.principal.clinic_roles.get(self.clinic_id)

    @property
    def is_clinic_administrator(self) -> bool:
        return self.member_role is ClinicMemberRole.CLINIC_ADMINISTRATOR

    @property
    def acting_practitioner_id(self) -> UUID | None:
        """The practitioner record of the caller, when they act here AS a practitioner."""
        if self.principal.is_practitioner and self.clinic_id in self.principal.practitioner_clinic_ids:
            return self.principal.practitioner_id
        return None


class ServiceScope(StrEnum):
    """Scopes another team's backend may hold for /api/v1/internal (read only).

    Which service (IAM role) holds which scope is set in ``INTERNAL_SERVICE_ROLES``.
    """

    #: clinic, its Client Organization, clinic profile, practitioners, online profiles, approved photos
    CLINICS_READ = "clinics.read"
    #: connected accounts (never secret_ref) and their locations / pages
    CONNECTED_ACCOUNTS_READ = "connected_accounts.read"
