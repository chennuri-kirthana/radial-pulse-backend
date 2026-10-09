"""app/core/iam_caller.py: who is calling /api/v1/internal (no database, no FastAPI)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.core.iam_caller import CallerRejectedError, ServiceRole, identify, role_key

ACCOUNT = "111122223333"
API_ID = "abc123"
SEO_ARN = f"arn:aws:iam::{ACCOUNT}:role/service-role/seo-backend"
ROLES = {role_key(SEO_ARN): (SEO_ARN, ServiceRole(name="seo-agent", scopes=frozenset({"clinics.read"})))}


def header(**overrides: Any) -> str:
    context: dict[str, Any] = {
        "apiId": API_ID,
        "stage": "dev",
        "identity": {
            "accountId": ACCOUNT,
            "userArn": f"arn:aws:sts::{ACCOUNT}:assumed-role/seo-backend/run-42",
        },
    }
    context.update(overrides)
    return json.dumps(context)


def test_role_key_reads_account_and_name_with_or_without_a_path() -> None:
    assert role_key(SEO_ARN) == (ACCOUNT, "seo-backend")
    assert role_key(f"arn:aws:iam::{ACCOUNT}:role/seo-backend") == (ACCOUNT, "seo-backend")
    for bad in (f"arn:aws:iam::{ACCOUNT}:user/seo-backend", "seo-backend", "arn:aws:iam::12:role/x"):
        with pytest.raises(ValueError):
            role_key(bad)


def test_allowed_role_is_identified_whatever_the_session_name() -> None:
    caller = identify(header(), internal_api_id=API_ID, roles=ROLES)
    assert (caller.name, caller.role_arn) == ("seo-agent", SEO_ARN)
    assert caller.scopes == frozenset({"clinics.read"})


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (None, "no request context"),
        ("", "no request context"),
        ("not json", "not JSON"),
        ("[1, 2]", "not an object"),
        (header(apiId="someotherapi"), "not our internal API"),
        (header(identity={}), "no IAM identity"),
        (header(identity={"userArn": None}), "no IAM identity"),
        (header(identity={"userArn": f"arn:aws:iam::{ACCOUNT}:user/seo-backend"}), "not an assumed IAM role"),
        (
            header(identity={"userArn": f"arn:aws:sts::{ACCOUNT}:assumed-role/seo-backend/run-1\n"}),
            "not an assumed IAM role",
        ),
        (
            header(identity={"userArn": "arn:aws:sts::999988887777:assumed-role/seo-backend/run-1"}),
            "not in INTERNAL_SERVICE_ROLES",
        ),
        (
            header(identity={"userArn": f"arn:aws:sts::{ACCOUNT}:assumed-role/other-team/run-1"}),
            "not in INTERNAL_SERVICE_ROLES",
        ),
    ],
)
def test_everything_else_is_rejected(value: str | None, reason: str) -> None:
    with pytest.raises(CallerRejectedError, match=reason):
        identify(value, internal_api_id=API_ID, roles=ROLES)
