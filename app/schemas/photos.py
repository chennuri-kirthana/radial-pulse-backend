from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from app.core.enums import PhotoAngle, PhotoAttire, PhotoCategory, PhotoReviewState, ProcessingStatus
from app.schemas.common import ApiModel, UploadTicket


class PhotoRead(ApiModel):
    id: UUID
    clinic_id: UUID
    practitioner_id: UUID | None
    attire: PhotoAttire | None
    outfit_no: int | None
    angle: PhotoAngle | None
    category: PhotoCategory | None
    mime_type: str
    size_bytes: int
    width: int | None
    height: int | None
    processing_status: ProcessingStatus
    review_state: PhotoReviewState
    review_note: str | None
    reviewed_at: datetime | None
    check_results: dict[str, object]
    created_at: datetime
    updated_at: datetime


class PhotoUploadRequest(ApiModel):
    """A PRACTITIONER photo (practitioner_id + attire + outfit_no + angle) or a CLINIC photo
    (``category``, may be left empty: the DSM sorts it before approving)."""

    content_type: str
    size_bytes: int
    practitioner_id: UUID | None = None
    attire: PhotoAttire | None = None
    outfit_no: int | None = Field(default=None, ge=1, le=20)
    angle: PhotoAngle | None = None
    category: PhotoCategory | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        practitioner_fields = (self.practitioner_id, self.attire, self.outfit_no, self.angle)
        if any(f is not None for f in practitioner_fields):
            if any(f is None for f in practitioner_fields):
                raise ValueError("a practitioner photo needs practitioner_id, attire, outfit_no and angle")
            if self.category is not None:
                raise ValueError("a practitioner photo has no category")
        return self


class PhotoUploadResponse(ApiModel):
    photo: PhotoRead
    upload: UploadTicket


class PhotoReview(ApiModel):
    """Staff decision. ``rejected`` needs a note. Approving a replacement retires the old live photo."""

    review_state: Literal[PhotoReviewState.APPROVED, PhotoReviewState.REJECTED]
    review_note: str | None = Field(default=None, max_length=1000)
    #: sort a clinic photo while reviewing (clinic photos must have a category to be approved)
    category: PhotoCategory | None = None

    @model_validator(mode="after")
    def _rejection_says_why(self) -> Self:
        if self.review_state == PhotoReviewState.REJECTED and not (
            self.review_note and self.review_note.strip()
        ):
            raise ValueError("say why the photo is rejected (review_note)")
        return self


class PhotoSort(ApiModel):
    """Staff sort a clinic photo into a category."""

    category: PhotoCategory
