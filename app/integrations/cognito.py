"""Cognito Hosted UI /oauth2/userInfo client.

Used ONCE per user, on first sign-in, to read the verified email for an access
token whose ``sub`` we have not seen yet (access tokens carry no email).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True)
class UserInfo:
    email: str | None
    email_verified: bool
    name: str | None


class UserInfoClient(Protocol):
    def fetch(self, access_token: str) -> UserInfo: ...


class CognitoUserInfoClient:
    def __init__(self, domain: str, timeout_seconds: float = 5.0) -> None:
        self._url = f"{domain.rstrip('/')}/oauth2/userInfo"
        self._timeout = timeout_seconds

    def fetch(self, access_token: str) -> UserInfo:
        response = httpx.get(
            self._url, headers={"Authorization": f"Bearer {access_token}"}, timeout=self._timeout
        )
        response.raise_for_status()
        data = response.json()
        verified = data.get("email_verified")
        return UserInfo(
            email=(data.get("email") or None),
            email_verified=verified is True or str(verified).lower() == "true",
            name=data.get("name"),
        )
