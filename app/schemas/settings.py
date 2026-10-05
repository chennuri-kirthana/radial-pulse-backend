from __future__ import annotations

from datetime import datetime
from zoneinfo import available_timezones

from pydantic import Field, field_validator

from app.core.enums import ConnectionPlatform, DateFormat, NotificationCategory, NotificationChannel
from app.schemas.common import ApiModel, Email, PatchModel


# ------------------------------------------------------------------ platform (Admin → General)
class PlatformSettingsRead(ApiModel):
    organization_name: str
    support_email: str | None
    support_phone: str | None
    #: IANA timezone for showing dates, e.g. "Asia/Kolkata". Times in the API are always UTC.
    timezone: str
    date_format: DateFormat
    updated_at: datetime | None = None


class PlatformSettingsUpdate(PatchModel):
    not_null_fields = ("organization_name", "timezone", "date_format")

    organization_name: str | None = Field(default=None, min_length=1, max_length=200)
    support_email: Email | None = None
    support_phone: str | None = Field(default=None, max_length=32)
    timezone: str | None = Field(default=None, max_length=64)
    date_format: DateFormat | None = None

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        if value is not None and value not in available_timezones():
            raise ValueError("not a known timezone (use a name like Asia/Kolkata)")
        return value


# ------------------------------------------------------------------ integrations (Admin → Integrations)
class PlatformIntegration(ApiModel):
    platform: ConnectionPlatform
    label: str
    #: True = the app credentials are set up, so clinics can press Connect.
    configured: bool


class IntegrationsStatus(ApiModel):
    """What is switched on in this environment. Never contains secrets."""

    connections: list[PlatformIntegration]
    #: "ses" = invite emails are really sent; "log" = only written to the logs (not set up yet).
    invite_email: str
    #: Photo/file uploads work (S3 bucket set).
    file_storage: bool
    #: "s3" or "local" (old rows are archived to a folder — local development only).
    archive: str


# ------------------------------------------------------------------ my notification switches
class NotificationSetting(ApiModel):
    category: NotificationCategory
    channel: NotificationChannel
    enabled: bool


class NotificationSettings(ApiModel):
    """Every category and channel, with its current value (default: on).

    ``email`` switches are saved now; emails for notifications will be sent in a later version.
    """

    items: list[NotificationSetting]


class NotificationSettingsUpdate(ApiModel):
    #: Only the switches you want to change.
    items: list[NotificationSetting] = Field(min_length=1, max_length=50)


# ------------------------------------------------------------------ my profile photo
class AvatarUploadRequest(ApiModel):
    mime_type: str = Field(max_length=127)
    size_bytes: int = Field(gt=0)


class AvatarUploadResponse(ApiModel):
    #: PUT the file here (with these headers) straight to S3, then call ``…/avatar/confirm``.
    upload_url: str
    headers: dict[str, str]
    key: str
    expires_at: datetime


class AvatarConfirm(ApiModel):
    key: str = Field(max_length=512)
