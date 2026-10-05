"""Connected accounts ("Connect Your Accounts"): OAuth with Google, Meta, LinkedIn and X.

Safety rules (docs/architecture/chat-connections-settings.md):
* Tokens go to AWS Secrets Manager; the database keeps only the secret's ARN. Never logged, never
  returned by the API, never in the audit log.
* ``state`` is a one-time random value; only its SHA-256 is stored. It is tied to ONE clinic, ONE
  platform and the person who pressed Connect, and expires (``OAUTH_STATE_TTL_SECONDS``).
* PKCE (S256) wherever the platform supports it.
* The redirect address must be on the server's allowed list (``OAUTH_REDIRECT_URIS``).
* We ask only for READ permissions (insights, reviews, followers). Nothing that posts.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import ConnectionPlatform, ConnectionStatus
from app.core.errors import (
    DomainValidationError,
    InvalidStateError,
    NotFoundError,
    ServiceUnavailableError,
    UpstreamError,
)
from app.core.rbac import ClinicContext
from app.db.base import utcnow
from app.integrations.oauth import (
    PLATFORM_LABELS,
    PLATFORM_PROVIDER,
    PLATFORM_SCOPES,
    OAuthClient,
    OAuthError,
    authorization_url,
    configured_providers,
    provider_for,
)
from app.integrations.secrets import SecretStore
from app.models import PlatformConnection
from app.repositories.connections import ConnectionRepository
from app.schemas.connections import (
    ConnectionCompleteRequest,
    ConnectionRead,
    ConnectionStartRequest,
    ConnectionStartResponse,
)
from app.services import audit

_ACTIVE = (ConnectionStatus.CONNECTED, ConnectionStatus.NEEDS_RECONNECT)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def secret_name(settings: Settings, clinic_id: object, platform: ConnectionPlatform) -> str:
    return f"{settings.connection_secrets_prefix}/{settings.app_env}/connections/{clinic_id}/{platform.value}"


def _clear_sign_in(row: PlatformConnection) -> None:
    row.oauth_state_hash = None
    row.oauth_code_verifier = None
    row.oauth_redirect_uri = None
    row.oauth_started_at = None
    row.oauth_started_by_user_id = None


def _sign_in_expired(row: PlatformConnection, settings: Settings) -> bool:
    started = row.oauth_started_at
    return started is None or _aware(started) + timedelta(seconds=settings.oauth_state_ttl_seconds) < utcnow()


def _read(
    platform: ConnectionPlatform, row: PlatformConnection | None, available: bool, settings: Settings
) -> ConnectionRead:
    label = PLATFORM_LABELS[platform]
    if row is None:
        return ConnectionRead(
            platform=platform, label=label, status=ConnectionStatus.NOT_CONNECTED, available=available
        )
    status = row.status
    if status is ConnectionStatus.PENDING and _sign_in_expired(row, settings):
        status = ConnectionStatus.NOT_CONNECTED  # an abandoned first Connect
    return ConnectionRead(
        platform=platform,
        label=label,
        status=status,
        available=available,
        external_account_name=row.external_account_name,
        scopes=list(row.scopes or []),
        connected_at=row.connected_at if status in _ACTIVE else None,
        connected_by_user_id=row.connected_by_user_id if status in _ACTIVE else None,
        token_expires_at=row.token_expires_at if status in _ACTIVE else None,
        last_synced_at=row.last_synced_at,
        last_error=row.last_error,
    )


def list_connections(session: Session, ctx: ClinicContext, settings: Settings) -> list[ConnectionRead]:
    rows = {row.platform: row for row in ConnectionRepository(session).list_for_clinic(ctx.clinic_id)}
    ready = configured_providers(settings)
    return [
        _read(platform, rows.get(platform), PLATFORM_PROVIDER[platform] in ready, settings)
        for platform in ConnectionPlatform
    ]


def get_connection(
    session: Session, ctx: ClinicContext, platform: ConnectionPlatform, settings: Settings
) -> ConnectionRead:
    row = ConnectionRepository(session).get(ctx.clinic_id, platform)
    return _read(platform, row, provider_for(platform, settings) is not None, settings)


def start(
    session: Session,
    ctx: ClinicContext,
    platform: ConnectionPlatform,
    data: ConnectionStartRequest,
    settings: Settings,
) -> ConnectionStartResponse:
    provider = provider_for(platform, settings)
    if provider is None:
        raise ServiceUnavailableError(f"{PLATFORM_LABELS[platform]} connection is not set up yet")
    if data.redirect_uri not in settings.oauth_redirect_uris:
        raise DomainValidationError("redirect_uri is not on the allowed list")

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)  # 86 characters (PKCE allows 43-128)
    repo = ConnectionRepository(session)
    row = repo.get(ctx.clinic_id, platform)
    if row is None:
        row = repo.add(
            PlatformConnection(clinic_id=ctx.clinic_id, platform=platform, status=ConnectionStatus.PENDING)
        )
    elif row.status in (ConnectionStatus.DISCONNECTED, ConnectionStatus.NOT_CONNECTED):
        row.status = ConnectionStatus.PENDING
    # A connected account stays "connected" while the clinic reconnects; only the sign-in fields change.
    now = utcnow()
    row.oauth_state_hash = _hash(state)
    row.oauth_code_verifier = verifier if provider.uses_pkce else None
    row.oauth_redirect_uri = data.redirect_uri
    row.oauth_started_at = now
    row.oauth_started_by_user_id = ctx.user_id
    audit.record(
        session,
        actor=ctx.principal,
        action="connection.start",
        resource_type="platform_connection",
        resource_id=row.id,
        clinic_id=ctx.clinic_id,
        details={"platform": platform.value},
    )
    session.commit()
    return ConnectionStartResponse(
        platform=platform,
        authorization_url=authorization_url(
            provider,
            PLATFORM_SCOPES[platform],
            redirect_uri=data.redirect_uri,
            state=state,
            code_verifier=verifier if provider.uses_pkce else None,
        ),
        expires_at=now + timedelta(seconds=settings.oauth_state_ttl_seconds),
    )


def complete(
    session: Session,
    ctx: ClinicContext,
    platform: ConnectionPlatform,
    data: ConnectionCompleteRequest,
    settings: Settings,
    oauth: OAuthClient,
    store: SecretStore,
) -> ConnectionRead:
    provider = provider_for(platform, settings)
    if provider is None:
        raise ServiceUnavailableError(f"{PLATFORM_LABELS[platform]} connection is not set up yet")
    row = ConnectionRepository(session).get(ctx.clinic_id, platform, for_update=True)
    if row is None or row.oauth_state_hash is None or row.oauth_redirect_uri is None:
        raise InvalidStateError("No connection is in progress. Press Connect again.")
    if not hmac.compare_digest(_hash(data.state), row.oauth_state_hash):
        raise DomainValidationError("This sign-in does not match the one that was started")
    if row.oauth_started_by_user_id != ctx.user_id:
        raise DomainValidationError("Finish the connection with the same account that started it")

    current: PlatformConnection = row  # (a closure does not keep the "not None" check)

    def give_up(message: str, status_if_new: ConnectionStatus) -> None:
        _clear_sign_in(current)
        if current.status is ConnectionStatus.PENDING:  # a first Connect: show why it failed
            current.status = status_if_new
            current.last_error = message
        # A reconnect that failed leaves the working connection (and its card) as it was.
        session.commit()

    if _sign_in_expired(row, settings):
        give_up("The sign-in took too long. Press Connect again.", ConnectionStatus.NOT_CONNECTED)
        raise InvalidStateError("The sign-in took too long. Press Connect again.")

    try:
        tokens = oauth.exchange_code(
            provider,
            code=data.code,
            redirect_uri=row.oauth_redirect_uri,
            code_verifier=row.oauth_code_verifier,
            scopes=PLATFORM_SCOPES[platform],
        )
    except OAuthError as exc:
        give_up(f"{PLATFORM_LABELS[platform]} did not accept the connection. Please try again.",
                ConnectionStatus.NOT_CONNECTED)  # fmt: skip
        raise UpstreamError(str(exc)) from exc

    row.secret_ref = store.save(
        secret_name(settings, ctx.clinic_id, platform),
        {"platform": platform.value, "clinic_id": str(ctx.clinic_id), **tokens.secret_fields()},
    )
    now = utcnow()
    _clear_sign_in(row)
    row.status = ConnectionStatus.CONNECTED
    row.scopes = tokens.scopes
    row.token_expires_at = tokens.expires_at
    row.connected_at = now
    row.connected_by_user_id = ctx.user_id
    row.disconnected_at = None
    row.last_error = None
    audit.record(
        session,
        actor=ctx.principal,
        action="connection.connected",
        resource_type="platform_connection",
        resource_id=row.id,
        clinic_id=ctx.clinic_id,
        details={"platform": platform.value, "scopes": tokens.scopes},
    )
    session.commit()
    return _read(platform, row, True, settings)


def disconnect(
    session: Session,
    ctx: ClinicContext,
    platform: ConnectionPlatform,
    settings: Settings,
    store: SecretStore,
) -> ConnectionRead:
    row = ConnectionRepository(session).get(ctx.clinic_id, platform)
    if row is None or row.status not in (*_ACTIVE, ConnectionStatus.PENDING):
        raise NotFoundError(f"{PLATFORM_LABELS[platform]} is not connected")
    if row.secret_ref:
        store.delete(row.secret_ref)
    _clear_sign_in(row)
    row.status = ConnectionStatus.DISCONNECTED
    row.secret_ref = None
    row.token_expires_at = None
    row.disconnected_at = utcnow()
    row.last_error = None
    audit.record(
        session,
        actor=ctx.principal,
        action="connection.disconnected",
        resource_type="platform_connection",
        resource_id=row.id,
        clinic_id=ctx.clinic_id,
        details={"platform": platform.value},
    )
    session.commit()
    return _read(platform, row, provider_for(platform, settings) is not None, settings)
