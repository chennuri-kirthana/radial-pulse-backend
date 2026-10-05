from __future__ import annotations

from typing import Annotated

from fastapi import Query

from app.core.errors import ProblemDetails

Limit = Annotated[int, Query(ge=1, le=200, description="Page size")]
Offset = Annotated[int, Query(ge=0, description="Items to skip")]

#: The shape FastAPI expects for ``responses=`` (status code → OpenAPI description).
ErrorResponses = dict[int | str, dict[str, object]]

#: Documented error responses shared by every authenticated route.
ERRORS: ErrorResponses = {
    401: {"model": ProblemDetails, "description": "Missing or invalid token"},
    403: {"model": ProblemDetails, "description": "Authenticated but not allowed"},
    404: {"model": ProblemDetails, "description": "Not found, or no access to this clinic"},
    422: {"model": ProblemDetails, "description": "Validation error"},
}
