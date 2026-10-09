"""The Cognito admin adapter against a stand-in boto3 client (no AWS calls)."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from app.integrations.identity_directory import (
    AlreadySignedUpError,
    CognitoIdentityDirectory,
    IdentityDirectoryError,
)

POOL = "test-pool"  # not a real pool id


def _error(code: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, op)


class FakeIdp:
    def __init__(self, fail: dict[str, str] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail or {}

    def _call(self, op: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((op, kwargs))
        if op in self.fail:
            raise _error(self.fail[op], op)

    def admin_create_user(self, **kw: Any) -> dict[str, Any]:
        self._call("admin_create_user", kw)
        return {"User": {"Attributes": [{"Name": "sub", "Value": "sub-1"}]}}

    def admin_get_user(self, **kw: Any) -> dict[str, Any]:
        self._call("admin_get_user", kw)
        return {"UserAttributes": [{"Name": "sub", "Value": "sub-existing"}]}

    def admin_disable_user(self, **kw: Any) -> None:
        self._call("admin_disable_user", kw)

    def admin_user_global_sign_out(self, **kw: Any) -> None:
        self._call("admin_user_global_sign_out", kw)

    def admin_enable_user(self, **kw: Any) -> None:
        self._call("admin_enable_user", kw)


def test_invite_creates_a_verified_email_user_and_returns_its_sub() -> None:
    idp = FakeIdp()
    account = CognitoIdentityDirectory(POOL, "ap-south-1", client=idp).invite("a@example.test", "Asha")
    assert (account.sub, account.created) == ("sub-1", True)
    op, kw = idp.calls[0]
    assert op == "admin_create_user" and kw["Username"] == "a@example.test" and kw["UserPoolId"] == POOL
    assert {"Name": "email_verified", "Value": "true"} in kw["UserAttributes"]
    assert "TemporaryPassword" not in kw  # Cognito generates it and emails it; we never see it


def test_invite_of_an_existing_cognito_user_links_it_without_email() -> None:
    idp = FakeIdp(fail={"admin_create_user": "UsernameExistsException"})
    account = CognitoIdentityDirectory(POOL, "ap-south-1", client=idp).invite("a@example.test", None)
    assert (account.sub, account.created) == ("sub-existing", False)


def test_resend_falls_back_to_create_and_reports_a_chosen_password() -> None:
    idp = FakeIdp(fail={"admin_create_user": "UnsupportedUserStateException"})
    with pytest.raises(AlreadySignedUpError):
        CognitoIdentityDirectory(POOL, "ap-south-1", client=idp).resend_invite("a@example.test", None)
    idp = FakeIdp()
    CognitoIdentityDirectory(POOL, "ap-south-1", client=idp).resend_invite("a@example.test", None)
    assert idp.calls[0][1]["MessageAction"] == "RESEND"


def test_disable_signs_out_everywhere_and_errors_carry_no_personal_data() -> None:
    idp = FakeIdp()
    CognitoIdentityDirectory(POOL, "ap-south-1", client=idp).disable("a@example.test")
    assert [op for op, _ in idp.calls] == ["admin_disable_user", "admin_user_global_sign_out"]
    idp = FakeIdp(fail={"admin_disable_user": "AccessDeniedException"})
    with pytest.raises(IdentityDirectoryError) as exc:
        CognitoIdentityDirectory(POOL, "ap-south-1", client=idp).disable("a@example.test")
    assert "a@example.test" not in str(exc.value) and "AccessDeniedException" in str(exc.value)
    # A person who never got a Cognito user: nothing to disable.
    idp = FakeIdp(fail={"admin_disable_user": "UserNotFoundException"})
    CognitoIdentityDirectory(POOL, "ap-south-1", client=idp).disable("a@example.test")
