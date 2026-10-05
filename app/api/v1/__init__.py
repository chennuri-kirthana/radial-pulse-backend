"""Version 1 of the platform API. Mounted at /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routers import (
    approvals,
    assessments,
    assets,
    assignments,
    audit_log,
    auth,
    chat,
    clinics,
    connections,
    dashboard,
    media,
    notifications,
    practitioners,
    presence,
    profiles,
    reports,
    settings,
    snapshots,
    users,
    work_items,
)

api_router = APIRouter()
for module in (
    auth,
    users,
    dashboard,
    clinics,
    practitioners,
    assignments,
    profiles,
    presence,
    assessments,
    assets,
    media,
    approvals,
    audit_log,
    work_items,
    notifications,
    snapshots,
    reports,
    chat,
    connections,
    settings,
):
    api_router.include_router(module.router)
# Lists across clinics (no clinic in the path; scoped to the caller's clinics like GET /clinics).
api_router.include_router(chat.inbox_router)
api_router.include_router(assessments.list_router)
api_router.include_router(work_items.list_router)
