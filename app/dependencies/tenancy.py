"""Access checks for routes. THE place where the API decides 404 vs 403 (CLAUDE.md rule 13).

Every route under ``/clinics/{clinic_id}/...`` depends on ``clinic_access(...)``:

* the caller may not see the clinic (or it does not exist) → 404 (we never reveal it exists)
* they may see it but not do this                          → 403
* allowed                                                  → a ``ClinicContext``

The database checks the same rules again (row-level security): defense in depth.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import Depends, Path
from sqlalchemy.orm import Session

from app.core.errors import ForbiddenError, NotFoundError
from app.core.rbac import GLOBAL_PERMISSIONS, ClinicContext, Permission, Principal
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.models import Clinic


def clinic_access(permission: Permission) -> Callable[..., ClinicContext]:
    if permission in GLOBAL_PERMISSIONS:
        raise ValueError(f"{permission} is platform-level; use platform_permission()")

    def dependency(
        clinic_id: UUID = Path(description="Clinic id"),
        principal: Principal = Depends(get_principal),
        db: Session = Depends(get_db),
    ) -> ClinicContext:
        permissions = principal.clinic_permissions(clinic_id)
        # The admin "sees" every id; make sure the clinic is real (row-level security agrees).
        if not permissions or db.get(Clinic, clinic_id) is None:
            raise NotFoundError("Clinic not found")
        if permission not in permissions:
            raise ForbiddenError("You are not allowed to do this in this clinic.")
        return ClinicContext(principal=principal, clinic_id=clinic_id, permissions=permissions)

    return dependency


def platform_permission(permission: Permission) -> Callable[..., Principal]:
    if permission not in GLOBAL_PERMISSIONS:
        raise ValueError(f"{permission} is clinic-scoped; use clinic_access()")

    def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.has(permission):
            raise ForbiddenError("You are not allowed to do this.")
        return principal

    return dependency
