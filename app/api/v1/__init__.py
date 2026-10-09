"""Version 1 of the platform API. Mounted at /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routers import (
    auth,
    client_organizations,
    clinic_members,
    clinic_practitioners,
    clinic_profiles,
    clinics,
    collaboration_messages,
    connected_accounts,
    digital_presence_assessments,
    improvement_work_items,
    internal,
    notifications,
    photos,
    portfolio_allocations,
    practitioner_profile,
    practitioners,
    settings,
    users,
    voice_samples,
)

api_router = APIRouter()
for module in (
    auth,
    users,
    client_organizations,
    clinics,
    portfolio_allocations,
    clinic_members,
    clinic_practitioners,
    practitioners,
    clinic_profiles,
    digital_presence_assessments,
    improvement_work_items,
    notifications,
    collaboration_messages,
    photos,
    voice_samples,
    connected_accounts,
    settings,
    practitioner_profile,
    internal,
):
    api_router.include_router(module.router)
