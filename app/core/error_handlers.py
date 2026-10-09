"""Maps exceptions to RFC 9457 problem+json responses. Registered once in ``app.main``.

Body: ``type, title, status, code, detail, request_id`` (+ ``fields`` for 400). See CLAUDE.md.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.db_errors import app_error_for
from app.core.errors import AppError, ProblemDetails
from app.core.logging import request_id_ctx

logger = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"
#: Where request data comes from; dropped from field names ("body.fee" → "fee").
_SOURCES = {"body", "query", "path", "header", "cookie"}


def _problem(
    status: int, code: str, title: str, detail: str | None = None, fields: dict[str, str] | None = None
) -> JSONResponse:
    body = ProblemDetails(
        type=code,
        title=title,
        status=status,
        code=code,
        detail=detail,
        request_id=request_id_ctx.get(),
        fields=fields,
    )
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
    return JSONResponse(
        body.model_dump(exclude_none=True), status_code=status, media_type=PROBLEM_JSON, headers=headers
    )


def _app_problem(exc: AppError) -> JSONResponse:
    return _problem(exc.status_code, exc.code, exc.title, exc.detail, exc.fields)


def _field_name(loc: tuple[object, ...] | list[object]) -> str:
    parts = [str(p) for p in loc]
    if len(parts) > 1 and parts[0] in _SOURCES:
        parts = parts[1:]
    return ".".join(parts) or "request"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("app error", extra={"error_code": exc.code})
        return _app_problem(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo the submitted input back (it may contain personal data): only field → message.
        fields: dict[str, str] = {}
        for err in exc.errors():
            fields.setdefault(_field_name(err.get("loc", ())), str(err.get("msg", "Invalid value")))
        return _problem(400, "invalid_request", "Invalid request", "Some values are not valid.", fields)

    @app.exception_handler(DBAPIError)
    async def _database_error(_: Request, exc: DBAPIError) -> JSONResponse:
        mapped = app_error_for(exc)
        if mapped is None:
            logger.exception("database error", extra={"exc_class": exc.orig.__class__.__name__})
            return _problem(500, "internal_error", "Something went wrong. Quote the request id to support.")
        logger.info("database refused", extra={"error_code": mapped.code})
        return _app_problem(mapped)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}
        detail = exc.detail if isinstance(exc.detail, str) else None
        return _problem(exc.status_code, codes.get(exc.status_code, "http_error"), detail or "Request failed")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", extra={"exc_class": exc.__class__.__name__})
        return _problem(500, "internal_error", "Something went wrong. Quote the request id to support.")
