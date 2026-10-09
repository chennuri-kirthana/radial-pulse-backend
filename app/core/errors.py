"""Domain errors and the single error response format (RFC 9457 problem details).

Services raise ``AppError`` subclasses. This module does not import FastAPI;
``app.core.error_handlers`` turns these into ``application/problem+json`` responses, and
``app.core.db_errors`` turns database refusals into the same errors (CLAUDE.md error table).

Rules:
* ``detail`` must be safe to show a user: no SQL, no stack traces, no other clinic's data.
* unexpected exceptions become a generic 500 with only the request id.
"""

from __future__ import annotations

from pydantic import BaseModel


class ProblemDetails(BaseModel):
    """The API's only error shape. Published in openapi/openapi.json (frontend types come from it).

    ``fields`` is only sent with 400 ``invalid_request``: field name → what is wrong with it.
    """

    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    request_id: str | None = None
    fields: dict[str, str] | None = None


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    title = "Internal error"

    def __init__(self, detail: str | None = None, fields: dict[str, str] | None = None) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.fields = fields


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    title = "Authentication required"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    title = "Not allowed"


class AccountDisabledError(AppError):
    """No Radial Pulse account for this sign-in, or the account is switched off (CLAUDE.md rule 6)."""

    status_code = 403
    code = "account_disabled"
    title = "Account not active"


#: Older name, kept so existing callers keep working.
NotProvisionedError = AccountDisabledError


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    title = "Not found"


class ConflictError(AppError):
    status_code = 409
    code = "state_conflict"
    title = "Conflict with the current state"


#: Older name for the same 409.
InvalidStateError = ConflictError


class InvalidRequestError(AppError):
    status_code = 400
    code = "invalid_request"
    title = "Invalid request"


#: Older name for the same 400.
DomainValidationError = InvalidRequestError


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    title = "Service unavailable"


class UpstreamError(AppError):
    """Another company's service (Google, Meta, …) refused or failed. Safe to try again later."""

    status_code = 502
    code = "upstream_error"
    title = "The other service did not accept the request"
