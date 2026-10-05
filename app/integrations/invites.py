"""Invite emails ("You've been invited to Radial Pulse — sign in here").

Radial Pulse is invite-only: a person is pre-created, then told to sign in with Google.
Sending is best-effort — a failed email never undoes the user/membership that was created;
the admin can press "Resend invite".

Backends (``INVITE_EMAIL_BACKEND``):
* ``log`` (default) — writes a log line only. Used locally, in tests, and until SES is set up.
* ``ses``           — Amazon SES v2. Needs ``INVITE_FROM_EMAIL`` (a verified SES identity) and
                      the ECS task role allowed to ``ses:SendEmail`` (Person 3 / Terraform).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Invite:
    email: str
    full_name: str | None
    #: Human role label, e.g. "Clinic Administrator".
    role_label: str
    #: Where the person should go to sign in.
    sign_in_url: str
    #: Optional context, e.g. the clinic name.
    clinic_name: str | None = None


class InviteSender(Protocol):
    def send(self, invite: Invite) -> None: ...


class LoggingInviteSender:
    """Does not send anything. Logs that an invite WOULD have been sent (no email address logged)."""

    def send(self, invite: Invite) -> None:
        logger.info("invite email not sent (INVITE_EMAIL_BACKEND=log)", extra={"role": invite.role_label})


class SesInviteSender:
    def __init__(self, from_email: str, region: str, client: Any | None = None) -> None:
        if client is None:
            import boto3

            client = boto3.client("sesv2", region_name=region)
        self._client = client
        self._from = from_email

    def send(self, invite: Invite) -> None:
        greeting = f"Hello {invite.full_name}," if invite.full_name else "Hello,"
        where = f" for {invite.clinic_name}" if invite.clinic_name else ""
        body = (
            f"{greeting}\n\n"
            f"You have been invited to Radial Pulse as {invite.role_label}{where}.\n\n"
            f"Sign in with your Google account ({invite.email}) here:\n{invite.sign_in_url}\n\n"
            "If you were not expecting this email, you can ignore it.\n"
        )
        self._client.send_email(
            FromEmailAddress=self._from,
            Destination={"ToAddresses": [invite.email]},
            Content={
                "Simple": {
                    "Subject": {"Data": "You're invited to Radial Pulse"},
                    "Body": {"Text": {"Data": body}},
                }
            },
        )
