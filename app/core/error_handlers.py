"""Maps exceptions to RFC 9457 problem+json responses. Registered once in ``app.main``."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import AppError, ProblemDetails, ValidationIssue
from app.core.logging import request_id_ctx

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


def _problem(status: int, code: str, title: str, detail: str | None = None, **extra: Any) -> JSONResponse:
    body = ProblemDetails(
        type=code, title=title, status=status, detail=detail, request_id=request_id_ctx.get(), **extra
    )
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(
        body.model_dump(exclude_none=True), status_code=status, media_type=PROBLEM_JSON, headers=headers
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("app error", extra={"error_code": exc.code})
        return _problem(exc.status_code, exc.code, exc.title, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo the submitted input back (it may contain personal data).
        issues = [
            ValidationIssue(
                loc=list(err.get("loc", [])), msg=str(err.get("msg", "")), type=str(err.get("type"))
            )
            for err in exc.errors()
        ]
        return _problem(422, "validation_error", "Invalid request", errors=issues)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}
        detail = exc.detail if isinstance(exc.detail, str) else None
        return _problem(exc.status_code, codes.get(exc.status_code, "http_error"), detail or "Request failed")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", extra={"exc_class": exc.__class__.__name__})
        return _problem(500, "internal_error", "Something went wrong. Quote the request id to support.")
