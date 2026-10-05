from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS, ErrorResponses, Limit, Offset
from app.core.config import Settings
from app.core.enums import ClinicStage, ClinicStageGroup
from app.core.errors import ProblemDetails
from app.core.rbac import ClinicContext, Permission, Principal
from app.dependencies.adapters import get_invite_sender, settings_dependency
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access, platform_permission
from app.integrations.invites import InviteSender
from app.schemas.clinics import (
    ArchiveRequest,
    ClinicCreate,
    ClinicListItem,
    ClinicRead,
    ClinicUpdate,
    StageChange,
    StageHistoryRead,
    TeamMemberCreate,
    TeamMemberRead,
    TeamMemberUpdate,
)
from app.schemas.common import Page
from app.services import clinics as service

router = APIRouter(prefix="/clinics", tags=["clinics"], responses=ERRORS)

STATE_ERROR: ErrorResponses = {
    409: {"model": ProblemDetails, "description": "Not allowed in the clinic's current state"}
}


@router.get(
    "",
    response_model=Page[ClinicListItem],
    summary="Clinics the caller may see, with filters (the Clinics / My Client Portfolio table)",
)
def list_clinics(
    stage: list[ClinicStage] | None = Query(default=None, description="One or more stages"),
    group: ClinicStageGroup | None = Query(
        default=None, description="An Admin tab: prospects (stages 1-2), in_progress (3-4) or active (5)"
    ),
    dsm_user_id: UUID | None = Query(default=None, description="Only clinics of this DSM"),
    unassigned: bool = Query(default=False, description="Only clinics without a DSM"),
    q: str | None = Query(default=None, max_length=100, description="Search clinic, practitioner or website"),
    archived: bool = Query(default=False, description="true = only archived clinics"),
    limit: Limit = 50,
    offset: Offset = 0,
    principal: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> Page[ClinicListItem]:
    items, total = service.list_clinics(
        db, principal, limit, offset,
        stages=stage, group=group, dsm_user_id=dsm_user_id, unassigned=unassigned,
        search=q, archived=archived,
    )  # fmt: skip
    return Page[ClinicListItem](items=items, total=total, limit=limit, offset=offset)


@router.post(
    "", response_model=ClinicRead, status_code=status.HTTP_201_CREATED, summary="Add a clinic (a lead)"
)
def create_clinic(
    body: ClinicCreate,
    principal: Principal = Depends(platform_permission(Permission.CLINICS_CREATE)),
    db: Session = Depends(get_db),
) -> ClinicRead:
    return ClinicRead.model_validate(service.create_clinic(db, principal, body))


@router.get("/{clinic_id}", response_model=ClinicRead)
def get_clinic(
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_READ)), db: Session = Depends(get_db)
) -> ClinicRead:
    return ClinicRead.model_validate(service.get_clinic(db, ctx))


@router.patch("/{clinic_id}", response_model=ClinicRead, summary="Edit clinic details")
def update_clinic(
    body: ClinicUpdate,
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_WRITE)),
    db: Session = Depends(get_db),
) -> ClinicRead:
    return ClinicRead.model_validate(service.update_clinic(db, ctx, body))


# ------------------------------------------------------------------ stages & archive
@router.post(
    "/{clinic_id}/stage",
    response_model=ClinicRead,
    responses=STATE_ERROR,
    summary="Move the clinic to a stage",
)
def change_stage(
    body: StageChange,
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_MANAGE)),
    db: Session = Depends(get_db),
) -> ClinicRead:
    return ClinicRead.model_validate(service.change_stage(db, ctx, body))


@router.get("/{clinic_id}/stage-history", response_model=list[StageHistoryRead], summary="Every stage move")
def stage_history(
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_MANAGE)), db: Session = Depends(get_db)
) -> list[StageHistoryRead]:
    return [StageHistoryRead.model_validate(h) for h in service.stage_history(db, ctx)]


@router.post(
    "/{clinic_id}/archive",
    response_model=ClinicRead,
    responses=STATE_ERROR,
    summary="Archive the clinic (e.g. it said no). A reason is required",
)
def archive_clinic(
    body: ArchiveRequest,
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_MANAGE)),
    db: Session = Depends(get_db),
) -> ClinicRead:
    return ClinicRead.model_validate(service.archive_clinic(db, ctx, body.reason))


@router.post(
    "/{clinic_id}/restore",
    response_model=ClinicRead,
    responses=STATE_ERROR,
    summary="Bring an archived clinic back",
)
def restore_clinic(
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_MANAGE)), db: Session = Depends(get_db)
) -> ClinicRead:
    return ClinicRead.model_validate(service.restore_clinic(db, ctx))


# -------------------------------------------------------------------------- team
@router.get("/{clinic_id}/team", response_model=list[TeamMemberRead], summary="Clinic-side people and roles")
def list_team(
    ctx: ClinicContext = Depends(clinic_access(Permission.CLINICS_READ)), db: Session = Depends(get_db)
) -> list[TeamMemberRead]:
    return service.list_team(db, ctx)


@router.post(
    "/{clinic_id}/team",
    response_model=TeamMemberRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a Clinic Administrator (sends an invite email)",
)
def add_team_member(
    body: TeamMemberCreate,
    ctx: ClinicContext = Depends(clinic_access(Permission.TEAM_MANAGE)),
    db: Session = Depends(get_db),
    invites: InviteSender = Depends(get_invite_sender),
    settings: Settings = Depends(settings_dependency),
) -> TeamMemberRead:
    return service.add_team_member(db, ctx, body, invites, settings.app_sign_in_url)


@router.patch(
    "/{clinic_id}/team/{membership_id}",
    response_model=TeamMemberRead,
    responses=STATE_ERROR,
    summary="Deactivate or reactivate a team member",
)
def update_team_member(
    membership_id: UUID,
    body: TeamMemberUpdate,
    ctx: ClinicContext = Depends(clinic_access(Permission.TEAM_MANAGE)),
    db: Session = Depends(get_db),
) -> TeamMemberRead:
    return service.set_team_member_active(db, ctx, membership_id, body.is_active)


@router.post(
    "/{clinic_id}/team/{membership_id}/resend-invite",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=STATE_ERROR,
)
def resend_team_invite(
    membership_id: UUID,
    ctx: ClinicContext = Depends(clinic_access(Permission.TEAM_MANAGE)),
    db: Session = Depends(get_db),
    invites: InviteSender = Depends(get_invite_sender),
    settings: Settings = Depends(settings_dependency),
) -> Response:
    service.resend_team_invite(db, ctx, membership_id, invites, settings.app_sign_in_url)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
