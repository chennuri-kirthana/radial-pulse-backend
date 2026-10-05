from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.routers._common import ERRORS
from app.core.rbac import Principal
from app.dependencies.auth import get_principal
from app.dependencies.db import get_db
from app.schemas.assets import MediaTaxonomyValueRead
from app.services import assets as service

router = APIRouter(prefix="/media", tags=["assets"], responses=ERRORS)


@router.get(
    "/taxonomy",
    response_model=list[MediaTaxonomyValueRead],
    summary="Media labels: photo categories, doctor-photo apron / angle / outfit, voice samples",
)
def list_taxonomy(
    _: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> list[MediaTaxonomyValueRead]:
    """The values to offer when uploading clinic media, grouped by ``dimension`` and in display
    order (``sort_order``). Use the ``code`` in ``POST /clinics/{id}/assets/uploads``. The list
    can grow (e.g. new outfits): build screens from it instead of hard-coding the values."""
    return service.list_taxonomy(db)
