"""Photos: practitioner photos and clinic (hospital) photos, with DSM review."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.enums import PhotoCategory, PhotoReviewState
from app.core.rbac import ClinicContext, Permission
from app.dependencies.adapters import get_storage
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.integrations.storage import ObjectStorage
from app.schemas.common import ViewLink
from app.schemas.photos import PhotoRead, PhotoReview, PhotoSort, PhotoUploadRequest, PhotoUploadResponse
from app.services import photos

router = APIRouter(prefix="/clinics/{clinic_id}/photos", tags=["photos"], responses=ERRORS)
_read = clinic_access(Permission.PHOTOS_READ)
_upload = clinic_access(Permission.PHOTOS_UPLOAD)
_review = clinic_access(Permission.PHOTOS_REVIEW)


@router.get("", response_model=list[PhotoRead], summary="Photos, newest first")
def list_photos(
    practitioner_id: UUID | None = None,
    category: PhotoCategory | None = None,
    review_state: PhotoReviewState | None = None,
    unsorted: bool = False,
    ctx: ClinicContext = Depends(_read),
    db: Session = Depends(get_db),
) -> list[PhotoRead]:
    """``unsorted=true``: clinic photos the DSM has not sorted into a category yet."""
    return photos.list_photos(
        db,
        ctx,
        practitioner_id=practitioner_id,
        category=category,
        review_state=review_state,
        unsorted=unsorted,
    )


@router.post("/uploads", response_model=PhotoUploadResponse, status_code=status.HTTP_201_CREATED)
def request_upload(
    body: PhotoUploadRequest,
    ctx: ClinicContext = Depends(_upload),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> PhotoUploadResponse:
    """Step 1 (Clinic Administrator, or the practitioner for his own photos). JPEG / PNG / WebP /
    HEIC, at most 15 MB. PUT the file to ``upload.upload_url``, then call ``/complete``.
    A slot already has a photo waiting for review → 409."""
    return photos.request_upload(db, ctx, body, storage)


@router.post("/{photo_id}/complete", response_model=PhotoRead, summary="Step 2: the file is in S3")
def complete_upload(
    photo_id: UUID,
    ctx: ClinicContext = Depends(_upload),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> PhotoRead:
    return photos.complete_upload(db, ctx, photo_id, storage)


@router.get("/{photo_id}/view", response_model=ViewLink, summary="Short-lived link to look at the photo")
def view_link(
    photo_id: UUID,
    ctx: ClinicContext = Depends(_read),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> ViewLink:
    """Every link handed out is audited."""
    return photos.view_link(db, ctx, photo_id, storage)


@router.post("/{photo_id}/review", response_model=PhotoRead)
def review(
    photo_id: UUID, body: PhotoReview, ctx: ClinicContext = Depends(_review), db: Session = Depends(get_db)
) -> PhotoRead:
    """DSM or Platform Administrator. Approving a replacement retires the old live photo
    ("Replaced by a newer photo") in the same step."""
    return photos.review(db, ctx, photo_id, body)


@router.post("/{photo_id}/sort", response_model=PhotoRead, summary="Put a clinic photo in a category")
def sort(
    photo_id: UUID, body: PhotoSort, ctx: ClinicContext = Depends(_review), db: Session = Depends(get_db)
) -> PhotoRead:
    return photos.sort(db, ctx, photo_id, body)


@router.delete("/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(photo_id: UUID, ctx: ClinicContext = Depends(_upload), db: Session = Depends(get_db)) -> None:
    """Clinic Administrator, or the practitioner for his own photo. The DSM can't delete photos."""
    photos.delete(db, ctx, photo_id)
