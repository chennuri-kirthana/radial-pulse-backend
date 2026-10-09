"""Voice samples (docs/01-decisions.md section 7). No review step.

* Seen by the admin, the DSM and the Clinic Administrator; a practitioner sees only his own;
  Clinic Team Members don't see voice samples.
* Uploaded / renamed / deleted by the Clinic Administrator, or the practitioner for his own.
* A title can't be reused for the same practitioner at a clinic (case-insensitive) → 409 with
  "This title is already used. Please give another title."
* Same 3-step upload as photos; every view link is audited.
"""

from __future__ import annotations

import uuid
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ProcessingStatus
from app.core.errors import ConflictError, ForbiddenError, NotFoundError
from app.core.rbac import ClinicContext
from app.integrations.storage import ObjectStorage
from app.models import ClinicPractitioner, VoiceSample
from app.schemas.common import ViewLink
from app.schemas.voice_samples import (
    VoiceSampleRead,
    VoiceSampleRename,
    VoiceSampleUploadRequest,
    VoiceSampleUploadResponse,
)
from app.services import audit, uploads

VOICE_FILES = uploads.FileRule(
    types={
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/aac": "aac",
        "audio/wav": "wav",
        "audio/webm": "webm",
        "audio/ogg": "ogg",
    },
    max_bytes=50 * 1024 * 1024,
)


def list_voice_samples(
    session: Session, ctx: ClinicContext, *, practitioner_id: UUID | None
) -> list[VoiceSampleRead]:
    query = select(VoiceSample).where(VoiceSample.clinic_id == ctx.clinic_id)
    own = ctx.acting_practitioner_id
    if own is not None:  # a practitioner: his own only (also enforced by the database)
        query = query.where(VoiceSample.practitioner_id == own)
    if practitioner_id is not None:
        query = query.where(VoiceSample.practitioner_id == practitioner_id)
    rows = session.scalars(query.order_by(VoiceSample.created_at.desc(), VoiceSample.id))
    return [VoiceSampleRead.model_validate(v) for v in rows]


def request_upload(
    session: Session, ctx: ClinicContext, body: VoiceSampleUploadRequest, storage: ObjectStorage
) -> VoiceSampleUploadResponse:
    _check_uploader(session, ctx, body.practitioner_id)
    ext = VOICE_FILES.check(body.content_type, body.size_bytes)
    sample_id = uuid.uuid4()
    sample = VoiceSample(
        id=sample_id,
        clinic_id=ctx.clinic_id,
        practitioner_id=body.practitioner_id,
        title=body.title,
        original_key=f"clinics/{ctx.clinic_id}/voice/{sample_id}.{ext}",
        mime_type=body.content_type,
        size_bytes=body.size_bytes,
    )
    session.add(sample)
    session.flush()  # a title already used: 409 "This title is already used. Please give another title."
    _audit(session, ctx, sample, "voice_sample.upload_started")
    ticket = uploads.ticket(storage, sample.original_key, body.content_type, body.size_bytes)
    session.commit()
    return VoiceSampleUploadResponse(voice_sample=_fresh(session, sample), upload=ticket)


def complete_upload(
    session: Session, ctx: ClinicContext, sample_id: UUID, storage: ObjectStorage
) -> VoiceSampleRead:
    sample = _get(session, ctx, sample_id)
    _check_uploader(session, ctx, sample.practitioner_id)
    if sample.processing_status != ProcessingStatus.UPLOADING:
        raise ConflictError("This upload is already complete.")
    uploads.check_uploaded(storage, sample.original_key, sample.size_bytes, sample.mime_type)
    sample.processing_status = ProcessingStatus.READY
    _audit(session, ctx, sample, "voice_sample.uploaded")
    session.commit()
    return _fresh(session, sample)


def rename(session: Session, ctx: ClinicContext, sample_id: UUID, body: VoiceSampleRename) -> VoiceSampleRead:
    sample = _get(session, ctx, sample_id)
    _check_uploader(session, ctx, sample.practitioner_id)
    sample.title = body.title
    session.flush()  # a title already used: 409
    _audit(session, ctx, sample, "voice_sample.renamed")
    session.commit()
    return _fresh(session, sample)


def view_link(session: Session, ctx: ClinicContext, sample_id: UUID, storage: ObjectStorage) -> ViewLink:
    sample = _get(session, ctx, sample_id)
    if sample.processing_status == ProcessingStatus.UPLOADING:
        raise ConflictError("The recording is not uploaded yet.")
    url = uploads.view_link(storage, sample.original_key)
    _audit(session, ctx, sample, "voice_sample.viewed")
    session.commit()
    return ViewLink(url=url, expires_in_seconds=uploads.VIEW_URL_TTL_SECONDS)


def delete(session: Session, ctx: ClinicContext, sample_id: UUID) -> None:
    sample = _get(session, ctx, sample_id)
    _check_uploader(session, ctx, sample.practitioner_id)
    session.delete(sample)
    _audit(session, ctx, sample, "voice_sample.deleted")
    session.commit()


def _check_uploader(session: Session, ctx: ClinicContext, practitioner_id: UUID) -> None:
    if ctx.is_clinic_administrator:
        if session.get(ClinicPractitioner, (ctx.clinic_id, practitioner_id)) is None:
            raise NotFoundError("Practitioner not found at this clinic")
        return
    if ctx.acting_practitioner_id is not None and ctx.acting_practitioner_id == practitioner_id:
        return
    raise ForbiddenError(
        "Only the Clinic Administrator, or the practitioner for his own recordings, can do this."
    )


def _audit(session: Session, ctx: ClinicContext, sample: VoiceSample, action: str) -> None:
    audit.record(
        session,
        actor_user_id=ctx.user_id,
        action=action,
        resource_type="voice_sample",
        resource_id=sample.id,
        clinic_id=ctx.clinic_id,
    )


def _fresh(session: Session, sample: VoiceSample) -> VoiceSampleRead:
    session.refresh(sample)
    return VoiceSampleRead.model_validate(sample)


def _get(session: Session, ctx: ClinicContext, sample_id: UUID) -> VoiceSample:
    sample = session.get(VoiceSample, sample_id)
    own = ctx.acting_practitioner_id
    if (
        sample is None
        or sample.clinic_id != ctx.clinic_id
        or (own is not None and sample.practitioner_id != own)
    ):
        raise NotFoundError("Voice sample not found")
    return sample
