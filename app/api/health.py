"""Liveness and readiness probes (unauthenticated, no tenant data)."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import Engine

from app.core.config import get_settings
from app.core.contract import CONTRACT_VERSION
from app.db.session import get_engine, ping

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    version: str
    contract_version: str
    environment: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["ok", "fail"]]


@router.get("/health", response_model=HealthResponse, summary="Liveness: the process is up")
def health() -> HealthResponse:
    s = get_settings()
    return HealthResponse(
        status="ok",
        service=s.service_name,
        version=s.service_version,
        contract_version=CONTRACT_VERSION,
        environment=s.app_env,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
    summary="Readiness: dependencies (database) are reachable",
)
def ready(engine: Engine = Depends(get_engine)) -> JSONResponse:
    checks: dict[str, Literal["ok", "fail"]] = {}
    try:
        ping(engine)
        checks["database"] = "ok"
    except Exception as exc:
        logger.warning(
            "readiness check failed", extra={"check": "database", "exc_class": exc.__class__.__name__}
        )
        checks["database"] = "fail"
    ok = all(v == "ok" for v in checks.values())
    body = ReadinessResponse(status="ready" if ok else "not_ready", checks=checks)
    return JSONResponse(body.model_dump(), status_code=200 if ok else 503)
