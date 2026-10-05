"""Asset upload/download: presigned S3 URLs + metadata + audit trail.

Bytes never pass through the API. The API only:
  1. validates the request (kind, MIME type, size, media labels) and records a pending Asset
  2. hands out a short-lived presigned PUT URL scoped to ONE key under the clinic's prefix, with
     the declared size signed into it (S3 refuses any other size)
  3. on confirm, HEADs the object and checks size/type before marking it uploaded

Clinic media (hospital/clinic photos, doctor photos, voice samples — ``REVIEWED_MEDIA_KINDS``):
  * only the Clinic Administrator uploads it (``media:upload``); Radial Pulse staff review it
  * confirming the upload submits it for review in the same transaction
  * a retake is a NEW upload with ``previous_version_id`` pointing at the old file

Report files follow the report rule: clinic people see them only once the report is PUBLISHED.
Uploads never confirmed are removed by ``expire_stale_uploads`` (``app.cli cleanup-stale-uploads``).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import (
    REVIEWED_MEDIA_KINDS,
    ApprovalAction,
    ApprovalState,
    AssetKind,
    AssetStatus,
    MediaTaxonomyDimension,
)
from app.core.errors import DomainValidationError, ForbiddenError, InvalidStateError, NotFoundError
from app.core.rbac import ClinicContext, Permission
from app.integrations.storage import ObjectStorage
from app.models import Asset
from app.repositories.assets import AssetRepository, MediaTaxonomyRepository
from app.repositories.governance import ApprovalRepository
from app.repositories.tenancy import PractitionerRepository
from app.schemas.assets import (
    AssetDownloadResponse,
    AssetRead,
    AssetReview,
    AssetUploadRequest,
    AssetUploadResponse,
    MediaTaxonomyValueRead,
)
from app.schemas.governance import ApprovalActionRequest
from app.services import audit, governance

IMAGE = {"image/jpeg", "image/png", "image/webp"}
AUDIO = {"audio/mpeg", "audio/mp4", "audio/wav", "audio/webm", "audio/ogg"}
VIDEO = {"video/mp4", "video/quicktime", "video/webm"}
DOCS = {"application/pdf"}

ALLOWED_MIME_TYPES: dict[AssetKind, set[str]] = {
    AssetKind.CLINIC_PHOTO: IMAGE,
    AssetKind.PRACTITIONER_PHOTO: IMAGE,
    AssetKind.LOGO: IMAGE | {"image/svg+xml"},
    AssetKind.BRAND_ASSET: IMAGE | DOCS | {"image/svg+xml"},
    AssetKind.AUDIO: AUDIO,
    AssetKind.VIDEO: VIDEO,
    AssetKind.REPORT: DOCS | {"text/html", "application/json"},
    AssetKind.GENERATED_MEDIA: IMAGE | AUDIO | VIDEO,
    AssetKind.DOCUMENT: DOCS,
    AssetKind.CHAT_ATTACHMENT: IMAGE | DOCS,
}

EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/svg+xml": "svg",
    "audio/mpeg": "mp3",
    "audio/mp4": "m4a",
    "audio/wav": "wav",
    "audio/webm": "weba",
    "audio/ogg": "ogg",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "application/pdf": "pdf",
    "text/html": "html",
    "application/json": "json",
}

#: Which label each kind of clinic media carries: field name -> taxonomy dimension.
#: Every listed label is REQUIRED for that kind; every other label must be left out.
MEDIA_LABELS: dict[AssetKind, dict[str, MediaTaxonomyDimension]] = {
    AssetKind.CLINIC_PHOTO: {"category": MediaTaxonomyDimension.CLINIC_PHOTO_CATEGORY},
    AssetKind.AUDIO: {"category": MediaTaxonomyDimension.VOICE_SAMPLE},
    AssetKind.PRACTITIONER_PHOTO: {
        "apron": MediaTaxonomyDimension.PRACTITIONER_APRON,
        "angle": MediaTaxonomyDimension.PRACTITIONER_ANGLE,
        "outfit": MediaTaxonomyDimension.PRACTITIONER_OUTFIT,
    },
}
LABEL_FIELDS = ("category", "apron", "angle", "outfit")


def storage_key_for(clinic_id: UUID, kind: AssetKind, asset_id: UUID, mime_type: str) -> str:
    """Keys are opaque and tenant-prefixed. User filenames are NEVER part of the key."""
    return f"clinics/{clinic_id}/{kind.value}/{asset_id}.{EXTENSIONS.get(mime_type, 'bin')}"


def size_limit(settings: Settings, mime_type: str) -> int:
    """The largest file allowed for this type (never above ``max_upload_bytes``)."""
    family = mime_type.split("/", 1)[0]
    if family == "image":
        limit = settings.max_image_upload_bytes
    elif family == "audio":
        limit = settings.max_audio_upload_bytes
    elif family == "video":
        limit = settings.max_upload_bytes
    else:
        limit = settings.max_document_upload_bytes
    return min(limit, settings.max_upload_bytes)


def _clients_only(ctx: ClinicContext) -> bool:
    """People who cannot write reports (clinic people) never see unpublished report files."""
    return not ctx.can(Permission.REPORTS_WRITE)


def _check_upload_permission(ctx: ClinicContext, kind: AssetKind) -> None:
    if kind in REVIEWED_MEDIA_KINDS and not ctx.can(Permission.MEDIA_UPLOAD):
        raise ForbiddenError(
            "Only the Clinic Administrator uploads clinic photos, doctor photos and voice samples"
        )
    if kind is AssetKind.REPORT and not ctx.can(Permission.REPORTS_WRITE):
        raise ForbiddenError("Report files are uploaded by the Radial Pulse team")


@dataclass(frozen=True)
class _Labels:
    practitioner_id: UUID | None = None
    category_id: UUID | None = None
    apron_id: UUID | None = None
    angle_id: UUID | None = None
    outfit_id: UUID | None = None


def _resolve_labels(session: Session, ctx: ClinicContext, data: AssetUploadRequest) -> _Labels:
    """Check the media labels against the kind and the taxonomy, and turn codes into ids."""
    wanted = MEDIA_LABELS.get(data.kind, {})
    given = {name: getattr(data, name) for name in LABEL_FIELDS if getattr(data, name) is not None}
    extra = sorted(set(given) - set(wanted))
    if extra:
        raise DomainValidationError(f"{', '.join(extra)} cannot be set on a {data.kind.value} file")
    missing = sorted(set(wanted) - set(given))
    if missing:
        raise DomainValidationError(f"{', '.join(missing)} is required for a {data.kind.value} file")

    taxonomy = MediaTaxonomyRepository(session)
    ids: dict[str, UUID] = {}
    for name, dimension in wanted.items():
        value = taxonomy.get_by_code(dimension, given[name])
        if value is None or not value.is_active:
            raise DomainValidationError(f"Unknown {name} '{given[name]}' (see GET /media/taxonomy)")
        ids[f"{name}_id"] = value.id

    practitioner_id = data.practitioner_id
    if data.kind is AssetKind.PRACTITIONER_PHOTO:
        if practitioner_id is None:
            raise DomainValidationError("practitioner_id is required for a practitioner_photo file")
        link = PractitionerRepository(session).get_in_clinic(ctx.clinic_id, practitioner_id)
        if link is None or not link[0].is_active:
            raise NotFoundError("Practitioner not found in this clinic")
    elif practitioner_id is not None:
        raise DomainValidationError(f"practitioner_id cannot be set on a {data.kind.value} file")
    return _Labels(practitioner_id=practitioner_id, **ids)


def request_upload(
    session: Session, ctx: ClinicContext, data: AssetUploadRequest, storage: ObjectStorage, settings: Settings
) -> AssetUploadResponse:
    _check_upload_permission(ctx, data.kind)
    mime = data.mime_type.lower()
    if mime not in ALLOWED_MIME_TYPES[data.kind]:
        raise DomainValidationError(f"{mime} is not allowed for {data.kind.value}")
    limit = size_limit(settings, mime)
    if data.size_bytes > limit:
        raise DomainValidationError(f"File is larger than the {limit} byte limit for {mime}")
    labels = _resolve_labels(session, ctx, data)

    repo = AssetRepository(session)
    version = 1
    if data.previous_version_id is not None:
        previous = repo.get_in_clinic(
            ctx.clinic_id, data.previous_version_id, clients_only=_clients_only(ctx)
        )
        if previous is None:
            raise NotFoundError("Previous version not found")
        if previous.kind is not data.kind:
            raise DomainValidationError("A new version must be the same kind of file")
        version = previous.version + 1

    asset_id = uuid.uuid4()
    asset = Asset(
        id=asset_id,
        clinic_id=ctx.clinic_id,
        owner_user_id=ctx.principal.user_id,
        kind=data.kind,
        mime_type=mime,
        size_bytes=data.size_bytes,
        storage_key=storage_key_for(ctx.clinic_id, data.kind, asset_id, mime),
        original_filename=data.original_filename,
        checksum_sha256=data.checksum_sha256,
        version=version,
        previous_version_id=data.previous_version_id,
        provenance={"source": "upload"},
        status=AssetStatus.PENDING_UPLOAD,
        practitioner_id=labels.practitioner_id,
        category_id=labels.category_id,
        apron_id=labels.apron_id,
        angle_id=labels.angle_id,
        outfit_id=labels.outfit_id,
    )
    repo.add(asset)
    url, headers = storage.presign_put(
        asset.storage_key, mime, settings.s3_presign_ttl_seconds, data.size_bytes
    )
    audit.record(
        session,
        actor=ctx.principal,
        action="asset.upload_requested",
        resource_type="asset",
        resource_id=asset.id,
        clinic_id=ctx.clinic_id,
        details={
            "kind": data.kind.value,
            "mime_type": mime,
            "size_bytes": data.size_bytes,
            "version": version,
        },
    )
    session.commit()
    return AssetUploadResponse(
        asset=to_reads(session, ctx, [asset])[0],
        upload_url=url,
        upload_headers=headers,
        expires_in=settings.s3_presign_ttl_seconds,
    )


def confirm_upload(session: Session, ctx: ClinicContext, asset_id: UUID, storage: ObjectStorage) -> Asset:
    asset = AssetRepository(session).get_in_clinic(ctx.clinic_id, asset_id)
    if asset is None:
        raise NotFoundError("Asset not found")
    _check_upload_permission(ctx, asset.kind)
    if asset.status is not AssetStatus.PENDING_UPLOAD:
        raise InvalidStateError(f"Asset is already {asset.status.value}")

    info = storage.head(asset.storage_key)
    problem: str | None = None
    if info is None:
        problem = "The file was not found in storage. Upload it before confirming."
    elif info.size_bytes != asset.size_bytes:
        problem = "Uploaded size does not match the declared size."
    elif info.content_type and info.content_type.lower() != asset.mime_type:
        problem = "Uploaded content type does not match the declared type."

    if problem is not None:
        if info is not None:
            asset.status = AssetStatus.FAILED
            storage.delete(asset.storage_key)
        audit.record(
            session,
            actor=ctx.principal,
            action="asset.upload_rejected",
            resource_type="asset",
            resource_id=asset.id,
            clinic_id=ctx.clinic_id,
            details={"reason": problem},
        )
        session.commit()
        raise DomainValidationError(problem)

    asset.status = AssetStatus.UPLOADED
    audit.record(
        session,
        actor=ctx.principal,
        action="asset.upload_confirmed",
        resource_type="asset",
        resource_id=asset.id,
        clinic_id=ctx.clinic_id,
    )
    if asset.kind in REVIEWED_MEDIA_KINDS:
        # Clinic media goes to Radial Pulse staff for review as soon as the upload is confirmed.
        session.flush()
        governance.apply_action(
            session,
            ctx,
            ApprovalActionRequest(resource_type="asset", resource_id=asset.id, action=ApprovalAction.SUBMIT),
            commit=False,
        )
    session.commit()
    return asset


def list_assets(
    session: Session,
    ctx: ClinicContext,
    kind: AssetKind | None,
    limit: int,
    offset: int,
    *,
    status: AssetStatus | None = None,
    approval_state: ApprovalState | None = None,
    practitioner_id: UUID | None = None,
    category: str | None = None,
) -> tuple[list[Any], int]:
    category_id: UUID | None = None
    if category is not None:
        dimension = (
            MediaTaxonomyDimension.VOICE_SAMPLE
            if kind is AssetKind.AUDIO
            else MediaTaxonomyDimension.CLINIC_PHOTO_CATEGORY
        )
        value = MediaTaxonomyRepository(session).get_by_code(dimension, category)
        if value is None:
            return [], 0
        category_id = value.id
    return AssetRepository(session).list_for_clinic(
        ctx.clinic_id,
        kind=kind,
        status=status,
        approval_state=approval_state,
        practitioner_id=practitioner_id,
        category_id=category_id,
        clients_only=_clients_only(ctx),
        limit=limit,
        offset=offset,
    )


def get_asset(session: Session, ctx: ClinicContext, asset_id: UUID) -> Asset:
    asset = AssetRepository(session).get_in_clinic(ctx.clinic_id, asset_id, clients_only=_clients_only(ctx))
    if asset is None:
        raise NotFoundError("Asset not found")
    return asset


def download_url(
    session: Session, ctx: ClinicContext, asset_id: UUID, storage: ObjectStorage, settings: Settings
) -> AssetDownloadResponse:
    asset = AssetRepository(session).get_in_clinic(ctx.clinic_id, asset_id, clients_only=_clients_only(ctx))
    if asset is None or asset.status is not AssetStatus.UPLOADED:
        raise NotFoundError("Asset not found")
    url = storage.presign_get(asset.storage_key, settings.s3_presign_ttl_seconds, asset.original_filename)
    audit.record(
        session,
        actor=ctx.principal,
        action="asset.download_url_issued",
        resource_type="asset",
        resource_id=asset.id,
        clinic_id=ctx.clinic_id,
    )
    session.commit()
    return AssetDownloadResponse(url=url, expires_in=settings.s3_presign_ttl_seconds)


def to_reads(session: Session, ctx: ClinicContext, assets: Sequence[Asset]) -> list[AssetRead]:
    """The API shape of files: label codes and the review, as the CALLER may see it."""
    label_ids = {
        getattr(a, f"{name}_id") for a in assets for name in LABEL_FIELDS if getattr(a, f"{name}_id")
    }
    labels = MediaTaxonomyRepository(session).by_ids(label_ids)
    approvals = ApprovalRepository(session).for_resources(ctx.clinic_id, "asset", [a.id for a in assets])
    reviews = {r.resource_id: r for r in governance.to_reads(session, ctx, list(approvals.values()))}

    def code(label_id: UUID | None) -> str | None:
        return labels[label_id].code if label_id is not None and label_id in labels else None

    rows = []
    for a in assets:
        review = reviews.get(a.id)
        rows.append(
            AssetRead.model_validate(
                {
                    **{
                        name: getattr(a, name)
                        for name in AssetRead.model_fields
                        if name not in (*LABEL_FIELDS, "review")
                    },
                    **{name: code(getattr(a, f"{name}_id")) for name in LABEL_FIELDS},
                    "review": None
                    if review is None
                    else AssetReview(
                        approval_id=review.id,
                        state=review.state,
                        clinic_message=review.clinic_message,
                        internal_note=review.last_comment,
                        submitted_by_user_id=review.submitted_by_user_id,
                        decided_by_user_id=review.decided_by_user_id,
                        available_actions=review.available_actions,
                        updated_at=review.updated_at,
                    ),
                }
            )
        )
    return rows


def list_taxonomy(session: Session) -> list[MediaTaxonomyValueRead]:
    """The labels offered for NEW uploads (retired values are left out)."""
    return [MediaTaxonomyValueRead.model_validate(v) for v in MediaTaxonomyRepository(session).list()]


def expire_stale_uploads(
    session: Session, storage: ObjectStorage, older_than: datetime, *, limit: int = 500, dry_run: bool = False
) -> int:
    """Uploads never confirmed: delete the S3 object (if the client put one) and mark the row FAILED.

    The caller sets the database scope (the CLI uses all clinics). Returns how many were found.
    """
    stale = AssetRepository(session).stale_pending_uploads(older_than, limit)
    if dry_run:
        return len(stale)
    for asset in stale:
        storage.delete(asset.storage_key)
        asset.status = AssetStatus.FAILED
        audit.record(
            session,
            actor=None,
            action="asset.upload_expired",
            resource_type="asset",
            resource_id=asset.id,
            clinic_id=asset.clinic_id,
        )
    session.commit()
    return len(stale)
