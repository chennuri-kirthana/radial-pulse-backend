"""Approvals: one small, explicit state machine shared by every team.

This is NOT a workflow engine. It records who submitted/approved/rejected/asked
for a redo/published/handed off a resource, keeps the resource's own state in
sync, and writes an audit event for every action.

Resource types must be REGISTERED below. Registration does two things:
* proves the resource exists INSIDE the same clinic (no cross-tenant approvals)
* mirrors the approval/publication state onto the resource row
Teams add their resource type (e.g. "website_brief", "video_job") with a small handler.

Notes: ``comment`` is an INTERNAL note (Radial Pulse staff only, stored in ``approval_notes``,
which the database hides from clinic people). ``clinic_message`` is what the clinic reads.

Clinic media (hospital/clinic photos, doctor photos, voice samples): the Clinic Administrator
uploads, the upload's confirm submits it for review, and ONLY Radial Pulse staff approve, reject
or ask for a retake (``redo``). Migration 0013 enforces the same rule in the database.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.enums import (
    REVIEWED_MEDIA_KINDS,
    ApprovalAction,
    ApprovalState,
    AssessmentStatus,
    AssetStatus,
    NotificationCategory,
    PublicationState,
)
from app.core.errors import DomainValidationError, ForbiddenError, InvalidStateError, NotFoundError
from app.core.rbac import ClinicContext, Permission
from app.db.base import utcnow
from app.models import Approval, ApprovalNote, Assessment
from app.repositories.assessments import AssessmentRepository
from app.repositories.assets import AssetRepository
from app.repositories.governance import ApprovalNoteRepository, ApprovalRepository, AuditEventRepository
from app.repositories.reporting import ReportRepository
from app.repositories.users import UserRepository
from app.schemas.governance import ApprovalActionRequest, ApprovalRead
from app.services import audit, notify
from app.services.identity import build_principal

# ------------------------------------------------------------- state machine
S = ApprovalState

#: action -> (states it may start from, resulting state or None if state is unchanged)
TRANSITIONS: dict[ApprovalAction, tuple[frozenset[ApprovalState], ApprovalState | None]] = {
    ApprovalAction.SUBMIT: (frozenset({S.DRAFT, S.REJECTED, S.REDO_REQUESTED}), S.SUBMITTED),
    ApprovalAction.APPROVE: (frozenset({S.SUBMITTED}), S.APPROVED),
    ApprovalAction.REJECT: (frozenset({S.SUBMITTED}), S.REJECTED),
    ApprovalAction.REDO: (frozenset({S.SUBMITTED, S.APPROVED}), S.REDO_REQUESTED),
    ApprovalAction.PUBLISH: (frozenset({S.APPROVED}), None),
    ApprovalAction.HANDOFF: (frozenset(ApprovalState), None),
}

PermissionMap = Mapping[ApprovalAction, Permission]

REQUIRED_PERMISSION: PermissionMap = {
    ApprovalAction.SUBMIT: Permission.APPROVALS_SUBMIT,
    ApprovalAction.APPROVE: Permission.APPROVALS_DECIDE,
    ApprovalAction.REJECT: Permission.APPROVALS_DECIDE,
    ApprovalAction.REDO: Permission.APPROVALS_DECIDE,
    ApprovalAction.PUBLISH: Permission.APPROVALS_PUBLISH,
    ApprovalAction.HANDOFF: Permission.APPROVALS_SUBMIT,
}

#: Clinic media: the clinic submits (its upload's confirm does it), Radial Pulse staff decide.
MEDIA_REVIEW_PERMISSION: PermissionMap = {
    **REQUIRED_PERMISSION,
    ApprovalAction.SUBMIT: Permission.MEDIA_UPLOAD,
    ApprovalAction.APPROVE: Permission.MEDIA_REVIEW,
    ApprovalAction.REJECT: Permission.MEDIA_REVIEW,
    ApprovalAction.REDO: Permission.MEDIA_REVIEW,
}

#: Actions that may carry a message for the clinic.
CLINIC_MESSAGE_ACTIONS = frozenset({ApprovalAction.APPROVE, ApprovalAction.REJECT, ApprovalAction.REDO})


# ------------------------------------------------------------- resource registry
@dataclass(frozen=True)
class ResourceHandler:
    #: Return True if resource_id exists in clinic_id.
    exists: Callable[[Session, UUID, UUID], bool]
    #: Mirror approval state onto the resource row.
    sync: Callable[[Session, UUID, UUID, Approval], None]
    #: Optional: raise InvalidStateError if the resource is not ready to be submitted.
    before_submit: Callable[[Session, UUID, UUID], None] | None = None
    #: Optional: raise InvalidStateError if the resource cannot be reviewed at all right now
    #: (checked before EVERY action, e.g. a file whose upload was never confirmed).
    before_any: Callable[[Session, UUID, UUID], None] | None = None
    #: Optional: who may do what, per resource (default: REQUIRED_PERMISSION). Batched for lists.
    permissions: Callable[[Session, UUID, Collection[UUID]], dict[UUID, PermissionMap]] | None = None
    #: Optional: per resource, the states a MANUAL submit may start from (default: TRANSITIONS).
    manual_submit_from: Callable[[Session, UUID, UUID], frozenset[ApprovalState] | None] | None = None
    #: Only Radial Pulse staff may see or act on it (the assessment publication gate).
    staff_only: bool = False


def _report_exists(session: Session, clinic_id: UUID, resource_id: UUID) -> bool:
    return ReportRepository(session).get_in_clinic(clinic_id, resource_id) is not None


def _report_sync(session: Session, clinic_id: UUID, resource_id: UUID, approval: Approval) -> None:
    report = ReportRepository(session).get_in_clinic(clinic_id, resource_id)
    if report is None:
        return
    report.approval_state = approval.state
    if approval.publication_state is PublicationState.PUBLISHED and report.published_at is None:
        report.published_at = utcnow()
    report.publication_state = approval.publication_state


def _asset_exists(session: Session, clinic_id: UUID, resource_id: UUID) -> bool:
    return AssetRepository(session).get_in_clinic(clinic_id, resource_id) is not None


def _asset_sync(session: Session, clinic_id: UUID, resource_id: UUID, approval: Approval) -> None:
    asset = AssetRepository(session).get_in_clinic(clinic_id, resource_id)
    if asset is not None:
        asset.approval_state = approval.state


def _asset_uploaded(session: Session, clinic_id: UUID, resource_id: UUID) -> None:
    asset = AssetRepository(session).get_in_clinic(clinic_id, resource_id)
    if asset is not None and asset.status is not AssetStatus.UPLOADED:
        raise InvalidStateError("The upload is not confirmed yet: confirm it before it can be reviewed")


def _asset_permissions(
    session: Session, clinic_id: UUID, resource_ids: Collection[UUID]
) -> dict[UUID, PermissionMap]:
    kinds = AssetRepository(session).kinds_in_clinic(clinic_id, resource_ids)
    return {
        asset_id: MEDIA_REVIEW_PERMISSION if kind in REVIEWED_MEDIA_KINDS else REQUIRED_PERMISSION
        for asset_id, kind in kinds.items()
    }


def _asset_manual_submit_from(
    session: Session, clinic_id: UUID, resource_id: UUID
) -> frozenset[ApprovalState] | None:
    """Clinic media enters review when its upload is confirmed. A rejected photo or a retake is a
    NEW upload (``previous_version_id``), never the same file sent again."""
    kinds = AssetRepository(session).kinds_in_clinic(clinic_id, [resource_id])
    return frozenset({S.DRAFT}) if kinds.get(resource_id) in REVIEWED_MEDIA_KINDS else None


def _get_assessment(session: Session, clinic_id: UUID, resource_id: UUID) -> Assessment | None:
    return AssessmentRepository(session).get_in_clinic(clinic_id, resource_id)


def _assessment_exists(session: Session, clinic_id: UUID, resource_id: UUID) -> bool:
    return _get_assessment(session, clinic_id, resource_id) is not None


def _assessment_ready(session: Session, clinic_id: UUID, resource_id: UUID) -> None:
    assessment = _get_assessment(session, clinic_id, resource_id)
    if assessment is not None and assessment.status not in (
        AssessmentStatus.COMPLETED,
        AssessmentStatus.PARTIAL,
    ):
        raise InvalidStateError("Only a finished assessment can be submitted for review")


def _assessment_sync(session: Session, clinic_id: UUID, resource_id: UUID, approval: Approval) -> None:
    assessment = _get_assessment(session, clinic_id, resource_id)
    if assessment is None:
        return
    assessment.approval_state = approval.state
    if approval.publication_state is PublicationState.PUBLISHED and assessment.published_at is None:
        assessment.published_at = utcnow()
    assessment.publication_state = approval.publication_state


RESOURCE_HANDLERS: dict[str, ResourceHandler] = {
    # The ONE user-facing Digital Presence Assessment.
    # Staff-only: clinic users never approve, reject, redo (retract) or publish it.
    "assessment": ResourceHandler(
        exists=_assessment_exists, sync=_assessment_sync, before_submit=_assessment_ready, staff_only=True
    ),
    # Other outputs (exports, briefs, media) and uploaded assets.
    "report_artifact": ResourceHandler(exists=_report_exists, sync=_report_sync),
    # Uploaded files. Clinic media is reviewed by Radial Pulse staff only (MEDIA_REVIEW_PERMISSION).
    "asset": ResourceHandler(
        exists=_asset_exists,
        sync=_asset_sync,
        before_any=_asset_uploaded,
        permissions=_asset_permissions,
        manual_submit_from=_asset_manual_submit_from,
    ),
}

#: Resource types clinic people never see in the approvals list (their review is staff-only).
STAFF_ONLY_RESOURCE_TYPES = frozenset(name for name, h in RESOURCE_HANDLERS.items() if h.staff_only)


def _permission_map(
    session: Session, ctx: ClinicContext, resource_type: str, resource_id: UUID
) -> PermissionMap:
    handler = RESOURCE_HANDLERS[resource_type]
    if handler.permissions is None:
        return REQUIRED_PERMISSION
    return handler.permissions(session, ctx.clinic_id, [resource_id]).get(resource_id, REQUIRED_PERMISSION)


# ------------------------------------------------------------- service functions
def apply_action(
    session: Session, ctx: ClinicContext, data: ApprovalActionRequest, *, commit: bool = True
) -> Approval:
    """Apply one review action. ``commit=False`` lets a caller (e.g. the upload confirm) commit it
    together with its own change."""
    handler = RESOURCE_HANDLERS.get(data.resource_type)
    if handler is None:
        raise DomainValidationError(
            f"Unknown resource_type '{data.resource_type}'. Register it in app/services/governance.py."
        )
    if handler.staff_only and not ctx.principal.is_internal:
        raise ForbiddenError("Only the Radial Pulse team reviews this")
    if not handler.exists(session, ctx.clinic_id, data.resource_id):
        raise NotFoundError("Resource not found in this clinic")
    if not ctx.can(_permission_map(session, ctx, data.resource_type, data.resource_id)[data.action]):
        raise ForbiddenError(f"You cannot '{data.action.value}' here")
    if data.comment is not None and not ctx.principal.is_internal:
        raise ForbiddenError("Internal notes are for the Radial Pulse team. Use clinic_message instead.")
    if data.clinic_message is not None and data.action not in CLINIC_MESSAGE_ACTIONS:
        raise DomainValidationError("clinic_message goes with approve, reject or redo")
    if handler.before_any is not None:
        handler.before_any(session, ctx.clinic_id, data.resource_id)
    if data.action is ApprovalAction.SUBMIT and handler.before_submit is not None:
        handler.before_submit(session, ctx.clinic_id, data.resource_id)

    repo = ApprovalRepository(session)
    approval = repo.get_for_resource(ctx.clinic_id, data.resource_type, data.resource_id)
    if approval is None:
        if data.action is not ApprovalAction.SUBMIT:
            raise InvalidStateError("Submit the resource for review first")
        approval = Approval(
            clinic_id=ctx.clinic_id, resource_type=data.resource_type, resource_id=data.resource_id
        )
        repo.add(approval)

    allowed_from, target = TRANSITIONS[data.action]
    if data.action is ApprovalAction.SUBMIT and handler.manual_submit_from is not None:
        allowed_from = handler.manual_submit_from(session, ctx.clinic_id, data.resource_id) or allowed_from
    if approval.state not in allowed_from:
        raise InvalidStateError(f"Cannot {data.action.value} when state is {approval.state.value}")

    previous_state = approval.state
    actor_id = ctx.principal.user_id
    if target is not None:
        approval.state = target
    if data.action is ApprovalAction.SUBMIT:
        approval.submitted_by_user_id = actor_id
        approval.publication_state = PublicationState.UNPUBLISHED
        approval.clinic_message = None  # a new review round starts without the old reason
    elif data.action in (ApprovalAction.APPROVE, ApprovalAction.REJECT, ApprovalAction.REDO):
        approval.decided_by_user_id = actor_id
        if data.action is ApprovalAction.REDO and approval.publication_state is PublicationState.PUBLISHED:
            approval.publication_state = PublicationState.RETRACTED
    elif data.action is ApprovalAction.PUBLISH:
        if approval.publication_state is PublicationState.PUBLISHED:
            raise InvalidStateError("Already published")
        approval.publication_state = PublicationState.PUBLISHED
    elif data.action is ApprovalAction.HANDOFF:
        _handoff(session, ctx, approval, data.assignee_user_id)

    if data.clinic_message is not None:
        approval.clinic_message = data.clinic_message
    if data.comment is not None:
        session.flush()  # the approval row must exist before its note
        session.add(
            ApprovalNote(
                clinic_id=ctx.clinic_id, approval_id=approval.id, author_user_id=actor_id, body=data.comment
            )
        )

    handler.sync(session, ctx.clinic_id, data.resource_id, approval)
    audit.record(
        session,
        actor=ctx.principal,
        action=f"approval.{data.action.value}",
        resource_type=data.resource_type,
        resource_id=data.resource_id,
        clinic_id=ctx.clinic_id,
        details={
            "approval_id": str(approval.id),
            "from_state": previous_state.value,
            "to_state": approval.state.value,
            "publication_state": approval.publication_state.value,
            "has_comment": data.comment is not None,
            "has_clinic_message": data.clinic_message is not None,
        },
    )
    if commit:
        session.commit()
    return approval


def _handoff(session: Session, ctx: ClinicContext, approval: Approval, assignee_id: UUID | None) -> None:
    if assignee_id is None:
        raise DomainValidationError("assignee_user_id is required for handoff")
    assignee = UserRepository(session).get(assignee_id)
    # Row-level security hides accounts with no link to this clinic, so "not visible" and
    # "no access" are the same answer here.
    if assignee is None:
        raise DomainValidationError("Assignee has no access to this clinic")
    if not assignee.is_active:
        raise NotFoundError("Assignee not found")
    if not build_principal(session, assignee).can_access_clinic(ctx.clinic_id):
        raise DomainValidationError("Assignee has no access to this clinic")
    approval.assignee_user_id = assignee.id
    notify.send(
        session,
        user_id=assignee.id,
        category=NotificationCategory.APPROVAL_HANDOFF,
        clinic_id=ctx.clinic_id,
        kind="approval.handoff",
        title="An item was handed to you for review",
        link=f"/clinics/{ctx.clinic_id}/approvals/{approval.id}",
    )


def available_actions(
    ctx: ClinicContext, approval: Approval, permissions: PermissionMap
) -> list[ApprovalAction]:
    """The actions THIS caller may take on the approval right now — the buttons to show.

    The same rules as ``apply_action`` (state machine, permission, staff-only resources,
    already published), so a screen never has to repeat them. ``permissions`` is the
    resource's permission map (``_permission_maps``).
    """
    handler = RESOURCE_HANDLERS.get(approval.resource_type)
    if handler is None or (handler.staff_only and not ctx.principal.is_internal):
        return []
    actions = []
    for action, (allowed_from, _target) in TRANSITIONS.items():
        if approval.state not in allowed_from or not ctx.can(permissions[action]):
            continue
        if action is ApprovalAction.PUBLISH and approval.publication_state is PublicationState.PUBLISHED:
            continue
        actions.append(action)
    if permissions is MEDIA_REVIEW_PERMISSION and approval.state is not S.DRAFT:
        # Clinic media: a retake is a new upload, never the same file sent again.
        actions = [a for a in actions if a is not ApprovalAction.SUBMIT]
    return actions


def _permission_maps(
    session: Session, ctx: ClinicContext, approvals: Collection[Approval]
) -> dict[UUID, PermissionMap]:
    """approval id -> permission map, with one query per resource type (lists stay cheap)."""
    by_type: dict[str, list[Approval]] = {}
    for approval in approvals:
        by_type.setdefault(approval.resource_type, []).append(approval)
    result: dict[UUID, PermissionMap] = {}
    for resource_type, rows in by_type.items():
        handler = RESOURCE_HANDLERS.get(resource_type)
        maps = (
            handler.permissions(session, ctx.clinic_id, [a.resource_id for a in rows])
            if handler is not None and handler.permissions is not None
            else {}
        )
        for approval in rows:
            result[approval.id] = maps.get(approval.resource_id, REQUIRED_PERMISSION)
    return result


def internal_notes(session: Session, ctx: ClinicContext, approval_ids: Collection[UUID]) -> dict[UUID, str]:
    """Latest internal note per approval — EMPTY for clinic people (they never see internal notes)."""
    if not ctx.principal.is_internal:
        return {}
    return ApprovalNoteRepository(session).latest_for(ctx.clinic_id, approval_ids)


def to_reads(session: Session, ctx: ClinicContext, approvals: Collection[Approval]) -> list[ApprovalRead]:
    """The API shape of approvals, with what the caller may do next and the notes they may read."""
    maps = _permission_maps(session, ctx, approvals)
    notes = internal_notes(session, ctx, [a.id for a in approvals])
    skip = {"available_actions", "last_comment"}
    return [
        ApprovalRead.model_validate(
            {
                **{name: getattr(a, name) for name in ApprovalRead.model_fields if name not in skip},
                "last_comment": notes.get(a.id),
                "available_actions": available_actions(ctx, a, maps[a.id]),
            }
        )
        for a in approvals
    ]


def to_read(session: Session, ctx: ClinicContext, approval: Approval) -> ApprovalRead:
    return to_reads(session, ctx, [approval])[0]


def list_approvals(
    session: Session,
    ctx: ClinicContext,
    state: ApprovalState | None,
    limit: int,
    offset: int,
    resource_type: str | None = None,
) -> tuple[list[Any], int]:
    """Clinic people never see staff-only reviews (an unpublished assessment's review)."""
    hidden = () if ctx.principal.is_internal else STAFF_ONLY_RESOURCE_TYPES
    return ApprovalRepository(session).list_for_clinic(
        ctx.clinic_id, state, limit, offset, resource_type=resource_type, hidden_resource_types=hidden
    )


def get_approval(session: Session, ctx: ClinicContext, approval_id: UUID) -> Approval:
    approval = ApprovalRepository(session).get_in_clinic(ctx.clinic_id, approval_id)
    if approval is None or (
        approval.resource_type in STAFF_ONLY_RESOURCE_TYPES and not ctx.principal.is_internal
    ):
        raise NotFoundError("Approval not found")
    return approval


def list_audit_events(session: Session, ctx: ClinicContext, limit: int, offset: int) -> tuple[list[Any], int]:
    """Clinic people never see review activity (``approval.*``) or assessment work."""
    return AuditEventRepository(session).list_for_clinic(
        ctx.clinic_id, limit, offset, hide_internal_review=not ctx.principal.is_internal
    )
