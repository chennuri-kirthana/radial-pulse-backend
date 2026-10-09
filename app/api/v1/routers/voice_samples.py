"""Voice samples: practitioners' voice recordings (no review)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.rbac import ClinicContext, Permission
from app.dependencies.adapters import get_storage
from app.dependencies.db import get_db
from app.dependencies.tenancy import clinic_access
from app.integrations.storage import ObjectStorage
from app.schemas.common import ViewLink
from app.schemas.voice_samples import (
    VoiceSampleRead,
    VoiceSampleRename,
    VoiceSampleUploadRequest,
    VoiceSampleUploadResponse,
)
from app.services import voice_samples

router = APIRouter(prefix="/clinics/{clinic_id}/voice-samples", tags=["voice samples"], responses=ERRORS)
_read = clinic_access(Permission.VOICE_SAMPLES_READ)
_upload = clinic_access(Permission.VOICE_SAMPLES_UPLOAD)


@router.get("", response_model=list[VoiceSampleRead])
def list_voice_samples(
    practitioner_id: UUID | None = None, ctx: ClinicContext = Depends(_read), db: Session = Depends(get_db)
) -> list[VoiceSampleRead]:
    """Admin, DSM, Clinic Administrator; a practitioner sees his own only. Team Members: 403."""
    return voice_samples.list_voice_samples(db, ctx, practitioner_id=practitioner_id)


@router.post("/uploads", response_model=VoiceSampleUploadResponse, status_code=status.HTTP_201_CREATED)
def request_upload(
    body: VoiceSampleUploadRequest,
    ctx: ClinicContext = Depends(_upload),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> VoiceSampleUploadResponse:
    """Step 1. Audio (MP3, M4A, AAC, WAV, WebM, OGG), at most 50 MB. A used title → 409."""
    return voice_samples.request_upload(db, ctx, body, storage)


@router.post(
    "/{voice_sample_id}/complete", response_model=VoiceSampleRead, summary="Step 2: the file is in S3"
)
def complete_upload(
    voice_sample_id: UUID,
    ctx: ClinicContext = Depends(_upload),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> VoiceSampleRead:
    return voice_samples.complete_upload(db, ctx, voice_sample_id, storage)


@router.patch("/{voice_sample_id}", response_model=VoiceSampleRead, summary="Rename")
def rename(
    voice_sample_id: UUID,
    body: VoiceSampleRename,
    ctx: ClinicContext = Depends(_upload),
    db: Session = Depends(get_db),
) -> VoiceSampleRead:
    return voice_samples.rename(db, ctx, voice_sample_id, body)


@router.get("/{voice_sample_id}/view", response_model=ViewLink, summary="Short-lived link to listen")
def view_link(
    voice_sample_id: UUID,
    ctx: ClinicContext = Depends(_read),
    db: Session = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
) -> ViewLink:
    """Every link handed out is audited."""
    return voice_samples.view_link(db, ctx, voice_sample_id, storage)


@router.delete("/{voice_sample_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    voice_sample_id: UUID, ctx: ClinicContext = Depends(_upload), db: Session = Depends(get_db)
) -> None:
    voice_samples.delete(db, ctx, voice_sample_id)
