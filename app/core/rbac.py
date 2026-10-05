"""Role-based access control — the ONE place that maps roles to permissions.

Roles (docs/architecture/multi-tenancy.md):

    Platform Administrator   platform_role = platform_administrator   every clinic
    Digital Success Manager  platform_role = digital_success_manager  assigned clinics only
    Clinic Administrator     clinic membership role = clinic_administrator   own clinic(s) only
    Clinic Team Member       clinic membership role = clinic_team_member     own clinic(s), mostly view-only

There is no other way to reach a clinic. Frontends may use the permission list to
hide buttons; only this module (through `app.dependencies.tenancy`) decides access.
Machine actors (the worker) use `ServicePrincipal` — never a human role.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from app.core.enums import ClinicRole, PlatformRole


class Permission(StrEnum):
    # ---- platform-level (not tied to one clinic) ----
    CLINICS_CREATE = "clinics:create"
    USERS_READ = "users:read"
    USERS_MANAGE = "users:manage"
    ASSIGNMENTS_MANAGE = "assignments:manage"
    #: Change platform-wide settings (organization name, support email, timezone). Admin only.
    SETTINGS_MANAGE = "settings:manage"
    # ---- clinic-scoped ----
    CLINICS_READ = "clinics:read"
    CLINICS_WRITE = "clinics:write"
    #: Move a clinic through the stages and archive/restore it. Radial Pulse staff only.
    CLINICS_MANAGE = "clinics:manage"
    TEAM_MANAGE = "team:manage"
    PRACTITIONERS_READ = "practitioners:read"
    PRACTITIONERS_WRITE = "practitioners:write"
    PROFILE_READ = "profile:read"
    PROFILE_WRITE = "profile:write"
    PRESENCE_READ = "presence:read"
    PRESENCE_WRITE = "presence:write"
    ASSETS_READ = "assets:read"
    ASSETS_UPLOAD = "assets:upload"
    ASSESSMENTS_READ = "assessments:read"
    ASSESSMENTS_REQUEST = "assessments:request"
    #: Write engine results into an assessment. Granted to the worker's ServicePrincipal only.
    ASSESSMENTS_WRITE_RESULTS = "assessments:write_results"
    REPORTS_READ = "reports:read"
    REPORTS_WRITE = "reports:write"
    APPROVALS_SUBMIT = "approvals:submit"
    APPROVALS_DECIDE = "approvals:decide"
    APPROVALS_PUBLISH = "approvals:publish"
    WORK_ITEMS_READ = "work_items:read"
    WORK_ITEMS_WRITE = "work_items:write"
    SNAPSHOTS_READ = "snapshots:read"
    SNAPSHOTS_WRITE = "snapshots:write"
    AUDIT_LOG_READ = "audit_log:read"
    #: Client Collaboration: read / send messages in the clinic's chat.
    CHAT_READ = "chat:read"
    CHAT_WRITE = "chat:write"
    #: Connected accounts (Instagram, Google Business Profile, ...): see / connect or disconnect.
    CONNECTIONS_READ = "connections:read"
    CONNECTIONS_MANAGE = "connections:manage"
    #: Upload clinic media for review (hospital/clinic photos, doctor photos, voice samples).
    #: Clinic Administrator only (V1). Radial Pulse staff never upload this media.
    MEDIA_UPLOAD = "media:upload"
    #: Approve / reject / request a retake of clinic media. Radial Pulse staff only.
    MEDIA_REVIEW = "media:review"


P = Permission

GLOBAL_PERMISSIONS: frozenset[Permission] = frozenset(
    {P.CLINICS_CREATE, P.USERS_READ, P.USERS_MANAGE, P.ASSIGNMENTS_MANAGE, P.SETTINGS_MANAGE}
)
CLINIC_PERMISSIONS: frozenset[Permission] = frozenset(set(Permission) - GLOBAL_PERMISSIONS)
#: Permissions no human role ever receives (machine-only).
SERVICE_ONLY_PERMISSIONS: frozenset[Permission] = frozenset({P.ASSESSMENTS_WRITE_RESULTS})
#: Permissions only clinic people receive — never Radial Pulse staff (they review, not upload).
CLINIC_USER_ONLY_PERMISSIONS: frozenset[Permission] = frozenset({P.MEDIA_UPLOAD})

# ---------------------------------------------------------------- role tables
# PROPOSED defaults — see "Decisions requiring approval" in docs/architecture/decisions.md.

PLATFORM_ROLE_GLOBAL_PERMISSIONS: Mapping[PlatformRole, frozenset[Permission]] = {
    PlatformRole.PLATFORM_ADMINISTRATOR: GLOBAL_PERMISSIONS,
    # DSMs onboard clinics (outbound sales model) but cannot manage users or assignments.
    PlatformRole.DIGITAL_SUCCESS_MANAGER: frozenset({P.CLINICS_CREATE}),
    PlatformRole.CLINIC_USER: frozenset(),
}

#: What a Platform Administrator can do inside ANY clinic.
PLATFORM_ADMINISTRATOR_CLINIC_PERMISSIONS: frozenset[Permission] = (
    CLINIC_PERMISSIONS - SERVICE_ONLY_PERMISSIONS - CLINIC_USER_ONLY_PERMISSIONS
)

#: What a Digital Success Manager can do inside a clinic they are ASSIGNED to.
DIGITAL_SUCCESS_MANAGER_CLINIC_PERMISSIONS: frozenset[Permission] = frozenset(
    {
        P.CLINICS_READ, P.CLINICS_WRITE, P.CLINICS_MANAGE, P.TEAM_MANAGE,
        P.PRACTITIONERS_READ, P.PRACTITIONERS_WRITE,
        P.PROFILE_READ, P.PROFILE_WRITE,
        P.PRESENCE_READ, P.PRESENCE_WRITE,
        P.ASSETS_READ, P.ASSETS_UPLOAD,
        P.ASSESSMENTS_READ, P.ASSESSMENTS_REQUEST,
        P.REPORTS_READ, P.REPORTS_WRITE,
        P.APPROVALS_SUBMIT, P.APPROVALS_DECIDE, P.APPROVALS_PUBLISH,
        P.WORK_ITEMS_READ, P.WORK_ITEMS_WRITE,
        P.SNAPSHOTS_READ, P.SNAPSHOTS_WRITE,
        P.AUDIT_LOG_READ,
        P.CHAT_READ, P.CHAT_WRITE,
        P.CONNECTIONS_READ, P.CONNECTIONS_MANAGE,
        P.MEDIA_REVIEW,
    }
)  # fmt: skip

CLINIC_ROLE_PERMISSIONS: Mapping[ClinicRole, frozenset[Permission]] = {
    ClinicRole.CLINIC_ADMINISTRATOR: frozenset(
        {
            P.CLINICS_READ,
            P.CLINICS_WRITE,
            #: May add other Clinic Administrators and Clinic Team Members to their own clinic
            #: (decision D14). Only GRANTABLE_CLINIC_ROLES can be granted: never a Radial Pulse
            #: role (Platform Administrator, DSM).
            P.TEAM_MANAGE,
            P.PRACTITIONERS_READ,
            P.PRACTITIONERS_WRITE,
            P.PROFILE_READ,
            P.PROFILE_WRITE,
            P.PRESENCE_READ,
            P.PRESENCE_WRITE,
            P.ASSETS_READ,
            P.ASSETS_UPLOAD,
            P.ASSESSMENTS_READ,  # published assessments only (enforced in the service)
            P.REPORTS_READ,  # published reports only
            #: No approvals:* permission: every review decision (assessments, report outputs,
            #: clinic media) is Radial Pulse staff work (decision D24, 5 Oct 2026).
            #: The ONLY clinic role that uploads clinic media for review (V1).
            P.MEDIA_UPLOAD,
            P.WORK_ITEMS_READ,
            P.SNAPSHOTS_READ,
            P.AUDIT_LOG_READ,
            P.CHAT_READ,
            P.CHAT_WRITE,
            #: "Connect Your Accounts" on the mobile app.
            P.CONNECTIONS_READ,
            P.CONNECTIONS_MANAGE,
        }
    ),
    #: Clinic staff (front desk, manager…). Mostly VIEW-ONLY inside their own clinic, plus
    #: uploading files. No editing clinic details, no adding people, no approvals, no
    #: activity log. Reports: published only (enforced in the services, like Clinic Administrators).
    #: No ``media:upload``: the clinic media workflow is the Clinic Administrator's in V1.
    ClinicRole.CLINIC_TEAM_MEMBER: frozenset(
        {
            P.CLINICS_READ,
            P.PRACTITIONERS_READ,
            P.PROFILE_READ,
            P.PRESENCE_READ,
            P.ASSETS_READ,
            P.ASSETS_UPLOAD,
            P.ASSESSMENTS_READ,  # published only
            P.REPORTS_READ,  # published only
            P.WORK_ITEMS_READ,
            P.SNAPSHOTS_READ,
            #: Reads the clinic chat; only Clinic Administrators, DSMs and Platform
            #: Administrators send (decision D18).
            P.CHAT_READ,
            P.CONNECTIONS_READ,
        }
    ),
}

#: Clinic roles that may be granted through the API (by Admin, the clinic's DSM, or a Clinic
#: Administrator of that clinic — anyone with team:manage there).
GRANTABLE_CLINIC_ROLES: frozenset[ClinicRole] = frozenset(
    {ClinicRole.CLINIC_ADMINISTRATOR, ClinicRole.CLINIC_TEAM_MEMBER}
)


@dataclass(frozen=True)
class Principal:
    """An authenticated HUMAN, with everything needed to make access decisions.

    Built once per request by `app.dependencies.auth` from the verified token and the DB.
    """

    user_id: UUID
    email: str
    platform_role: PlatformRole
    #: clinic_id -> role, from active ClinicMembership rows (clinic users only)
    clinic_roles: Mapping[UUID, ClinicRole] = field(default_factory=dict)
    #: clinic ids from active ClinicAssignment rows (Digital Success Managers only)
    assigned_clinic_ids: frozenset[UUID] = field(default_factory=frozenset)

    @property
    def actor_type(self) -> str:
        return "user"

    @property
    def is_platform_administrator(self) -> bool:
        return self.platform_role is PlatformRole.PLATFORM_ADMINISTRATOR

    @property
    def is_internal(self) -> bool:
        """Radial Pulse staff (Platform Administrator or Digital Success Manager)."""
        return self.platform_role in (
            PlatformRole.PLATFORM_ADMINISTRATOR,
            PlatformRole.DIGITAL_SUCCESS_MANAGER,
        )

    def global_permissions(self) -> frozenset[Permission]:
        return PLATFORM_ROLE_GLOBAL_PERMISSIONS.get(self.platform_role, frozenset())

    def clinic_permissions(self, clinic_id: UUID) -> frozenset[Permission]:
        """Permissions inside `clinic_id` (empty set = no access at all)."""
        if self.is_platform_administrator:
            return PLATFORM_ADMINISTRATOR_CLINIC_PERMISSIONS
        # Defense in depth: an assignment only counts for DSMs, a membership only for clinic
        # users — even if bad data exists.
        if self.platform_role is PlatformRole.DIGITAL_SUCCESS_MANAGER:
            return (
                DIGITAL_SUCCESS_MANAGER_CLINIC_PERMISSIONS
                if clinic_id in self.assigned_clinic_ids
                else frozenset()
            )
        if self.platform_role is PlatformRole.CLINIC_USER:
            role = self.clinic_roles.get(clinic_id)
            return CLINIC_ROLE_PERMISSIONS[role] if role is not None else frozenset()
        return frozenset()

    def can_access_clinic(self, clinic_id: UUID) -> bool:
        return bool(self.clinic_permissions(clinic_id))

    def has(self, permission: Permission, clinic_id: UUID | None = None) -> bool:
        if permission in GLOBAL_PERMISSIONS:
            return permission in self.global_permissions()
        if clinic_id is None:
            raise ValueError(f"{permission} is clinic-scoped; pass clinic_id")
        return permission in self.clinic_permissions(clinic_id)

    def accessible_clinic_ids(self) -> frozenset[UUID] | None:
        """Clinic ids this principal may see. `None` means ALL (Platform Administrator)."""
        if self.is_platform_administrator:
            return None
        if self.platform_role is PlatformRole.DIGITAL_SUCCESS_MANAGER:
            return self.assigned_clinic_ids
        if self.platform_role is PlatformRole.CLINIC_USER:
            return frozenset(cid for cid, role in self.clinic_roles.items() if CLINIC_ROLE_PERMISSIONS[role])
        return frozenset()


#: What the background worker may do inside the ONE clinic its current job belongs to.
WORKER_PERMISSIONS: frozenset[Permission] = frozenset(
    {P.CLINICS_READ, P.PROFILE_READ, P.PRESENCE_READ, P.PRESENCE_WRITE, P.ASSESSMENTS_WRITE_RESULTS,
     P.SNAPSHOTS_READ, P.SNAPSHOTS_WRITE}
)  # fmt: skip


@dataclass(frozen=True)
class ServicePrincipal:
    """A MACHINE actor (e.g. the assessment worker). Never impersonates a human.

    Authenticated by AWS (its own ECS task role + its own DB login), scoped to one clinic
    per job, with a fixed small permission set.
    """

    name: str
    clinic_id: UUID
    permissions: frozenset[Permission] = WORKER_PERMISSIONS
    user_id: None = None

    @property
    def actor_type(self) -> str:
        return "service"

    @property
    def is_internal(self) -> bool:
        return False


Actor = Principal | ServicePrincipal


@dataclass(frozen=True)
class ClinicContext:
    """An actor acting inside ONE clinic, after the access check passed.

    Produced by `app.dependencies.tenancy.clinic_access` (humans) or by the worker (services).
    Services that receive a ClinicContext can trust `clinic_id` and must scope queries to it.
    """

    principal: Actor
    clinic_id: UUID
    permissions: frozenset[Permission]

    def can(self, permission: Permission) -> bool:
        return permission in self.permissions

    @property
    def user_id(self) -> UUID | None:
        return self.principal.user_id

    @classmethod
    def for_service(cls, service: ServicePrincipal) -> ClinicContext:
        return cls(principal=service, clinic_id=service.clinic_id, permissions=service.permissions)
