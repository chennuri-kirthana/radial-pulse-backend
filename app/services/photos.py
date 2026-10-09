"""Photos (docs/01-decisions.md section 6).

* Who uploads: the Clinic Administrator, or the practitioner for HIS own photos. Never the DSM,
  never Clinic Team Members.
* Upload: (1) ask → a ``photos`` row (``uploading``) + presigned PUT to
  ``clinics/<clinic>/photos/<photo id>.<ext>``; (2) PUT to S3; (3) complete → the file is checked
  in S3 → ``ready``. (Image processing / AI pre-checks come later; ``check_results`` stays empty.)
* Review (DSM / Platform Administrator): approve or reject (with a note). Per slot at most 1 live
  + 1 waiting photo. Approving a replacement: in the SAME transaction the old live photo is first
  rejected with "Replaced by a newer photo", then the new one approved.
* Every view link is audited. No download endpoint.
* Deleting removes the row only; S3 files stay (deliberately not done yet, docs/01 section 13).
"""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import PhotoCategory, PhotoReviewState, ProcessingStatus
from app.core.errors import ConflictError, ForbiddenError, InvalidRequestError, NotFoundError
from app.core.rbac import ClinicContext
from app.db.base import utcnow
from app.integrations.storage import ObjectStorage
from app.models import ClinicPractitioner, Photo
from app.schemas.common import ViewLink
from app.schemas.photos import PhotoRead, PhotoReview, PhotoSort, PhotoUploadRequest, PhotoUploadResponse
from app.services import audit, uploads

PHOTO_FILES = uploads.FileRule(
    types={"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/heic": "heic"},
    max_bytes=15 * 1024 * 1024,  # open question Q4: 15 MB until decided
)
REPLACED_NOTE = "Replaced by a newer photo"
_LIMITED_CATEGORIES = (PhotoCategory.LOGO, PhotoCategory.COVER)


def list_photos(
    session: Session,
    ctx: ClinicContext,
    *,
    practitioner_id: UUID | None,
    category: PhotoCategory | None,
    review_state: PhotoReviewState | None,
    unsorted: bool,
) -> list[PhotoRead]:
    query = select(Photo).where(Photo.clinic_id == ctx.clinic_id)
    if practitioner_id is not None:
        query = query.where(Photo.practitioner_id == practitioner_id)
    if category is not None:
        query = query.where(Photo.category == category)
    if unsorted:
        query = query.where(Photo.practitioner_id.is_(None), Photo.category.is_(None))
    if review_state is not None:
        query = query.where(Photo.review_state == review_state)
    rows = session.scalars(query.order_by(Photo.created_at.desc(), Photo.id))
    return [PhotoRead.model_validate(p) for p in rows]


def request_upload(
    session: Session, ctx: ClinicContext, body: PhotoUploadRequest, storage: ObjectStorage
) -> PhotoUploadResponse:
    _check_uploader(session, ctx, body.practitioner_id)
    ext = PHOTO_FILES.check(body.content_type, body.size_bytes)
    photo = Photo(
        id=uuid.uuid4(),  # known now: the S3 key contains it
        clinic_id=ctx.clinic_id,
        practitioner_id=body.practitioner_id,
        attire=body.attire,
        outfit_no=body.outfit_no,
        angle=body.angle,
        category=body.category,
        mime_type=body.content_type,
        size_bytes=body.size_bytes,
    )
    photo.original_key = f"clinics/{ctx.clinic_id}/photos/{photo.id}.{ext}"
    session.add(photo)
    session.flush()  # a second waiting photo for the same slot fails here: 409
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action="photo.upload_started",
        resource_type="photo",
        resource_id=photo.id,
        clinic_id=ctx.clinic_id,
    )
    ticket = uploads.ticket(storage, photo.original_key, body.content_type, body.size_bytes)
    session.commit()
    return PhotoUploadResponse(photo=_fresh(session, photo), upload=ticket)


def complete_upload(
    session: Session, ctx: ClinicContext, photo_id: UUID, storage: ObjectStorage
) -> PhotoRead:
    photo = _get(session, ctx, photo_id)
    _check_uploader(session, ctx, photo.practitioner_id)
    if photo.processing_status != ProcessingStatus.UPLOADING:
        raise ConflictError("This upload is already complete.")
    uploads.check_uploaded(storage, photo.original_key, photo.size_bytes, photo.mime_type)
    photo.processing_status = ProcessingStatus.READY
    _audit(session, ctx, photo, "photo.uploaded")
    session.commit()
    return _fresh(session, photo)


