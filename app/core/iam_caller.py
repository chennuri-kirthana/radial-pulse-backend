"""Who is calling /api/v1/internal: an AWS IAM role, checked by API Gateway (no FastAPI in here).

How it works in AWS (decided 9 Oct 2026, replaces Cognito client credentials for backend services):

1. The other team's backend signs its request with its own IAM role (SigV4).
2. The separate **REST API** for /api/v1/internal has ``AWS_IAM`` on every method and Central's
   resource policy (only listed roles, deny everyone else). Unsigned or not-allowed calls never
   reach this code.
3. API Gateway hands the request to our Lambda. The AWS Lambda Web Adapter puts the event's
   ``requestContext`` (JSON) in the header ``x-amzn-request-context``. It REPLACES any header of the
   same name sent by the caller (``req_headers.insert`` in the adapter's source).
4. This module reads ``requestContext.apiId`` (must be our internal REST API) and
   ``requestContext.identity.userArn`` (the caller's role session,
   ``arn:aws:sts::<account>:assumed-role/<role name>/<session>``), then finds the role in
   ``INTERNAL_SERVICE_ROLES``. The session part is ignored on purpose.

The header can only be trusted when the app runs behind the adapter (uvicorn listens on 127.0.0.1
only, see scripts/lambda/run.sh). That is why it is read only when
``INTERNAL_TRUST_LAMBDA_CONTEXT=true``, which is set ONLY on the Lambda function.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

#: Header the AWS Lambda Web Adapter fills with the Lambda event's requestContext (JSON).
REQUEST_CONTEXT_HEADER = "x-amzn-request-context"

#: An IAM role ARN as written in INTERNAL_SERVICE_ROLES (a path like /service-role/ is allowed).
ROLE_ARN = re.compile(
    r"arn:aws:iam::(?P<account>\d{12}):role/(?:[\w+=,.@/-]*/)?(?P<role>[\w+=,.@-]{1,64})", re.ASCII
)
#: The caller as API Gateway reports it: an assumed-role SESSION (no role path in it).
ASSUMED_ROLE = re.compile(
    r"arn:aws:sts::(?P<account>\d{12}):assumed-role/(?P<role>[\w+=,.@-]{1,64})/[^/\s]+", re.ASCII
)


class CallerRejectedError(Exception):
    """The request does not come from an allowed role through our internal API (→ 401)."""


@dataclass(frozen=True)
class ServiceRole:
    """One allowed backend service: its name in logs and which scopes it holds."""

    name: str
    scopes: frozenset[str]


@dataclass(frozen=True)
class IamCaller:
    name: str
    role_arn: str
    scopes: frozenset[str]


def role_key(role_arn: str) -> tuple[str, str]:
    """(account, role name) of a configured role ARN. Raises ValueError if it isn't a role ARN."""
    match = ROLE_ARN.fullmatch(role_arn.strip())
    if not match:
        raise ValueError(f"not an IAM role ARN: {role_arn!r}")
    return match["account"], match["role"]


def identify(
    header_value: str | None,
    *,
    internal_api_id: str,
    roles: dict[tuple[str, str], tuple[str, ServiceRole]],
) -> IamCaller:
    """The allowed caller of this request, or ``CallerRejectedError``.

    ``roles`` maps (account, role name) → (configured role ARN, ServiceRole).
    """
    if not header_value:
        raise CallerRejectedError("no request context")
    try:
        context = json.loads(header_value)
    except (TypeError, ValueError) as exc:
        raise CallerRejectedError("request context is not JSON") from exc
    if not isinstance(context, dict):
        raise CallerRejectedError("request context is not an object")
    if context.get("apiId") != internal_api_id:
        raise CallerRejectedError("not our internal API")
    identity = context.get("identity")
    user_arn = identity.get("userArn") if isinstance(identity, dict) else None
    if not isinstance(user_arn, str):
        raise CallerRejectedError("no IAM identity (route not protected by AWS_IAM?)")
    match = ASSUMED_ROLE.fullmatch(user_arn)
    if not match:
        raise CallerRejectedError("caller is not an assumed IAM role")
    found = roles.get((match["account"], match["role"]))
    if found is None:
        raise CallerRejectedError("role is not in INTERNAL_SERVICE_ROLES")
    role_arn, role = found
    return IamCaller(name=role.name, role_arn=role_arn, scopes=role.scopes)
