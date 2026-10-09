from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.core.enums import ClinicMemberRole, PlatformRole
from app.core.rbac import Permission
from app.schemas.common import ApiModel


class ClinicAccess(ApiModel):
    clinic_id: UUID
    #: Clinic Administrator / Clinic Team Member (clinic_member logins only).
    clinic_member_role: ClinicMemberRole | None = None
    #: The caller is the DSM of this clinic's Client Organization.
    is_digital_success_manager: bool = False
    #: The caller is a practitioner actively linked to this clinic.
    is_practitioner: bool = False
    permissions: list[Permission]


class MeResponse(ApiModel):
    """Who the caller is and what they may do. Frontends use this to shape the UI only."""

    id: UUID
    email: str
    full_name: str | None
    phone: str | None = None
    platform_role: PlatformRole
    #: Platform-level permissions (Platform Administrator only).
    permissions: list[Permission]
    #: Per-clinic access. Empty for Platform Administrators (they can access every clinic).
    clinics: list[ClinicAccess]
    all_clinics: bool
    #: The practitioner record of this login (practitioner logins only).
    practitioner_id: UUID | None = None
    #: Short-lived link to my profile photo (fetch /auth/me again after it expires). None = no photo.
    avatar_url: str | None = None
    #: Sign-in is email + password through Cognito; the API never sees a password.
    sign_in_method: Literal["email_password"] = "email_password"
    last_login_at: datetime | None = None
