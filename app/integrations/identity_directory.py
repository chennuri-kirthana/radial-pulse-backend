"""The sign-in accounts in Amazon Cognito (email + password through Managed Login).

Radial Pulse is invite-only. When an admin invites someone, the API creates their Cognito user
and Cognito emails a temporary password (the invite message is set up in the Cognito console).
The person signs in through Managed Login and chooses their own password. The API stores the
Cognito ``sub`` right away, so the account is linked before the first sign-in.

Deactivating a person in the Users screen also disables their Cognito user and signs them out
everywhere (refresh tokens stop working). Access tokens already issued stay valid until they
expire, but the API checks ``users.is_active`` on every request, so they are refused anyway.

Backends (``IDENTITY_DIRECTORY_BACKEND``):
* ``log``     (default) — changes nothing in Cognito; writes a log line. Local development and tests.
* ``cognito`` — calls the Cognito admin API. The API's task role needs ``cognito-idp:AdminCreateUser``,
                ``AdminGetUser``, ``AdminDisableUser``, ``AdminEnableUser`` and ``AdminUserGlobalSignOut``
                on the user pool (docs/infrastructure/manual-aws-setup.md).

Never log email addresses, passwords or tokens here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class IdentityDirectoryError(Exception):
    """Cognito refused or could not be reached. The message never contains personal data."""


class AlreadySignedUpError(IdentityDirectoryError):
    """The person already chose their password: there is no invite to send again."""


@dataclass(frozen=True)
class InvitedAccount:
    #: The Cognito ``sub`` (None for the ``log`` backend, which creates nothing).
    sub: str | None
    #: False when the account already existed in Cognito (no new email was sent).
    created: bool


class IdentityDirectory(Protocol):
    def invite(self, email: str, full_name: str | None) -> InvitedAccount: ...

    def resend_invite(self, email: str, full_name: str | None) -> InvitedAccount: ...

    def disable(self, email: str) -> None: ...

    def enable(self, email: str) -> None: ...


class LoggingIdentityDirectory:
    """Changes nothing. People invited locally are linked on first sign-in (``/oauth2/userInfo``)."""

    backend = "log"

    def invite(self, email: str, full_name: str | None) -> InvitedAccount:
        logger.info("invite not sent (IDENTITY_DIRECTORY_BACKEND=log)")
        return InvitedAccount(sub=None, created=False)

    def resend_invite(self, email: str, full_name: str | None) -> InvitedAccount:
        return self.invite(email, full_name)

    def disable(self, email: str) -> None:
        logger.info("sign-in not disabled (IDENTITY_DIRECTORY_BACKEND=log)")

    def enable(self, email: str) -> None:
        logger.info("sign-in not enabled (IDENTITY_DIRECTORY_BACKEND=log)")


class CognitoIdentityDirectory:
    """Cognito admin API. The username is the (lower-case) email address."""

    backend = "cognito"

    def __init__(self, user_pool_id: str, region: str, client: Any | None = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("cognito-idp", region_name=region)
        self._idp = client
        self._pool = user_pool_id

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _code(exc: Exception) -> str:
        response = getattr(exc, "response", None) or {}
        return str(response.get("Error", {}).get("Code", exc.__class__.__name__))

    @staticmethod
    def _sub(attributes: list[dict[str, str]]) -> str:
        for attribute in attributes:
            if attribute.get("Name") == "sub":
                return attribute["Value"]
        raise IdentityDirectoryError("Cognito returned a user without a sub")

    def _create(self, email: str, full_name: str | None, *, resend: bool) -> str:
        attributes = [{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}]
        if full_name:
            attributes.append({"Name": "name", "Value": full_name})
        request: dict[str, Any] = {
            "UserPoolId": self._pool,
            "Username": email,
            "DesiredDeliveryMediums": ["EMAIL"],
        }
        if resend:
            request["MessageAction"] = "RESEND"
        else:
            request["UserAttributes"] = attributes
        response = self._idp.admin_create_user(**request)
        return self._sub(response["User"]["Attributes"])

    def _existing_sub(self, email: str) -> str:
        response = self._idp.admin_get_user(UserPoolId=self._pool, Username=email)
        return self._sub(response["UserAttributes"])

    # ------------------------------------------------------------------ API
    def invite(self, email: str, full_name: str | None) -> InvitedAccount:
        try:
            return InvitedAccount(sub=self._create(email, full_name, resend=False), created=True)
        except Exception as exc:
            if self._code(exc) == "UsernameExistsException":
                # Already has a sign-in (e.g. invited to another clinic): link it, send nothing.
                try:
                    return InvitedAccount(sub=self._existing_sub(email), created=False)
                except Exception as inner:
                    raise IdentityDirectoryError(
                        f"Cognito AdminGetUser failed: {self._code(inner)}"
                    ) from inner
            raise IdentityDirectoryError(f"Cognito AdminCreateUser failed: {self._code(exc)}") from exc

    def resend_invite(self, email: str, full_name: str | None) -> InvitedAccount:
        try:
            return InvitedAccount(sub=self._create(email, full_name, resend=True), created=True)
        except Exception as exc:
            code = self._code(exc)
            if code == "UserNotFoundException":
                return self.invite(email, full_name)  # the first invite never reached Cognito
            if code == "UnsupportedUserStateException":
                raise AlreadySignedUpError("This person already chose a password") from exc
            raise IdentityDirectoryError(f"Cognito AdminCreateUser (resend) failed: {code}") from exc

    def disable(self, email: str) -> None:
        try:
            self._idp.admin_disable_user(UserPoolId=self._pool, Username=email)
            # Refresh tokens stop working at once (access tokens expire on their own).
            self._idp.admin_user_global_sign_out(UserPoolId=self._pool, Username=email)
        except Exception as exc:
            if self._code(exc) == "UserNotFoundException":
                return
            raise IdentityDirectoryError(f"Cognito disable failed: {self._code(exc)}") from exc

    def enable(self, email: str) -> None:
        try:
            self._idp.admin_enable_user(UserPoolId=self._pool, Username=email)
        except Exception as exc:
            if self._code(exc) == "UserNotFoundException":
                return
            raise IdentityDirectoryError(f"Cognito enable failed: {self._code(exc)}") from exc