def view_link(session: Session, ctx: ClinicContext, photo_id: UUID, storage: ObjectStorage) -> ViewLink:
    photo = _get(session, ctx, photo_id)
    if photo.processing_status == ProcessingStatus.UPLOADING:
        raise ConflictError("The photo is not uploaded yet.")
    url = uploads.view_link(storage, photo.original_key)
    _audit(session, ctx, photo, "photo.viewed")
    session.commit()
    return ViewLink(url=url, expires_in_seconds=uploads.VIEW_URL_TTL_SECONDS)


def review(session: Session, ctx: ClinicContext, photo_id: UUID, body: PhotoReview) -> PhotoRead:
    photo = _get(session, ctx, photo_id)
    if photo.review_state != PhotoReviewState.PENDING:
        raise ConflictError("This photo has already been reviewed.")
    if photo.processing_status != ProcessingStatus.READY:
        raise ConflictError("The photo is not uploaded yet.")
    if body.category is not None:
        if photo.practitioner_id is not None:
            raise InvalidRequestError(
                "A practitioner photo has no category.", fields={"category": "Leave it out."}
            )
        photo.category = body.category
    now = utcnow()
    if body.review_state == PhotoReviewState.APPROVED:
        if photo.practitioner_id is None and photo.category is None:
            raise InvalidRequestError(
                "Sort the photo first.", fields={"category": "Choose a category before approving."}
            )
        old = _live_in_same_slot(session, photo)
        if old is not None:  # the replacement goes live; the old photo is retired first
            old.review_state = PhotoReviewState.REJECTED
            old.review_note = REPLACED_NOTE
            old.reviewed_at = now
            session.flush()
            _audit(session, ctx, old, "photo.replaced")
    photo.review_state = body.review_state
    photo.review_note = body.review_note
    photo.reviewed_at = now
    session.flush()
    _audit(session, ctx, photo, f"photo.{body.review_state.value}")
    session.commit()
    return _fresh(session, photo)


def sort(session: Session, ctx: ClinicContext, photo_id: UUID, body: PhotoSort) -> PhotoRead:
    photo = _get(session, ctx, photo_id)
    if photo.practitioner_id is not None:
        raise InvalidRequestError(
            "A practitioner photo has no category.", fields={"category": "Not for this photo."}
        )
    photo.category = body.category
    session.flush()  # a second live / waiting logo or cover fails here: 409
    _audit(session, ctx, photo, "photo.sorted", {"category": body.category.value})
    session.commit()
    return _fresh(session, photo)


def delete(session: Session, ctx: ClinicContext, photo_id: UUID) -> None:
    photo = _get(session, ctx, photo_id)
    _check_uploader(session, ctx, photo.practitioner_id)
    session.delete(photo)
    _audit(session, ctx, photo, "photo.deleted")
    session.commit()


# ------------------------------------------------------------------------------ helpers
def _check_uploader(session: Session, ctx: ClinicContext, practitioner_id: UUID | None) -> None:
    """Clinic Administrator: any photo of this clinic. Practitioner: his own photos only."""
    if ctx.is_clinic_administrator:
        if (
            practitioner_id is not None
            and session.get(ClinicPractitioner, (ctx.clinic_id, practitioner_id)) is None
        ):
            raise NotFoundError("Practitioner not found at this clinic")
        return
    own = ctx.acting_practitioner_id
    if own is not None and practitioner_id == own:
        return
    raise ForbiddenError(
        "Only the Clinic Administrator, or the practitioner for his own photos, can do this."
    )


def _live_in_same_slot(session: Session, photo: Photo) -> Photo | None:
    query = select(Photo).where(
        Photo.clinic_id == photo.clinic_id,
        Photo.review_state == PhotoReviewState.APPROVED,
        Photo.id != photo.id,
    )
    if photo.practitioner_id is not None:
        query = query.where(
            Photo.practitioner_id == photo.practitioner_id,
            Photo.attire == photo.attire,
            Photo.outfit_no == photo.outfit_no,
            Photo.angle == photo.angle,
        )
    elif photo.category in _LIMITED_CATEGORIES:
        query = query.where(Photo.category == photo.category)
    else:
        return None  # other categories have no limit
    return session.scalar(query)


def _audit(
    session: Session, ctx: ClinicContext, photo: Photo, action: str, details: dict[str, str] | None = None
) -> None:
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action=action,
        resource_type="photo",
        resource_id=photo.id,
        clinic_id=ctx.clinic_id,
        details=details,
    )


def _fresh(session: Session, photo: Photo) -> PhotoRead:
    session.refresh(photo)
    return PhotoRead.model_validate(photo)


def _get(session: Session, ctx: ClinicContext, photo_id: UUID) -> Photo:
    photo = session.get(Photo, photo_id)
    if photo is None or photo.clinic_id != ctx.clinic_id:
        raise NotFoundError("Photo not found")
    return photo
