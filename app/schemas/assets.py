from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field

from app.core.enums import ApprovalAction, ApprovalState, AssetKind, AssetStatus, MediaTaxonomyDimension
from app.schemas.common import ApiModel

#: A media label code from GET /media/taxonomy, e.g. "exterior_signage", "45_left", "outfit_1".
TaxonomyCode = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")]


class AssetUploadRequest(ApiModel):
    kind: AssetKind
    mime_type: str = Field(min_length=3, max_length=127)
    size_bytes: int = Field(gt=0)
    original_filename: str | None = Field(default=None, max_length=255)
    checksum_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    #: Set when uploading a new version of an existing asset (e.g. a retake).
    previous_version_id: UUID | None = None
    #: Doctor photos (kind practitioner_photo): the practitioner in the photo. Required there.
    practitioner_id: UUID | None = None
    #: Hospital/Clinic photos: the photo category. Voice samples (kind audio): the sample type.
    category: TaxonomyCode | None = None
    #: Doctor photos only: with or without apron, camera angle, outfit.
    apron: TaxonomyCode | None = None
    angle: TaxonomyCode | None = None
    outfit: TaxonomyCode | None = None


class AssetReview(ApiModel):
    """The review of a file (clinic media): its approval, as the CALLER may see it."""

    approval_id: UUID
    state: ApprovalState
    #: The reason Radial Pulse staff gave the clinic (reject / retake). Visible to everyone.
    clinic_message: str | None
    #: The latest INTERNAL review note. Radial Pulse staff only: always null for clinic people.
    internal_note: str | None
    submitted_by_user_id: UUID | None
    decided_by_user_id: UUID | None
    #: What the CALLER may do now (approve / reject / redo = request retake / ...).
    #: Send it to POST /clinics/{id}/approvals/actions with resource_type "asset".
    available_actions: list[ApprovalAction]
    updated_at: datetime


class AssetRead(ApiModel):
    id: UUID
    clinic_id: UUID
    owner_user_id: UUID | None
    kind: AssetKind
    mime_type: str
    size_bytes: int
    original_filename: str | None
    version: int
    previous_version_id: UUID | None
    provenance: dict[str, Any]
    status: AssetStatus
    approval_state: ApprovalState
    practitioner_id: UUID | None = None
    category: str | None = None
    apron: str | None = None
    angle: str | None = None
    outfit: str | None = None
    #: Null until the file is in review (clinic media enters review when its upload is confirmed).
    review: AssetReview | None = None
    created_at: datetime
    updated_at: datetime


class AssetUploadResponse(ApiModel):
    asset: AssetRead
    #: Presigned S3 PUT URL. Short-lived. Do not log or store it. The file size is part of the
    #: signature: upload exactly ``size_bytes`` bytes.
    upload_url: str
    #: Headers the client MUST send with the PUT (content type, encryption).
    upload_headers: dict[str, str]
    expires_in: int


class AssetDownloadResponse(ApiModel):
    url: str
    expires_in: int


class MediaTaxonomyValueRead(ApiModel):
    dimension: MediaTaxonomyDimension
    code: str
    label: str
    sort_order: int
