"""Domain errors and the single error response format (RFC 9457 problem details).

Services raise ``AppError`` subclasses. This module does not import FastAPI;
``app.core.error_handlers`` turns these into ``application/problem+json`` responses.

Rules:
* ``detail`` must be safe to show a user: no SQL, no stack traces, no other clinic's data.
* unexpected exceptions become a generic 500 with only the request id.
"""

from __future__ import annotations

from pydantic import BaseModel


class ValidationIssue(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class ProblemDetails(BaseModel):
    """The API's only error shape. Published in openapi/openapi.json (frontend types come from it)."""

    type: str
    title: str
    status: int
    detail: str | None = None
    request_id: str | None = None
    errors: list[ValidationIssue] | None = None


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    title = "Internal error"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    title = "Authentication required"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    title = "Not allowed"


class NotProvisionedError(AppError):
    status_code = 403
    code = "not_provisioned"
    title = "Account not set up"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    title = "Not found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    title = "Conflict"


class InvalidStateError(AppError):
    status_code = 409
    code = "invalid_state"
    title = "Action not allowed in the current state"


class DomainValidationError(AppError):
    status_code = 422
    code = "validation_error"
    title = "Invalid request"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    title = "Service unavailable"


class UpstreamError(AppError):
    """Another company's service (Google, Meta, …) refused or failed. Safe to try again later."""

    status_code = 502
    code = "upstream_error"
    title = "The other service did not accept the request"
