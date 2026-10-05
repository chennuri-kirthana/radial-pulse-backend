"""OAuth 2.0 sign-in with the platforms a clinic can connect (Google, Meta, LinkedIn, X).

Flow ("Connect" button — docs/architecture/chat-connections-settings.md):
  1. API ``…/connections/{platform}/start`` builds the platform's sign-in address (this module).
  2. The app opens it; the clinic signs in and allows access; the platform sends the browser back
     to our frontend's redirect address with ``?code=…&state=…``.
  3. The frontend posts code + state to ``…/connections/{platform}/complete``; the API swaps the
     code for tokens HERE (server to server, with the client secret) and stores them in
     AWS Secrets Manager.

The authorize/token addresses and scopes below follow each platform's public docs (Sep 2026).
Before PROD, check them against the app you registered with each platform: Meta and LinkedIn
also need an app review before real clinics can grant these permissions.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from app.core.config import Settings
from app.core.enums import ConnectionPlatform


@dataclass(frozen=True)
class OAuthProvider:
    key: str  # google | meta | linkedin | x
    authorize_url: str
    token_url: str
    client_id: str
    client_secret: str
    uses_pkce: bool
    scope_separator: str = " "
    #: Send client id/secret as HTTP Basic auth instead of in the form (X requires this).
    basic_auth: bool = False
    extra_authorize_params: dict[str, str] = field(default_factory=dict)


#: Which sign-in each platform uses.
PLATFORM_PROVIDER: dict[ConnectionPlatform, str] = {
    ConnectionPlatform.GOOGLE_BUSINESS_PROFILE: "google",
    ConnectionPlatform.YOUTUBE: "google",
    ConnectionPlatform.INSTAGRAM: "meta",
    ConnectionPlatform.FACEBOOK: "meta",
    ConnectionPlatform.LINKEDIN: "linkedin",
    ConnectionPlatform.X: "x",
}

#: Read-only permissions we ask for (reviews, insights, followers). Nothing that posts.
PLATFORM_SCOPES: dict[ConnectionPlatform, list[str]] = {
    ConnectionPlatform.GOOGLE_BUSINESS_PROFILE: ["https://www.googleapis.com/auth/business.manage"],
    ConnectionPlatform.YOUTUBE: [
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ],
    ConnectionPlatform.INSTAGRAM: [
        "instagram_basic",
        "instagram_manage_insights",
        "pages_show_list",
        "pages_read_engagement",
        "business_management",
    ],
    ConnectionPlatform.FACEBOOK: ["pages_show_list", "pages_read_engagement", "read_insights"],
    ConnectionPlatform.LINKEDIN: ["r_organization_social", "rw_organization_admin"],
    ConnectionPlatform.X: ["tweet.read", "users.read", "offline.access"],
}

PLATFORM_LABELS: dict[ConnectionPlatform, str] = {
    ConnectionPlatform.GOOGLE_BUSINESS_PROFILE: "Google Business Profile",
    ConnectionPlatform.INSTAGRAM: "Instagram",
    ConnectionPlatform.FACEBOOK: "Facebook",
    ConnectionPlatform.YOUTUBE: "YouTube",
    ConnectionPlatform.LINKEDIN: "LinkedIn",
    ConnectionPlatform.X: "X",
}


def configured_providers(settings: Settings) -> dict[str, OAuthProvider]:
    """The providers whose client id AND secret are set. Missing ones = "not set up yet"."""
    out: dict[str, OAuthProvider] = {}
    if settings.google_oauth_client_id and settings.google_oauth_client_secret:
        out["google"] = OAuthProvider(
            key="google",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",  # noqa: S106 - a URL, not a secret
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret.get_secret_value(),
            uses_pkce=True,
            # offline = also give a refresh token; consent = always ask, so we get it again on reconnect
            extra_authorize_params={
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
            },
        )
    if settings.meta_app_id and settings.meta_app_secret:
        out["meta"] = OAuthProvider(
            key="meta",
            authorize_url="https://www.facebook.com/v21.0/dialog/oauth",
            token_url="https://graph.facebook.com/v21.0/oauth/access_token",  # noqa: S106
            client_id=settings.meta_app_id,
            client_secret=settings.meta_app_secret.get_secret_value(),
            uses_pkce=False,
            scope_separator=",",
        )
    if settings.linkedin_client_id and settings.linkedin_client_secret:
        out["linkedin"] = OAuthProvider(
            key="linkedin",
            authorize_url="https://www.linkedin.com/oauth/v2/authorization",
            token_url="https://www.linkedin.com/oauth/v2/accessToken",  # noqa: S106
            client_id=settings.linkedin_client_id,
            client_secret=settings.linkedin_client_secret.get_secret_value(),
            uses_pkce=False,
        )
    if settings.x_client_id and settings.x_client_secret:
        out["x"] = OAuthProvider(
            key="x",
            authorize_url="https://x.com/i/oauth2/authorize",
            token_url="https://api.x.com/2/oauth2/token",  # noqa: S106
            client_id=settings.x_client_id,
            client_secret=settings.x_client_secret.get_secret_value(),
            uses_pkce=True,
            basic_auth=True,
        )
    return out


def provider_for(platform: ConnectionPlatform, settings: Settings) -> OAuthProvider | None:
    return configured_providers(settings).get(PLATFORM_PROVIDER[platform])


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def authorization_url(
    provider: OAuthProvider,
    scopes: list[str],
    *,
    redirect_uri: str,
    state: str,
    code_verifier: str | None,
) -> str:
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "scope": provider.scope_separator.join(scopes),
        "state": state,
        **provider.extra_authorize_params,
    }
    if provider.uses_pkce and code_verifier:
        params["code_challenge"] = pkce_challenge(code_verifier)
        params["code_challenge_method"] = "S256"
    return f"{provider.authorize_url}?{urlencode(params)}"


@dataclass(frozen=True)
class TokenSet:
    """What the platform gave back. ``secret_fields`` go to Secrets Manager, never to the database."""

    access_token: str
    refresh_token: str | None
    token_type: str | None
    scopes: list[str]
    expires_at: datetime | None

    def secret_fields(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "scopes": self.scopes,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


class OAuthError(Exception):
    """The platform refused the code (expired, already used, wrong redirect, app not approved…)."""


class OAuthClient(Protocol):
    def exchange_code(
        self,
        provider: OAuthProvider,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str | None,
        scopes: list[str],
    ) -> TokenSet: ...


def parse_token_response(payload: dict[str, Any], requested: list[str]) -> TokenSet:
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise OAuthError("The platform did not return an access token")
    granted = payload.get("scope")
    if isinstance(granted, str) and granted:
        scopes = [s for s in granted.replace(",", " ").split(" ") if s]
    else:
        scopes = requested
    expires_in = payload.get("expires_in")
    expires_at = (
        datetime.now(UTC) + timedelta(seconds=int(expires_in))
        if isinstance(expires_in, int | float | str) and str(expires_in).isdigit()
        else None
    )
    refresh = payload.get("refresh_token")
    token_type = payload.get("token_type")
    return TokenSet(
        access_token=token,
        refresh_token=refresh if isinstance(refresh, str) else None,
        token_type=token_type if isinstance(token_type, str) else None,
        scopes=scopes,
        expires_at=expires_at,
    )


class HttpxOAuthClient:
    """Real token exchange. Never logs the code, the tokens or the response body."""

    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout = timeout_seconds

    def exchange_code(
        self,
        provider: OAuthProvider,
        *,
        code: str,
        redirect_uri: str,
        code_verifier: str | None,
        scopes: list[str],
    ) -> TokenSet:
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
        form["client_id"] = provider.client_id
        auth: tuple[str, str] | None = None
        if provider.basic_auth:
            auth = (provider.client_id, provider.client_secret)
        else:
            form["client_secret"] = provider.client_secret
        if provider.uses_pkce and code_verifier:
            form["code_verifier"] = code_verifier
        try:
            response = httpx.post(
                provider.token_url,
                data=form,
                auth=auth,
                timeout=self.timeout,
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise OAuthError(f"Could not reach {provider.key}") from exc
        if response.status_code >= 400:
            raise OAuthError(f"{provider.key} refused the sign-in (HTTP {response.status_code})")
        try:
            payload = response.json()
        except ValueError as exc:
            raise OAuthError(f"{provider.key} sent an unreadable answer") from exc
        if not isinstance(payload, dict):
            raise OAuthError(f"{provider.key} sent an unreadable answer")
        return parse_token_response(payload, scopes)
