"""Errors raised by the SDK. Messages never contain AWS credentials or signatures."""

from __future__ import annotations


class CentralError(Exception):
    """Base class for every SDK error."""


class ConfigurationError(CentralError):
    """A setting is missing or unsafe (e.g. a non-https address)."""


class SigningError(CentralError):
    """The request could not be signed with the service's IAM role (e.g. no AWS credentials)."""


class CentralApiError(CentralError):
    """The Central API answered with an error (problem+json)."""

    def __init__(
        self,
        status_code: int,
        problem_type: str | None,
        title: str | None,
        detail: str | None,
        request_id: str | None,
    ) -> None:
        self.status_code = status_code
        self.problem_type = problem_type
        self.title = title
        self.detail = detail
        #: Quote this when asking the Central team about a failed call.
        self.request_id = request_id
        super().__init__(
            f"HTTP {status_code} {problem_type or ''}: {detail or title or ''} (request {request_id})"
        )
